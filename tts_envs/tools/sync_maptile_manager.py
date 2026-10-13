#!/usr/bin/env python3
"""Inline data/maptile.xlsx into the Maptile Manager's script and stage it.

  data/maptile.xlsx  ->  MAPTILE  ->  src/maptile_manager.lua  ->  .tts/objects/<nickname>.b77050.lua

Sheets read (tools/scaffold_maptile_xlsx.py creates and tops them up):

  <deck> x5            biome, pattern, orientation, density, image, file, url
  backs                deck, name, image, file, url
  biome_descriptions   biome, deck, name, description
  maptile_table        gmnotes, <whatever Render will need>
  density              density, explorations
  weights              param, pool        ("a|b|b": b is twice as likely)

Only images WITH a url reach the game; the rest are counted and reported, so
the manager works while the upload is still in progress. A Google Drive
share-page link is rewritten to its direct-download form on the way through.

Run: python tools/sync_maptile_manager.py
"""
import io, os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasets import ROOT, MAPTILES, load, read_rows
from spawn_cells import staged_path

MANAGER_GUID = "b77050"
SRC = os.path.join(ROOT, "src", "maptile_manager.lua")
BEGIN = "--[[ BEGIN GENERATED MAPTILE DATA -- do not edit ]]"
END = "--[[ END GENERATED MAPTILE DATA ]]"
DRIVE_PAGE = re.compile(r"https?://drive\.google\.com/(?:file/d/([\w-]+)|open\?id=([\w-]+))")


def warn(msg):
  print("  warning: " + msg)


def lua_str(s):
  s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
  return '"' + s + '"'


def lua_list(items):
  return "{" + ", ".join(lua_str(i) for i in items) + "}"


def direct_url(url, where):
  """Drive share pages are HTML, not images -- TTS needs uc?export=download."""
  m = DRIVE_PAGE.match(url)
  if m:
    return "https://drive.google.com/uc?export=download&id=" + (m.group(1) or m.group(2)), True
  if url and not url.startswith(("http://", "https://")):
    sys.exit("%s: url %r is not a web address" % (where, url))
  return url, False


