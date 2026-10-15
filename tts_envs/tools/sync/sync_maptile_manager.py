#!/usr/bin/env python3
"""Inline data/maptile.xlsx into the Maptile Manager's script and stage it.

  data/maptile.xlsx  ->  MAPTILE  ->  src/maptile_manager.lua  ->  .tts/objects/<nickname>.b77050.lua

Sheets read (tools/build/scaffold_maptile_xlsx.py creates and tops them up):

  <deck> x5            biome, pattern, orientation, density, image, file, url
  backs                deck, name, image, file, url
  biome_descriptions   biome, deck, name, effect, flavor  -> [effect], blank line, "flavor"
  maptile_table        gmnotes + spawn cells (spawnN, spawnmeepleN, spawnlandmarkN, spawngold); optional
                       <spawncol>_gmnotes / <spawncol>_memo stamp that slot's copy ("{biome}" = the row's biome)
  explore_outcomes     outcome, category (resource / poi / event), kind (landmark / nothing), name,
                       landmarks ("a|b|b"), gmnotes + memo (stamped on the spawned landmark; "{biome}" =
                       the tile's biome), flavor ("line|line": one is announced)
  exploration          biome + one weight column per resource / poi outcome  (blank / 0 = never)
  density              density, explorations
  weights              param, pool        ("a|b|b": b is twice as likely)
  tiers                biome, tier, gmnotes, tileset

A biome on the tiers sheet rolls a tier (weights tier:<biome>) after it is
drawn. The tier is never shown: it only picks GMNOTES -- the biome the tile
becomes (settlement / town / city), with its own description and render row --
and the TILESET whose images it uses. A gmnotes biome reached only through a
tier is never drawn on its own; a tileset that is not a biome (none today) has
image rows and nothing else.

The guildhall is the starter tile: it is never drawn, only spawned by its own
button, so it is left out of every biome pool and rolls from guildhall:* pools.

Only images WITH a url reach the game; the rest are counted and reported, so
the manager works while the upload is still in progress. A Google Drive
share-page link is rewritten to its direct-download form on the way through.

Run: python tools/sync/sync_maptile_manager.py
"""
import io, os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from datasets import ROOT, MAPTILES, load, read_rows, item_names, token_names, landmark_names
from spawn_cells import staged_path, read_spawn, read_stamps, referenced_names, SPAWN_CATEGORIES

MANAGER_GUID = "b77050"
SRC = os.path.join(ROOT, "src", "maptile_manager.lua")
BEGIN = "--[[ BEGIN GENERATED MAPTILE DATA -- do not edit ]]"
END = "--[[ END GENERATED MAPTILE DATA ]]"
GUILDHALL = "guildhall"
EXPLORE_KINDS = ("landmark", "nothing")
EXPLORE_CATEGORIES = ("resource", "poi", "event")  # event = the Experiences choice: flavor only, no weights
DRIVE_PAGE = re.compile(r"https?://drive\.google\.com/(?:file/d/([\w-]+)|open\?id=([\w-]+))")


def warn(msg):
  print("  warning: " + msg)


def lua_str(s):
  s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
  return '"' + s + '"'


def lua_list(items):
  return "{" + ", ".join(lua_str(i) for i in items) + "}"


def lua_spawn(spawn):
  """A read_spawn() table in the shape global.lua's rollSpawn() expects."""
  parts = ["%s = {%s}" % (c["key"], ", ".join(lua_list(slot) for slot in spawn[c["key"]]))
           for c in SPAWN_CATEGORIES if c["key"] in spawn]
  if "gold" in spawn:
    parts.append("gold = {%d, %d}" % spawn["gold"])
  if spawn.get("stamps"):
    parts.append("stamps = {%s}" % ", ".join(
      "%s = {%s}" % (key, ", ".join("[%d] = {%s}" % (i, ", ".join("%s = %s" % (f, lua_str(v)) for f, v in st.items()))
                                    for i, st in slots.items()))
      for key, slots in spawn["stamps"].items()))
  return "{" + ", ".join(parts) + "}"


