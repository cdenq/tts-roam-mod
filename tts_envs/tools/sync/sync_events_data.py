#!/usr/bin/env python3
"""Convert cards.xlsx into the TTS Global script.

Three sheets, one event tree each:
  event_intro     the card: event_id (EV1), template, region, title,
                     flavor, face_url, back_url
  event_options   its buttons; `outcomes` lists outcome_keys, and a key
                     repeated in the list is rolled that much more often
  event_outcomes  where a button can land, keyed by event_id + outcome_key

plus `generic`: art-only cards (id, template, set, title, description,
face_url, back_url), read as more intros via intro_rows(); no options needed.

The game still sees one flat EVENT_DATA keyed by node id: an intro is its
event_id, an outcome is "<event_id>_<outcome_key>" (EV1_pay_through).

Writes two things:
  generated/global_data.lua  the data table on its own (reference / diffing)
  .tts/objects/Global.lua  src/global.lua with that data inlined

The data is inlined rather than require()d so the script runs no matter which
Save and Play variant the editor uses. Never hand-edit the two outputs.
Run: python tools/sync/sync_events_data.py
"""
import os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from spawn_cells import (SPAWN_CATEGORIES, read_spawn, referenced_names,
                         spawn_gives_anything)
from datasets import (ROOT, CARDS, GENERIC_SHEET, EVENT_OPTIONS, intro_rows,
                      EVENT_OUTCOMES, load, read_rows, item_names,
                      token_names, outcome_id, template_cell)

OUT = os.path.join(ROOT, "generated", "global_data.lua")
SRC = os.path.join(ROOT, "src", "global.lua")
WORKSPACE = os.path.dirname(ROOT)  # .tts/ must sit at the VS Code workspace root
SCRIPT = os.path.join(WORKSPACE, ".tts", "objects", "Global.lua")
BEGIN = "--[[ BEGIN GENERATED DATA -- do not edit ]]"
END = "--[[ END GENERATED DATA ]]"

#[[ Spawn cells, gold ranges and the Excel-date guard all live in
# spawn_cells.py, shared with the lootbox and origin syncs, so the grammar
# cannot drift between the systems that read it.
warnings_out = []


def warn(msg):
  warnings_out.append(msg)


def lua_str(s):
  r"""Quote a string for Lua, turning real newlines into the \n ESCAPE.

  A raw newline inside a double-quoted Lua string is a syntax error, so it has
  to become the two-character escape. Event descriptions are single-line today,
  which is why this never bit; see lua_str in sync_items_data.py for the same
  rule where multi-line text is expected.
  """
  s = s.replace("\\", "\\\\").replace('"', '\\"')
  s = s.replace("\r", "").replace("\n", "\\n")
  return '"' + s + '"'

def check_title(nid, title):
  # Titles travel to the Card Importer as tab-separated text (Global's
  # cardIndexText), so a tab or newline in a title would corrupt that wire
  # format. Catch it here rather than producing mis-named cards.
  if any(c in title for c in ("\t", "\n", "\r")):
    sys.exit("node %s title contains a tab or newline, which breaks the "
             "card index wire format: %r" % (nid, title))


def check_url(row, col):
  # URLs travel in the same tab-separated card index as titles.
  url = row.get(col, "")
  if re.search(r"\s", url):
    sys.exit("%s: %s %r contains whitespace" % (row["_where"], col, url))
  return url


