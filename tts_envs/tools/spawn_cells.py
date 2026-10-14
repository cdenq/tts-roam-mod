import os
#!/usr/bin/env python3
"""Parsing for spawn cells, shared by every system that hands out items.

Event nodes and lootboxes use the identical cell format, so the grammar lives
here rather than being reimplemented per consumer. Anything else that drops
loot -- shop menus, quest rewards -- should import this too.

The grammar, in one place:

    Ration|Rope|Ration     uniform pick; repeats raise the odds
    Ration|Rope| |         a blank entry means "nothing drops"
    !Key|!Key|Box          "!" marks a UNIQUE drop: the spawner TAKES the item
                           from the canonical bag instead of cloning it, so
                           only one can exist at a time
    (empty cell)           not a slot at all -- no reward here, as distinct
                           from a reward that sometimes misses

The "!" is PER REFERENCE, not per item: the same item can be unique from one
source and ordinary from another. It is left on the name by weighted_list and
stripped in global.lua by parseSpawnEntry.
"""
import sys

UNIQUE_PREFIX = "!"

# Spawn categories. One entry drives the column names, the parsing and the
# generated Lua, so adding a category means adding a row -- not new code.
SPAWN_CATEGORIES = [
  {"key": "items", "prefix": "spawn", "count": 5},
  {"key": "status", "prefix": "spawnstatus", "count": 3},
  # A sheet only needs the columns it uses: origins carry spawnmeeple1 alone.
  {"key": "meeple", "prefix": "spawnmeeple", "count": 12},
  # One unnumbered column: spawncard. Cards come out of their own bag by exact name.
  {"key": "card", "prefix": "spawncard", "count": 1, "single": True},
]
GOLD_COLUMN = "spawngold"

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec")


def category_columns(cat):
  """A category's column names: spawn1..spawn5, or just the prefix when single."""
  if cat.get("single"):
    return [cat["prefix"]]
  return ["%s%d" % (cat["prefix"], i) for i in range(1, cat["count"] + 1)]


def spawn_columns():
  """Every column name a spawn table uses, in order."""
  cols = [GOLD_COLUMN]
  for cat in SPAWN_CATEGORIES:
    cols += category_columns(cat)
  return cols


def weighted_list(cell):
  """One slot's entries, blanks and ! prefixes preserved. See module docstring."""
  text = (cell or "").strip()
  if not text:
    return []
  if "|" not in text:
    return [text]
  # Entries are kept positionally, blanks included.
  return [x.strip() for x in text.split("|")]


def strip_unique(name):
  """The real item name behind a possible "!" marker."""
  name = (name or "").strip()
  return name[1:].strip() if name.startswith(UNIQUE_PREFIX) else name


def parse_gold(cell, where="spawngold"):
  """"5" -> (5, 5);  "1-5" -> (1, 5);  "" -> None."""
  cell = (cell or "").strip()
  if not cell:
    return None
  #[[ Opening a CSV in Excel silently turns a range like "1-5" into the DATE
  # "5-Jan". Name the cause, because "bad range: 5-Jan" is otherwise baffling.
  if any(m in cell.lower() for m in MONTHS):
    sys.exit("%s %r looks like an Excel date: opening the file in Excel turns "
             "a range such as 1-5 into 5-Jan. Restore it by hand and edit that "
             "file in a text editor." % (where, cell))
  if "-" in cell:
    lo, _, hi = cell.partition("-")
    try:
      return (int(lo.strip()), int(hi.strip()))
    except ValueError:
      sys.exit("bad %s range: %s" % (where, cell))
  try:
    n = int(cell)
  except ValueError:
    sys.exit("bad %s value: %s" % (where, cell))
  return (n, n)


def read_spawn(row):
  """Pull a whole spawn table out of a row dict, or {} when it has none.

  Returns the shape global.lua's rollSpawn() expects:

      {"items":  [["Ration", "Rope", ""], ["Rope"]],
       "status": [["Blessed"]],
       "gold":   (1, 5)}
  """
  spawn = {}
  for cat in SPAWN_CATEGORIES:
    slots = []
    for col in category_columns(cat):
      names = weighted_list(row.get(col))
      if names:
        slots.append(names)
    if slots:
      spawn[cat["key"]] = slots
  gold = parse_gold(row.get(GOLD_COLUMN))
  if gold:
    spawn["gold"] = gold
  return spawn


def spawn_gives_anything(spawn):
  """True when a spawn table can actually hand something out.

  The Python mirror of spawnHasAnything() in global.lua, which decides whether
  a card gets a spawn button. A slot of nothing but blanks (" | | ") parses to
  a real slot yet can never drop anything, so a table built only from those is
  a button that does nothing. Gold alone DOES count as a reward.
  """
  if not spawn:
    return False
  # spawngold=0 parses to (0, 0); spawnPlanStep only pays out when gold > 0.
  gold = spawn.get("gold")
  if gold and gold[1] > 0:
    return True
  for cat in SPAWN_CATEGORIES:
    for slot in spawn.get(cat["key"], []):
      if any(strip_unique(n) for n in slot):
        return True
  return False


def referenced_names(row, keys=None):
  """Every real name a row's spawn cells mention, ! markers stripped.

  `keys` limits the result to those categories, e.g. keys=("items",) to check
  names against tiles.xlsx -- statuses come from their own bag and have no
  entry there, so validating them against the item sheet is a false positive.
  Default is every category, preserving the original behaviour.
  """
  out = []
  for cat in SPAWN_CATEGORIES:
    if keys is not None and cat["key"] not in keys:
      continue
    for col in category_columns(cat):
      for raw in weighted_list(row.get(col)):
        name = strip_unique(raw)
        if name:
          out.append(name)
  return out


def _workspace():
  """The VS Code workspace root -- .tts/ sits directly inside it."""
  here = os.path.dirname(os.path.abspath(__file__))
  return os.path.dirname(os.path.dirname(here))


def staged_path(guid, objects_dir=None):
  """Where to stage a script, resolved by GUID rather than by filename.

  Ctrl+Alt+L names each file after the object's in-game NICKNAME, so a
  rename moves the file. Hardcoding a name means the sync writes to a path
  the extension has never heard of, which it then deletes on the next pull --
  silently, because nothing errors. The GUID never changes, so find the file
  by its GUID and use whatever name the extension chose.

  Returns the absolute path to <Nickname>.<guid>.lua.
  """
  objects = objects_dir or os.path.join(_workspace(), ".tts", "objects")
  if not os.path.isdir(objects):
    raise SystemExit("missing %s -- open the workspace in VS Code with the "
                     "TTS extension and press Ctrl+Alt+L once" % objects)

  # The .data.json is the extension's own record that it tracks this object.
  matches = sorted(f for f in os.listdir(objects)
                   if f.endswith(".%s.data.json" % guid))
  if len(matches) == 1:
    return os.path.join(objects, matches[0].replace(".data.json", ".lua"))
  if len(matches) > 1:
    raise SystemExit("%s matches more than one tracked object: %s"
                     % (guid, ", ".join(matches)))
  raise SystemExit(
    "%s is not tracked. Give the object a one-line script in TTS, press "
    "Ctrl+Alt+L, then re-run the sync." % guid)