def describe(effect, flavor):
  """The tile description: '[effect]', a blank line, then the quoted flavor."""
  parts = []
  if effect:
    parts.append("[%s]" % effect)
  if flavor:
    parts.append('"%s"' % flavor)
  return "\n\n".join(parts)


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
    sys.exit("missing %s -- run tools/build/scaffold_maptile_xlsx.py first" % MAPTILES)
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
                          "description": describe(r.get("effect", ""), r.get("flavor", ""))}
    if r["biome"] != GUILDHALL:  # the cycling list Draw specific offers
      deck_ids[r["deck"]]["biomes"].append(r["biome"])
  if GUILDHALL not in biomes:
    sys.exit("biome_descriptions has no %r row -- the Spawn guildhall button needs it" % GUILDHALL)
  blank = sorted(b for b, v in biomes.items() if not v["description"])
  if blank:
    warn("%d biomes have no effect or flavor: %s" % (len(blank), ", ".join(blank)))

  # tiers: biome -> tier -> {gmnotes, tileset}
  tiers, tilesets, tier_only = {}, {}, set()
  for r in read_rows(MAPTILES, "tiers", "biome", wb):
    where = r["_where"]
    if r["biome"] not in biomes:
      sys.exit("%s: biome %r is not on biome_descriptions" % (where, r["biome"]))
    if not (r.get("tier") and r.get("gmnotes") and r.get("tileset")):
      sys.exit("%s: needs a tier, gmnotes and tileset" % where)
    if r["tier"] in tiers.get(r["biome"], {}):
      sys.exit("%s: %s tier %s is listed twice" % (where, r["biome"], r["tier"]))
    deck = biomes[r["biome"]]["deck"]
    if biomes.get(r["gmnotes"], {}).get("deck") != deck:
      sys.exit("%s: gmnotes %r needs a %s row on biome_descriptions (its description and render row)"
               % (where, r["gmnotes"], deck))
    tiers.setdefault(r["biome"], {})[r["tier"]] = {"gmnotes": r["gmnotes"], "tileset": r["tileset"]}
    if r["gmnotes"] != r["biome"]:
      tier_only.add(r["gmnotes"])
    if r["tileset"] not in biomes:
      tilesets[r["tileset"]] = deck
  tier_only -= set(tiers)
  for d in decks:  # reached only through a tier: Draw specific cannot pick it either
    d["biomes"] = [b for b in d["biomes"] if b not in tier_only]

  images, patterns, orientations, densities = {}, [], {}, set()
  drawn = set()  # every tileset with at least one image
  guildhall_patterns, guildhall_densities = [], set()
  total = missing = 0
  for d in decks:
    if d["id"] not in wb.sheetnames:
      sys.exit("maptile.xlsx has no sheet for deck %r" % d["id"])
    for r in read_rows(MAPTILES, d["id"], "image", wb):
      where = r["_where"]
      biome, pattern, orient, dens = r.get("biome"), r.get("pattern"), r.get("orientation"), r.get("density")
      if biomes.get(biome, {}).get("deck", tilesets.get(biome)) != d["id"]:
        sys.exit("%s: biome %r is not a %s biome on biome_descriptions or a tileset on tiers"
                 % (where, biome, d["id"]))
      drawn.add(biome)
      if not (pattern and orient and dens):
        sys.exit("%s: needs pattern, orientation and density" % where)
      if pattern not in patterns:
        patterns.append(pattern)
      if orient not in orientations.setdefault(pattern, []):
        orientations[pattern].append(orient)
      densities.add(dens)
      if biome == GUILDHALL:
        if pattern not in guildhall_patterns:
          guildhall_patterns.append(pattern)
        guildhall_densities.add(dens)
      total += 1
      url, conv = direct_url(r.get("url", ""), where)
      converted += conv
      if not url:
        missing += 1
        continue
      images["|".join((biome, pattern, orient, dens))] = url
  densities = sorted(densities, key=int)
  for b, by_tier in tiers.items():
    for tier, v in by_tier.items():
      if v["tileset"] not in drawn:
        warn("%s tier %s uses tileset %r, which has no images yet -- that tier cannot be drawn"
             % (b, tier, v["tileset"]))

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
  allowed["guildhall:pattern"] = guildhall_patterns
  allowed["guildhall:density"] = sorted(guildhall_densities, key=int)
  # optional: a pattern without its own guildhall rotation pool uses orientation:<pattern>
  optional = {"guildhall:orientation:" + p for p in guildhall_patterns}
  allowed.update({"guildhall:orientation:" + p: orientations[p] for p in guildhall_patterns})
  allowed.update({"tier:" + b: sorted(t, key=int) for b, t in tiers.items()})
  weights = {}
  for r in read_rows(MAPTILES, "weights", "param", wb):
    if r["param"] not in allowed:
      sys.exit("%s: unknown param %r (use: %s)" % (r["_where"], r["param"], ", ".join(allowed)))
    pool = [v.strip() for v in r.get("pool", "").split("|") if v.strip()]
    if r["param"].startswith("biome:") and GUILDHALL in pool:
      sys.exit("%s: %s is the starter tile, spawned by its own button -- take it out of %s"
               % (r["_where"], GUILDHALL, r["param"]))
    tiered = set(pool) & (set(tilesets) | tier_only)
    if r["param"].startswith("biome:") and tiered:
      sys.exit("%s: %s is only reached through a tier (tiers sheet) -- take it out of %s"
               % (r["_where"], ", ".join(sorted(tiered)), r["param"]))
    bad = [v for v in pool if v not in allowed[r["param"]]]
    if bad or not pool:
      sys.exit("%s: pool %r has %s (allowed: %s)" % (r["_where"], r.get("pool", ""),
               "unknown " + ", ".join(bad) if bad else "nothing in it", "|".join(allowed[r["param"]])))
    weights[r["param"]] = pool
  for param, values in allowed.items():
    if param not in weights and param not in optional:
      warn("weights sheet has no %r row -- rolling it evenly" % param)
      weights[param] = list(values)

  # maptile_table: what Render spawns, in the shared spawn-cell grammar
  # landmarks now come from their own bag, so a meeple cell may only name a meeple
  items, landmarks = item_names(), landmark_names()
  meeples = token_names() - landmarks
  table = {}
  for r in read_rows(MAPTILES, "maptile_table", "gmnotes", wb):
    if r["gmnotes"] not in biomes:
      warn("%s: gmnotes %r is not a biome -- no tile will ever read it" % (r["_where"], r["gmnotes"]))
    for ref in referenced_names(r, keys=("items",)):
      if ref not in items:
        sys.exit("%s: %r is not an item in tiles.xlsx" % (r["_where"], ref))
    for ref in referenced_names(r, keys=("meeple",)):
      if ref in landmarks:
        sys.exit("%s: %r is a landmark -- put it in a spawnlandmarkN column" % (r["_where"], ref))
      if ref not in meeples:
        sys.exit("%s: %r is not a meeple in tokens.xlsx" % (r["_where"], ref))
    for ref in referenced_names(r, keys=("landmark",)):
      if ref not in landmarks:
        sys.exit("%s: %r is not a landmark in tokens.xlsx (landmarks sheet)" % (r["_where"], ref))
    spawn = read_spawn(r)
    stamps = read_stamps(r, fill=lambda text, b=r["gmnotes"]: text.replace("{biome}", b))
    if stamps:
      spawn["stamps"] = stamps
    if spawn:
      table[r["gmnotes"]] = spawn

  # explore_outcomes: what each outcome does; exploration: per-biome weight per resource / poi outcome
  outcomes = {}
  for r in read_rows(MAPTILES, "explore_outcomes", "outcome", wb):
    where, category = r["_where"], r.get("category", "")
    if category not in EXPLORE_CATEGORIES:
      sys.exit("%s: category %r (use: %s)" % (where, category, ", ".join(EXPLORE_CATEGORIES)))
    kind = r.get("kind") or "nothing"
    if kind not in EXPLORE_KINDS:
      sys.exit("%s: kind %r (use: %s)" % (where, kind, ", ".join(EXPLORE_KINDS)))
    pool = [v.strip() for v in r.get("landmarks", "").split("|") if v.strip()]
    for name in pool:
      if name not in landmarks:
        sys.exit("%s: %r is not a landmark in tokens.xlsx (landmarks sheet)" % (where, name))
    if kind == "landmark" and not pool:
      warn("%s: %s has no landmarks yet -- give it weight only once it does" % (where, r["outcome"]))
    outcomes[r["outcome"]] = {"category": category, "kind": kind, "name": r.get("name") or r["outcome"].title(),
                              "landmarks": pool, "gmnotes": r.get("gmnotes", ""), "memo": r.get("memo", ""),
                              "flavor": [v.strip() for v in r.get("flavor", "").split("|") if v.strip()]}
  if "event" not in outcomes:
    warn("explore_outcomes has no 'event' row -- Experiences is announced without flavor")
  exploration = {}
  for r in read_rows(MAPTILES, "exploration", "biome", wb):
    if r["biome"] not in biomes:
      sys.exit("%s: biome %r is not on biome_descriptions" % (r["_where"], r["biome"]))
    rows = {}
    for col, v in r.items():
      if col in ("biome", "notes") or col.startswith("_") or v == "":
        continue
      o = outcomes.get(col)
      if o is None or o["category"] == "event":
        sys.exit("%s: column %r is not a resource / poi outcome on explore_outcomes" % (r["_where"], col))
      try:
        weight = int(float(v))
      except ValueError:
        sys.exit("%s: %s weight %r must be a whole number" % (r["_where"], col, v))
      if weight < 0:
        sys.exit("%s: %s weight must not be negative" % (r["_where"], col))
      if weight and o["kind"] == "landmark" and not o["landmarks"]:
        sys.exit("%s: %s has weight but no landmarks on explore_outcomes" % (r["_where"], col))
      if weight:
        rows.setdefault(o["category"], []).append((col, weight))
    if rows:
      exploration[r["biome"]] = rows
  unexplorable = sorted(set(biomes) - set(exploration))
  if unexplorable:
    warn("%d biomes have no exploration weights (Explore finds nothing): %s"
         % (len(unexplorable), ", ".join(unexplorable)))

  # ---- Lua
  L = [BEGIN, "-- GENERATED by tools/sync/sync_maptile_manager.py from data/maptile.xlsx", "MAPTILE = {",
       "  guildhall = %s," % lua_str(GUILDHALL), "  decks = {"]
  for d in decks:
    L.append("    {id = %s, name = %s, back = %s, biomes = %s}," % (
      lua_str(d["id"]), lua_str(d["name"]), lua_str(d["back"]), lua_list(d["biomes"])))
  L.append("  },")
  L.append("  biomes = {")
  for b, v in biomes.items():
    L.append("    [%s] = {deck = %s, name = %s, description = %s}," % (
      lua_str(b), lua_str(v["deck"]), lua_str(v["name"]), lua_str(v["description"])))
  L.append("  },")
  L.append("  tiers = {")
  for b, by_tier in tiers.items():
    L.append("    [%s] = {%s}," % (lua_str(b), ", ".join(
      "[%s] = {gmnotes = %s, tileset = %s}" % (lua_str(t), lua_str(v["gmnotes"]), lua_str(v["tileset"]))
      for t, v in by_tier.items())))
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
    L.append("    [%s] = %s," % (lua_str(gm), lua_spawn(row)))
  L.append("  },")
  L.append("  outcomes = {")
  for o, v in outcomes.items():
    L.append("    [%s] = {category = %s, kind = %s, name = %s, landmarks = %s, gmnotes = %s, memo = %s, flavor = %s}," % (
      lua_str(o), lua_str(v["category"]), lua_str(v["kind"]), lua_str(v["name"]), lua_list(v["landmarks"]),
      lua_str(v["gmnotes"]), lua_str(v["memo"]), lua_list(v["flavor"])))
  L.append("  },")
  L.append("  exploration = {")
  for b, rows in exploration.items():
    L.append("    [%s] = {%s}," % (lua_str(b), ", ".join(
      "%s = {%s}" % (cat, ", ".join("{%s, %d}" % (lua_str(o), w) for o, w in row)) for cat, row in rows.items())))
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
  print("wrote %s (%d bytes): %d decks, %d biomes, %d/%d images have a url, %d biomes render something, "
        "%d explorable" % (os.path.relpath(out, os.path.dirname(ROOT)), len(script), len(decks), len(biomes),
                           total - missing, total, len(table), len(exploration)))
  if missing:
    warn("%d images have no url yet -- they cannot be drawn until data/maptile.xlsx has them" % missing)
  if converted:
    print("  note: %d Google Drive page links rewritten to direct-download links" % converted)


if __name__ == "__main__":
  main()