def main():
  known = item_names()
  meeples = token_names()
  wb = load(CARDS)
  nodes = {}

  # ---- intros: one card each -----------------------------------------------
  intros = []
  for r in intro_rows(wb):
    sid = r["event_id"]
    if sid in nodes:
      sys.exit("%s: duplicate event_id %s" % (r["_where"], sid))
    #[[ region groups cards into importer buttons (CARD_SETS), so a card
    # without one would never be importable.
    if not r.get("region"):
      sys.exit("%s: %s has no region" % (r["_where"], sid))
    check_title(sid, r.get("title", ""))
    nodes[sid] = {"title": r.get("title", ""), "flavor": r.get("flavor", ""),
                  "effect": "", "region": r["region"], "options": [],
                  "template": template_cell(r, r["_where"]),
                  "face": check_url(r, "face_url"),
                  "back": check_url(r, "back_url"),
                  "generic": r["_sheet"] == GENERIC_SHEET}
    intros.append(sid)

  # ---- outcomes: where an option lands ------------------------------------
  outcomes_of = {sid: [] for sid in intros}
  for r in read_rows(CARDS, EVENT_OUTCOMES, "outcome_key", wb):
    sid = r.get("event_id", "")
    if sid not in outcomes_of:
      sys.exit("%s: unknown event_id %r" % (r["_where"], sid))
    nid = outcome_id(sid, r["outcome_key"])
    where = "%s (%s)" % (r["_where"], nid)
    if nid in nodes:
      sys.exit("%s: duplicate outcome_key %r on %s"
               % (r["_where"], r["outcome_key"], sid))
    check_title(nid, r.get("title", ""))
    node = {"title": r.get("title", ""), "flavor": r.get("flavor", ""),
            "effect": r.get("effect", ""), "options": []}

    # Spawn rewards: one slot per filled column, each a weighted name list.
    spawn = read_spawn(r)
    if spawn:
      node["spawn"] = spawn

    #[[ A spawn table that can never hand anything out gives the card a spawn
    # button that does nothing -- hasSpawn() in global.lua uses this same test.
    # A gold-only reward is legitimate, so "no items" alone is NOT a fault.
    if spawn and not spawn_gives_anything(spawn):
      warn("%s: has spawn cells but hands out nothing -- its spawn button "
           "would do nothing" % where)

    #[[ The reverse check -- an item that no event spawns -- is NOT a fault:
    # most items are shop or drop-table only and never appear on an event.
    # items only: statuses come from their own bag and are not in tiles.xlsx.
    # A weighted cell repeats names on purpose, so report each one once.
    missing = []
    for ref in referenced_names(r, keys=("items",)):
      if ref not in known and ref not in missing:
        missing.append(ref)
    for ref in missing:
      warn("%s: spawns %r, which is not in tiles.xlsx -- the spawn will "
           "fail in game" % (where, ref))
    missing = []
    for ref in referenced_names(r, keys=("meeple",)):
      if ref not in meeples and ref not in missing:
        missing.append(ref)
    for ref in missing:
      warn("%s: spawns meeple %r, which is not in tokens.xlsx -- the spawn "
           "will fail in game" % (where, ref))

    nodes[nid] = node
    outcomes_of[sid].append(nid)

  # ---- options: the buttons on an intro -----------------------------------
  opts = []
  used = set()
  for r in read_rows(CARDS, EVENT_OPTIONS, "event_id", wb):
    sid = r["event_id"]
    where = "%s (%s)" % (r["_where"], sid)
    if sid not in outcomes_of:
      sys.exit("%s: unknown event_id" % where)
    try:
      ordv = int(r.get("option") or "0")
    except ValueError:
      sys.exit("%s: option %r is not a number" % (where, r.get("option")))
    keys = [k.strip() for k in (r.get("outcomes") or "").split("|") if k.strip()]
    if not keys:
      sys.exit("%s: option %d has no outcomes" % (where, ordv))
    outs = []
    for k in keys:
      nid = outcome_id(sid, k)
      if nid not in outcomes_of[sid]:
        sys.exit("%s: option %d names outcome_key %r, but %s has no row for "
                 "%s with that key" % (where, ordv, k, EVENT_OUTCOMES, sid))
      outs.append(nid)
      used.add(nid)
    opts.append((sid, ordv, r.get("label", ""), r.get("tooltip", ""), outs))

  for sid, ordv, label, tip, outs in sorted(opts, key=lambda x: (x[0], x[1])):
    nodes[sid]["options"].append({"label": label, "tooltip": tip,
                                  "outcomes": outs})
  for sid in intros:
    if not nodes[sid]["options"] and not nodes[sid]["generic"]:
      sys.exit("event %s has no rows on %s -- its card would have no "
               "buttons" % (sid, EVENT_OPTIONS))
    for nid in outcomes_of[sid]:
      if nid not in used:
        warn("%s is on %s but no option of %s rolls it -- unreachable"
             % (nid, EVENT_OUTCOMES, sid))

  # Each intro followed by its outcomes, so the generated file reads as trees.
  order = []
  for sid in intros:
    order.append(sid)
    order.extend(outcomes_of[sid])

  L = ["-- GENERATED by tools/sync/sync_events_data.py -- do not edit by hand",
       "EVENT_DATA = {"]
  for nid in order:
    n = nodes[nid]
    L.append("  [%s] = {" % lua_str(nid))
    L.append("    title = %s," % lua_str(n["title"]))
    # Intros only: the card importer clones the template this names.
    if "template" in n:
      L.append("    template = %s," % lua_str(n["template"]))
      if n["face"]:
        L.append("    face = %s," % lua_str(n["face"]))
      if n["back"]:
        L.append("    back = %s," % lua_str(n["back"]))
      # Art-only: Global draws nothing on it.
      if n["generic"]:
        L.append("    generic = true,")
    L.append("    flavor = %s," % lua_str(n["flavor"]))
    L.append("    effect = %s," % lua_str(n["effect"]))
    if n["options"]:
      L.append("    options = {")
      for o in n["options"]:
        outs = ", ".join(lua_str(x) for x in o["outcomes"])
        L.append("      {label = %s, tooltip = %s, outcomes = {%s}},"
                 % (lua_str(o["label"]), lua_str(o["tooltip"]), outs))
      L.append("    },")
    else:
      L.append("    options = {},")

    sp = n.get("spawn")
    if sp:
      L.append("    spawn = {")
      for cat in SPAWN_CATEGORIES:
        slots = sp.get(cat["key"])
        if not slots:
          continue
        inner = ", ".join("{%s}" % ", ".join(lua_str(x) for x in slot)
                          for slot in slots)
        L.append("      %s = {%s}," % (cat["key"], inner))
      if "gold" in sp:
        lo, hi = sp["gold"]
        L.append("      gold = {%d, %d}," % (lo, hi))
      L.append("    },")

    L.append("  },")
  L.append("}")

  #[[ Which nodes are CARDS, grouped by region.
  #
  # Every intro gets a physical card; the outcome nodes it branches to do not.
  # The importer bag makes one button per region from CARD_SETS; Global still
  # renders from EVENT_DATA, so a card only ever carries its id.
  card_sets = []
  for sid in intros:
    region = nodes[sid]["region"]
    if region not in [name for name, _ in card_sets]:
      card_sets.append((region, []))
  for name, ids in card_sets:
    ids.extend(sid for sid in intros if nodes[sid]["region"] == name)

  L.append("")
  L.append("-- Intro nodes that get a physical card, grouped by region (sheet order).")
  L.append("CARD_SETS = {")
  for name, ids in card_sets:
    L.append("  [%s] = {%s}," % (lua_str(name),
                                 ", ".join(lua_str(i) for i in ids)))
  L.append("}")
  L.append("")
  L.append("-- Region names in sheet order -- drives the importer's button grid.")
  L.append("CARD_SET_ORDER = {%s}"
           % ", ".join(lua_str(n) for n, _ in card_sets))
  data_lua = "\n".join(L)

  os.makedirs(os.path.dirname(OUT), exist_ok=True)
  with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(data_lua + "\n")

  with open(SRC, encoding="utf-8") as f:
    script = f.read()
  block = BEGIN + "\n" + data_lua + "\n" + END
  if BEGIN in script and END in script:
    script = script.split(BEGIN)[0] + block + script.split(END, 1)[1]
  else:
    script = block + "\n\n" + script
  os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
  with open(SCRIPT, "w", encoding="utf-8", newline="\n") as f:
    f.write(script)

  for w in warnings_out:
    print("  warning: " + w)
  cards = len(intros)
  print("wrote %s (%d nodes, %d options, %d cards)"
        % (OUT, len(order), len(opts), cards))
  print("wrote %s (%d bytes, data inlined)" % (SCRIPT, len(script)))

main()