def main():
  if not os.path.exists(MAPTILES):
    sys.exit("missing %s -- run tools/scaffold_maptile_xlsx.py first" % MAPTILES)
  wb = load(MAPTILES)
  converted = 0

  # decks, in backs-sheet order
  decks = []
  for r in read_rows(MAPTILES, "backs", "deck", wb):
    url, conv = direct_url(r.get("url", ""), r["_where"])
    converted += conv
    if not url:
      warn("%s: deck %s has no back url -- its tiles spawn with the template's back"
           % (r["_where"], r["deck"]))
    decks.append({"id": r["deck"], "name": r.get("name") or r["deck"], "back": url, "biomes": []})
  deck_ids = {d["id"]: d for d in decks}

  biomes = {}
  for r in read_rows(MAPTILES, "biome_descriptions", "biome", wb):
    if r.get("deck") not in deck_ids:
      sys.exit("%s: deck %r is not on the backs sheet" % (r["_where"], r.get("deck")))
    biomes[r["biome"]] = {"deck": r["deck"], "name": r.get("name") or r["biome"].title(),
                          "description": r.get("description", "")}
    deck_ids[r["deck"]]["biomes"].append(r["biome"])

  images, patterns, orientations, densities = {}, [], {}, set()
  total = missing = 0
  for d in decks:
    if d["id"] not in wb.sheetnames:
      sys.exit("maptile.xlsx has no sheet for deck %r" % d["id"])
    for r in read_rows(MAPTILES, d["id"], "image", wb):
      where = r["_where"]
      biome, pattern, orient, dens = r.get("biome"), r.get("pattern"), r.get("orientation"), r.get("density")
      if biomes.get(biome, {}).get("deck") != d["id"]:
        sys.exit("%s: biome %r is not a %s biome on biome_descriptions" % (where, biome, d["id"]))
      if not (pattern and orient and dens):
        sys.exit("%s: needs pattern, orientation and density" % where)
      if pattern not in patterns:
        patterns.append(pattern)
      if orient not in orientations.setdefault(pattern, []):
        orientations[pattern].append(orient)
      densities.add(dens)
      total += 1
      url, conv = direct_url(r.get("url", ""), where)
      converted += conv
      if not url:
        missing += 1
        continue
      images["|".join((biome, pattern, orient, dens))] = url
  densities = sorted(densities, key=int)

  explore = {}
  for r in read_rows(MAPTILES, "density", "density", wb):
    try:
      explore[r["density"]] = int(r.get("explorations") or 0)
    except ValueError:
      sys.exit("%s: explorations must be a whole number" % r["_where"])
  for dens in densities:
    if dens not in explore:
      sys.exit("maptile.xlsx density sheet has no row for density %s" % dens)

  # weights: every pool checked against what it may contain; a missing pool = everything, evenly
  allowed = {"deck": [d["id"] for d in decks], "pattern": patterns, "density": densities}
  allowed.update({"biome:" + d["id"]: d["biomes"] for d in decks})
  allowed.update({"orientation:" + p: o for p, o in orientations.items()})
  weights = {}
  for r in read_rows(MAPTILES, "weights", "param", wb):
    if r["param"] not in allowed:
      sys.exit("%s: unknown param %r (use: %s)" % (r["_where"], r["param"], ", ".join(allowed)))
    pool = [v.strip() for v in r.get("pool", "").split("|") if v.strip()]
    bad = [v for v in pool if v not in allowed[r["param"]]]
    if bad or not pool:
      sys.exit("%s: pool %r has %s (allowed: %s)" % (r["_where"], r.get("pool", ""),
               "unknown " + ", ".join(bad) if bad else "nothing in it", "|".join(allowed[r["param"]])))
    weights[r["param"]] = pool
  for param, values in allowed.items():
    if param not in weights:
      warn("weights sheet has no %r row -- rolling it evenly" % param)
      weights[param] = list(values)

  table = {}
  for r in read_rows(MAPTILES, "maptile_table", "gmnotes", wb):
    if r["gmnotes"] not in biomes:
      warn("%s: gmnotes %r is not a biome -- no tile will ever read it" % (r["_where"], r["gmnotes"]))
    table[r["gmnotes"]] = {k: v for k, v in r.items() if not k.startswith("_") and k != "gmnotes"}

  # ---- Lua
  L = [BEGIN, "-- GENERATED by tools/sync_maptile_manager.py from data/maptile.xlsx", "MAPTILE = {", "  decks = {"]
  for d in decks:
    L.append("    {id = %s, name = %s, back = %s, biomes = %s}," % (
      lua_str(d["id"]), lua_str(d["name"]), lua_str(d["back"]), lua_list(d["biomes"])))
  L.append("  },")
  L.append("  biomes = {")
  for b, v in biomes.items():
    L.append("    [%s] = {deck = %s, name = %s, description = %s}," % (
      lua_str(b), lua_str(v["deck"]), lua_str(v["name"]), lua_str(v["description"])))
  L.append("  },")
  L.append("  patterns = %s," % lua_list(patterns))
  L.append("  orientations = {%s}," % ", ".join("[%s] = %s" % (lua_str(p), lua_list(o))
                                                 for p, o in orientations.items()))
  L.append("  densities = %s," % lua_list(densities))
  L.append("  explore = {%s}," % ", ".join("[%s] = %d" % (lua_str(k), v) for k, v in explore.items()))
  L.append("  weights = {")
  for param, pool in weights.items():
    L.append("    [%s] = %s," % (lua_str(param), lua_list(pool)))
  L.append("  },")
  L.append("  table = {")
  for gm, row in table.items():
    L.append("    [%s] = {%s}," % (lua_str(gm), ", ".join("[%s] = %s" % (lua_str(k), lua_str(v))
                                                         for k, v in row.items())))
  L.append("  },")
  L.append("  images = {")
  for key, url in images.items():
    L.append("    [%s] = %s," % (lua_str(key), lua_str(url)))
  L.append("  },")
  L.append("}")
  L.append(END)

  src = io.open(SRC, encoding="utf-8").read()
  start, stop = src.find(BEGIN), src.find(END)
  if start < 0 or stop < 0:
    sys.exit("%s is missing the GENERATED MAPTILE DATA markers" % SRC)
  script = src[:start] + "\n".join(L) + src[stop + len(END):]

  out = staged_path(MANAGER_GUID)
  with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write(script)
  print("wrote %s (%d bytes): %d decks, %d biomes, %d/%d images have a url"
        % (os.path.relpath(out, os.path.dirname(ROOT)), len(script), len(decks), len(biomes),
           total - missing, total))
  if missing:
    warn("%d images have no url yet -- they cannot be drawn until data/maptile.xlsx has them" % missing)
  if converted:
    print("  note: %d Google Drive page links rewritten to direct-download links" % converted)


if __name__ == "__main__":
  main()
