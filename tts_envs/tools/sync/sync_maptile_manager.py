#!/usr/bin/env python3
"""Inline data/maptile.xlsx into the Maptile Manager's script and stage it.

  data/maptile.xlsx  ->  MAPTILE  ->  src/maptile_manager.lua  ->  .tts/objects/<nickname>.b77050.lua

Sheets read (tools/build/scaffold_maptile_xlsx.py creates and tops them up):

  <deck> x5          biome, pattern, orientation, density, image, file, url
  backs              deck, name, image, file, url
  biome_explore      one row per biome:
                       region (a deck on backs), name, effect, flavor -> description: [effect], blank line, "flavor"
                       resources, landmarks: what Explore's Resources / Landmarks choice can find, as a pool
                         of exact landmark names ("Mining Node|Mining Node|none"); "none" or a blank entry
                         = nothing found. Repeats raise the odds
                       special_label, special_tooltip: its fifth Explore choice (guildhall: Eat)
                       extra_info: the memo of every landmark Explore spawns on this biome (exactly this)
                       the tile description opens with the resources chances, computed here:
                         [Mining 33%, Hunting 33%, None 33%], then [effect] if any, then "flavor"
  biome_render       gmnotes + spawn cells (spawnN, spawnmeepleN, spawnlandmarkN, spawngold); optional
                     <spawncol>_gmnotes / <spawncol>_memo stamp that slot's copy ("{biome}" = the row's biome)
                     extra_info: added to the memo of every landmark + meeple Render spawns (not items,
                     cards or coins: their memo is cooldown / branch state)
  maptile_weights    param, pool        ("a|b|b": b is twice as likely)

A tile gets as many explorations as its density (no table: always equal).

A biome with a maptile_weights tier:<biome> row rolls that pool after it is drawn
("settlement|settlement|town|city") and BECOMES the result: its GMNotes,
description, render row and images. A biome reached only through a tier pool
is never drawn on its own.

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
EXPLORE_POOLS = ("resources", "landmarks")  # biome_explore columns, one per Explore choice that spawns
NOTHING = "none"  # a pool entry that finds nothing (a blank entry does too)
BIOME_COLUMNS = {"biome", "region", "name", "effect", "flavor", "extra_info", "special_label",
                 "special_tooltip"} | set(EXPLORE_POOLS)
# Render's extra_info reaches these slots only: an item's memo is its cooldown, a card's its branch state
EXTRA_INFO_KEYS = ("landmark", "meeple")
MEMO_JOIN = "|"


def join_memo(*parts):
  """Memo pieces in order, blanks dropped: slot / outcome memo first, then extra_info."""
  return MEMO_JOIN.join(p for p in parts if p)
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


def resource_chances(pool):
  """'Mining 33%, Hunting 33%, None 33%' from a resources pool: each entry's share,
  names without ' Node', in first-appearance order with None last. '' = no pool."""
  entries = [v.strip() for v in (pool or "").split("|")] if (pool or "").strip() else []
  if not entries:
    return ""
  names = ["None" if e == "" or e.lower() == NOTHING else e[:-len(" Node")] if e.endswith(" Node") else e
           for e in entries]
  order = [n for n in dict.fromkeys(names) if n != "None"] + (["None"] if "None" in names else [])
  return ", ".join("%s %d%%" % (n, round(100.0 * names.count(n) / len(names))) for n in order)


def describe(chances, effect, flavor):
  """The tile description: '[chances]' and '[effect]' (each if any), a blank line, then the quoted flavor.
  chances is derived from the resources pool by the sync, never authored."""
  parts = []
  head = "\n".join("[%s]" % t for t in (chances, effect) if t)
  if head:
    parts.append(head)
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

  biome_rows = read_rows(MAPTILES, "biome_explore", "biome", wb)
  biomes = {}
  for r in biome_rows:
    if r.get("region") not in deck_ids:
      sys.exit("%s: region %r is not a deck on the backs sheet" % (r["_where"], r.get("region")))
    biomes[r["biome"]] = {"deck": r["region"], "name": r.get("name") or r["biome"].title(),
                          "description": describe(resource_chances(r.get("resources")), r.get("effect", ""),
                                                 r.get("flavor", ""))}
    if r["biome"] != GUILDHALL:  # the cycling list Draw specific offers
      deck_ids[r["region"]]["biomes"].append(r["biome"])
  if GUILDHALL not in biomes:
    sys.exit("biome_explore has no %r row -- the Spawn guildhall button needs it" % GUILDHALL)
  blank = sorted(b for b, v in biomes.items() if not v["description"])
  if blank:
    warn("%d biomes have no effect or flavor: %s" % (len(blank), ", ".join(blank)))

  # tiers: maptile_weights tier:<biome> -> the biomes a drawn <biome> can become
  weight_rows = read_rows(MAPTILES, "maptile_weights", "param", wb)
  tiers, tier_only = {}, set()
  for r in weight_rows:
    if not r["param"].startswith("tier:"):
      continue
    where, b = r["_where"], r["param"][len("tier:"):]
    if b not in biomes:
      sys.exit("%s: %r is not on biome_explore" % (where, b))
    into = [v.strip() for v in r.get("pool", "").split("|") if v.strip()]
    if not into:
      sys.exit("%s: pool is empty" % where)
    for v in into:
      if biomes.get(v, {}).get("deck") != biomes[b]["deck"]:
        sys.exit("%s: %r needs a %s row on biome_explore (its description, render row and images)"
                 % (where, v, biomes[b]["deck"]))
    tiers[b] = list(dict.fromkeys(into))
    tier_only |= set(into) - {b}
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
      if biomes.get(biome, {}).get("deck") != d["id"]:
        sys.exit("%s: biome %r is not a %s biome on biome_explore" % (where, biome, d["id"]))
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
  for b, into in tiers.items():
    for v in into:
      if v not in drawn:
        warn("tier:%s can become %r, which has no images yet -- that result cannot be drawn" % (b, v))

  # weights: every pool checked against what it may contain; a missing pool = everything, evenly
  allowed = {"deck": [d["id"] for d in decks], "pattern": patterns, "density": densities}
  allowed.update({"biome:" + d["id"]: d["biomes"] for d in decks})
  allowed.update({"orientation:" + p: o for p, o in orientations.items()})
  allowed["guildhall:pattern"] = guildhall_patterns
  allowed["guildhall:density"] = sorted(guildhall_densities, key=int)
  # optional: a pattern without its own guildhall rotation pool uses orientation:<pattern>
  optional = {"guildhall:orientation:" + p for p in guildhall_patterns}
  allowed.update({"guildhall:orientation:" + p: orientations[p] for p in guildhall_patterns})
  allowed.update({"tier:" + b: into for b, into in tiers.items()})
  weights = {}
  for r in weight_rows:
    if r["param"] not in allowed:
      sys.exit("%s: unknown param %r (use: %s)" % (r["_where"], r["param"], ", ".join(allowed)))
    pool = [v.strip() for v in r.get("pool", "").split("|") if v.strip()]
    if r["param"].startswith("biome:") and GUILDHALL in pool:
      sys.exit("%s: %s is the starter tile, spawned by its own button -- take it out of %s"
               % (r["_where"], GUILDHALL, r["param"]))
    tiered = set(pool) & tier_only
    if r["param"].startswith("biome:") and tiered:
      sys.exit("%s: %s is only reached through a tier pool -- take it out of %s"
               % (r["_where"], ", ".join(sorted(tiered)), r["param"]))
    bad = [v for v in pool if v not in allowed[r["param"]]]
    if bad or not pool:
      sys.exit("%s: pool %r has %s (allowed: %s)" % (r["_where"], r.get("pool", ""),
               "unknown " + ", ".join(bad) if bad else "nothing in it", "|".join(allowed[r["param"]])))
    weights[r["param"]] = pool
  for param, values in allowed.items():
    if param not in weights and param not in optional:
      warn("maptile_weights has no %r row -- rolling it evenly" % param)
      weights[param] = list(values)

  # biome_render: what Render spawns, in the shared spawn-cell grammar
  # landmarks now come from their own bag, so a meeple cell may only name a meeple
  items, landmarks = item_names(), landmark_names()
  meeples = token_names() - landmarks
  table = {}
  for r in read_rows(MAPTILES, "biome_render", "gmnotes", wb):
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
    fill = lambda text, b=r["gmnotes"]: text.replace("{biome}", b)
    stamps = read_stamps(r, fill=fill)
    extra = fill(r.get("extra_info", ""))
    if extra:
      for key in EXTRA_INFO_KEYS:
        for i in range(1, len(spawn.get(key, [])) + 1):
          slot = stamps.setdefault(key, {}).setdefault(i, {})
          slot["memo"] = join_memo(slot.get("memo", ""), extra)
      if not any(spawn.get(k) for k in EXTRA_INFO_KEYS):
        warn("%s: extra_info but no landmark or meeple to carry it" % r["_where"])
    if stamps:
      spawn["stamps"] = stamps
    if spawn:
      table[r["gmnotes"]] = spawn

  # biome_explore: Explore's pools (exact landmark names, "none" / blank = nothing) and extra_info
  exploration, special, extra_info = {}, {}, {}
  for r in biome_rows:
    unknown = [c for c in r if not c.startswith("_") and c not in BIOME_COLUMNS]
    if unknown:
      sys.exit("%s: unknown biome_explore column %s (use: %s)"
               % (r["_where"], ", ".join(unknown), ", ".join(sorted(BIOME_COLUMNS))))
    if r.get("extra_info"):
      extra_info[r["biome"]] = r["extra_info"].replace("{biome}", r["biome"])
    pools = {}
    for col in EXPLORE_POOLS:
      if not r.get(col):
        continue
      pool = []
      for entry in (v.strip() for v in r[col].split("|")):
        if entry.lower() == NOTHING:
          entry = ""
        if entry and entry not in landmarks:
          sys.exit("%s: %s %r is not a landmark in tokens.xlsx (landmarks sheet)" % (r["_where"], col, entry))
        pool.append(entry)
      pools[col] = pool
    if pools:
      exploration[r["biome"]] = pools
    # a biome's own fifth Explore choice
    if r.get("special_tooltip") and not r.get("special_label"):
      sys.exit("%s: special_tooltip without a special_label (the button text)" % r["_where"])
    if r.get("special_label"):
      special[r["biome"]] = {"label": r["special_label"], "tooltip": r.get("special_tooltip", "")}

  unexplorable = sorted(set(biomes) - set(exploration))
  if unexplorable:
    warn("%d biomes have no resources / landmarks pool (Explore finds nothing): %s"
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
  L.append("  patterns = %s," % lua_list(patterns))
  L.append("  orientations = {%s}," % ", ".join("[%s] = %s" % (lua_str(p), lua_list(o))
                                                 for p, o in orientations.items()))
  L.append("  densities = %s," % lua_list(densities))
  L.append("  weights = {")
  for param, pool in weights.items():
    L.append("    [%s] = %s," % (lua_str(param), lua_list(pool)))
  L.append("  },")
  L.append("  table = {")
  for gm, row in table.items():
    L.append("    [%s] = %s," % (lua_str(gm), lua_spawn(row)))
  L.append("  },")
  L.append("  extra_info = {%s}," % ", ".join("[%s] = %s" % (lua_str(b), lua_str(v)) for b, v in extra_info.items()))
  L.append("  exploration = {")
  for b, pools in exploration.items():
    L.append("    [%s] = {%s}," % (lua_str(b), ", ".join("%s = %s" % (col, lua_list(pool)) for col, pool in pools.items())))
  L.append("  },")
  L.append("  special = {")
  for b, v in special.items():
    L.append("    [%s] = {label = %s, tooltip = %s}," % (lua_str(b), lua_str(v["label"]), lua_str(v["tooltip"])))
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
