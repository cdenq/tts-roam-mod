#!/usr/bin/env python3
"""Convert tiles.xlsx and tokens.xlsx into the item bag's object script.

Every sheet in datasets.ITEM_SHEETS (items, skills, statuses) shares one set
of headers and is read as one table, in that order. tokens.xlsx (meeples --
people, not things) has headers of its own and is appended after them. Both
land in ITEM_DATA because one bag imports both, keyed by one name space.

Writes two things:
  generated/tiletoken_data.lua          the data table on its own (reference / diffing)
  .tts/objects/TileToken Importer.85a721.lua
                                        src/tiletoken_importer.lua, data inlined

The import list lives on the BAG: it is the only consumer of the full table, and
object scripts do not share Global's scope. Interactive items (tools) ALSO need
their numbers in Global, because Global draws the USE button and must know the
cooldown duration -- it reads them from ITEM_INDEX, which global.lua builds from
this same data.

Validation is the real payoff. Every item name referenced by a spawn column in
scenarios.xlsx must exist here, so a typo dies at build time instead of showing
up mid-game as '"Rations" is not in bag ...'. The classification columns use
closed vocabularies for the same reason: a typo'd 'conusmable' would otherwise
silently create a new category.

Never hand-edit the two outputs.
Run: python tools/sync/sync_items_data.py
"""
import os, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from spawn_cells import staged_path, referenced_names, read_spawn
from datasets import (ROOT, TILES, ITEM_SHEETS, SCENARIOS, SCENARIO_OUTCOMES,
                      TOKENS, TOKEN_SHEET, LANDMARK_SHEET, LANDMARK_ROLE,
                      FACTIONS_SHEET, LOOT_TABLE_SHEET,
                      STATS_TABLE_SHEET, SHOP_ROLE, COMBAT_ROLE, SHOPS,
                      load, read_rows, outcome_id, template_cell,
                      template_collisions)
from lua_inline import inline_shared

OUT = os.path.join(ROOT, "generated", "tiletoken_data.lua")
SRC = os.path.join(ROOT, "src", "tiletoken_importer.lua")
WORKSPACE = os.path.dirname(ROOT)  # .tts/ must sit at the VS Code workspace root

# The item bag in-game. BAG_NAME must match the filename the extension writes,
# which comes from the object's Nickname with /:<>"|?* and newlines stripped:
# "Tile/Token Importer" -> "TileToken Importer".
BAG_GUID = "85a721"
# The staged filename is resolved from the GUID at run time, not hardcoded:
# Ctrl+Alt+L names each file after the object's in-game NICKNAME, so renaming
# the bag would otherwise orphan whatever this wrote.

BEGIN = "--[[ BEGIN GENERATED DATA -- do not edit ]]"
END = "--[[ END GENERATED DATA ]]"

# --------------------------------------------------------- vocabularies ---

#[[ The allowed values live on the `_values` SHEET of tiles.xlsx, not here.
#
# Excel enforces them with dropdowns, and this script reads the same sheet, so
# there is exactly one place to extend a vocabulary: add a row on `_values` and
# both the dropdown and this validator pick it up.
#
# The few rules that are STRUCTURAL rather than a list -- which types may carry
# a tier, which may carry a stat -- stay below, because they are logic, not
# vocabulary.
VALUES_SHEET = "_values"

# Types that are GEAR: they sit on the tier ladder and need a qualifying stat.
GEAR_TYPES = ("weapon", "armor")

# Any item may carry a cooldown or a use count -- a throwing-knife weapon with
# 5 uses, a quest item on a cooldown. Nothing gates it but the cells themselves.

# Weapon categories, from taxonomy.md. A weapon's subtype is its category.
WEAPON_CATEGORIES = (
  "hacking", "slashing", "bludgeoning", "thrusting", "projectile",
  "blocking", "channeling", "warding", "infusing",
  "miscellaneous",
)

#[[ Tool-like gear that is not a real weapon or a real armour piece.
#
# A miscellaneous WEAPON always rolls 1-4 whatever its tier -- it is a tool you
# are swinging, not something forged to fight with. A miscellaneous ARMOUR has
# no weight, so nothing gates it, exactly like a trinket.
MISC = "miscellaneous"
MISC_DAMAGE = (1, 4)

# Armor weights. An armor's subtype is its weight.
ARMOR_SUBTYPES = ("heavy", "medium", "light", "trinket", "miscellaneous")

#[[ Qualifying stats per weapon category and armor weight, from taxonomy.md.
#
# A tier-N item needs level N in ANY ONE of these -- they are alternatives,
# never a stack. Derived here rather than authored so the sheet cannot disagree
# with the taxonomy.
STAT_BY_CATEGORY = {
  "hacking": ("STR",),
  "bludgeoning": ("STR",),
  "slashing": ("STR", "STA"),
  "thrusting": ("STR", "AGI"),
  "projectile": ("AGI",),
  "channeling": ("AGI",),
  "blocking": ("STA",),
  "warding": ("STA",),
  "infusing": ("INT",),          # plus the element's own stat, below
  "miscellaneous": (),           # a tool, not a weapon -- nothing gates it
}
#[[ Armor qualifying stats. `trinket` is deliberately absent: it has no weight,
# so nothing gates it -- anyone may wear it and the tier alone scales its power.
STAT_BY_WEIGHT = {
  "heavy": ("STR", "STA"),
  "medium": ("AGI", "STA"),
  "light": ("INT", "STA"),
}
# Infusion elements add a second qualifying stat, matching the physical
# passive they mirror.
STAT_BY_ELEMENT = {"shadow": "AGI", "frost": "STA"}  # keys match lowercased subsubtype

#[[ Damage ranges, from taxonomy.md.
#
#   1H standard  tier 0 is 1-6; each tier is lo+2, hi+3  (+2.5 EV per tier)
#   2H           double both ends
#   slashing     same floor, ceiling -1   (-0.5 EV per hand)
#
# Derived, never authored, so a balance change is one edit here.
TIER0_LO, TIER0_HI = 1, 6
TIER_LO_STEP, TIER_HI_STEP = 2, 3
FIST = (1, 4)


#[[ What POOL a hit lands in, from the weapon category. Mirrors the sheet
# formula in damage_type/armor_type, but derived here because the sheet's
# cached formula results are lost whenever a tool writes the file with
# openpyxl -- tools/sync/sync_gold.py does exactly that. The sheet column stays as
# a visual cross-check; this is the authority.
DAMAGE_TYPE_BY_CATEGORY = {
  "channeling": "Magical",
  "infusing": "Magical",
  "blocking": "Anti-Physical",
  "warding": "Anti-Magical",
}
DEFAULT_DAMAGE_TYPE = "Physical"


def damage_type(category):
  """The pool a weapon's damage applies to, or None when it has no damage."""
  if not category:
    return None
  return DAMAGE_TYPE_BY_CATEGORY.get(category, DEFAULT_DAMAGE_TYPE)


def damage_range(tier, hands, category):
  """The (lo, hi) a weapon rolls, or None when it is not a weapon."""
  # A tool swung in anger is always 1-4, on every tier.
  if category == MISC:
    return MISC_DAMAGE
  if tier is None:
    return None
  lo = TIER0_LO + TIER_LO_STEP * tier
  hi = TIER0_HI + TIER_HI_STEP * tier
  if category == "slashing":          # the flex weapon pays -0.5 EV per hand
    hi -= 1
  if hands == 2:                      # 2H doubles both ends
    lo, hi = 2 * lo, 2 * hi
  return (lo, hi)


warnings = []


def warn(msg):
  warnings.append(msg)


def lua_str(s):
  r"""Quote a string for Lua, turning real newlines into the \n ESCAPE.

  A raw newline inside a double-quoted Lua string is a syntax error, so it has
  to become the two-character escape. Authors may write either a literal
  newline inside a quoted cell or the sentinel \n -- normalise_newlines() has
  already collapsed both to a real newline by the time we get here.
  """
  s = s.replace("\\", "\\\\").replace('"', '\\"')
  s = s.replace("\r", "").replace("\n", "\\n")
  return '"' + s + '"'


def normalise_newlines(cell, where):
  r"""Collapse the accepted newline spellings to one real newline.

  Accepted:  the sentinel \n  (recommended: keeps one item per CSV line, so
             diffs and spreadsheet sorting stay sane)
             a literal newline inside a "quoted cell"
  Flagged:   /n  -- forward slash, the natural typo
  """
  text = (cell or "").strip()
  if not text:
    return ""
  if "/n" in text:
    warn("%s: contains '/n' (forward slash) -- did you mean '\\n'?" % where)
  if "\\\\n" in text:
    warn("%s: contains '\\\\n' -- treating as a line break" % where)
    text = text.replace("\\\\n", "\\n")
  return text.replace("\\n", "\n")


def read_values(path):
  """The allowed values per column, read off the `_values` sheet.

  Row 2 holds the column names, rows 3+ the values beneath each. This is the
  same range the Excel dropdowns point at, so extending a vocabulary means
  adding a row there and nothing else.
  """
  wb = load(path)
  if VALUES_SHEET not in wb.sheetnames:
    return {}
  ws = wb[VALUES_SHEET]
  out = {}
  for col in ws.iter_cols(min_row=2):
    header = col[0].value
    if not header:
      continue
    vals = set()
    for c in col[1:]:
      if c.value is not None and str(c.value).strip():
        vals.add(str(c.value).strip().lower())
    if vals:
      out[str(header).strip()] = vals
  return out


def compose_description(it):
  """Build the in-game description block from the sheet's columns.

  The description is GENERATED, never authored -- only `flavor` and `effect`
  are written by hand. Layout:

      Type | Subtype, Subsubtype
      Tier N (Stat), basegold

      damage or armor range
      cooldown - uses
      effect

      flavor

  Empty sections collapse, so a Ration is just its heading and its flavour
  while a tier-2 greatsword fills every line.
  """
  def line(parts, sep=" - "):
    return sep.join(p for p in parts if p)

  blocks = []

  #[[ heading, two lines:
  #     Weapon | Slashing, 2H Greatsword
  #     Tier 2 (STR or STA), 120g
  # The type is set off by a pipe; the rest of the chain is comma-separated.
  rest = line([it["subtype"].title(), it["subsubtype"].title()], sep=", ")
  chain = line([it["type"].title(), rest], sep=" | ")

  tier = ""
  if it["tier"] is not None:
    tier = "Tier %d" % it["tier"]
    if it["stats"]:
      tier += " (%s)" % " or ".join(it["stats"])
  ident = line([tier,
                # 0g is a real price (junk), so test for None, not falsiness.
                ("%sg" % it["base_gold"])
                if it["base_gold"] is not None else ""],
               sep=", ")
  blocks.append("\n".join(x for x in (chain, ident) if x))

  # mechanics: the numbers, then what it does
  dmg = it["damage"]
  #[[ A range carries its damage/armor TYPE, and an item may have two of them:
  #
  #     1-3 Physical
  #     1-3 Physical, 1-3 Magical
  #
  # The primary range is derived (weapons) or authored (armor); the secondary
  # pair is authored in both cases and is normally blank. A range with no type
  # prints bare, so an older row that predates the type columns still renders.
  def ranged(primary, ptype, secondary, stype):
    parts = []
    if primary:
      parts.append(line([primary, ptype], sep=" "))
    if secondary:
      parts.append(line([secondary, stype], sep=" "))
    return ", ".join(parts)

  if dmg:
    numbers = ranged("%d-%d" % dmg, it["damage_type"],
                     it["damage_range2"], it["damage_type2"])
  else:
    numbers = ranged(it["armor_range"], it["armor_type"],
                     it["armor_range2"], it["armor_type2"])

  mech = [
    numbers,
    line([("CD: %d" % it["cooldown"]) if it["cooldown"] is not None else "",
          ("Use: %d" % it["uses"]) if it["uses"] is not None else ""]),
    it["effect"],
  ]
  mech = [x for x in mech if x]
  if mech:
    blocks.append("\n".join(mech))

  #[[ Flavor is quoted in game but typed plainly in the sheet, so the quotes go
  # on here. An author who quoted it anyway is not double-quoted. ]]
  if it["description"]:
    flavor = it["description"]
    if not (flavor.startswith('"') and flavor.endswith('"')):
      flavor = '"%s"' % flavor
    blocks.append(flavor)

  return "\n\n".join(blocks)


def int_cell(cell, where, field):
  """A non-negative integer, or None when the cell is blank.

  A numeric 0 is a real value, not a blank: junk prices at 0g. Testing
  falsiness here would read it back as "no price".
  """
  if isinstance(cell, (int, float)) and not isinstance(cell, bool):
    n = int(cell)
    if n < 0:
      sys.exit("%s: %s cannot be negative (%d)" % (where, field, n))
    return n
  text = (cell or "").strip()
  if not text:
    return None
  try:
    n = int(text)
  except ValueError:
    sys.exit("%s: %s must be a whole number, got %r" % (where, field, text))
  if n < 0:
    sys.exit("%s: %s cannot be negative (%d)" % (where, field, n))
  return n


def compose_token_description(tk):
  """The in-game description of a token, built like an item's:

      Enemy | Combat, Brute
      Marquisate
      Tier 1, 20 EXP

      effect

      "flavor"

  Empty parts collapse, so a shop token is "Neutral | Shop" over its faction.
  """
  kind = ", ".join(x.title() for x in (tk["role"], tk["subtype"]) if x)
  heading = " | ".join(x for x in (tk["affiliation"].title(), kind) if x)
  level = ", ".join(x for x in (
      "Tier %d" % tk["tier"] if tk["tier"] is not None else "",
      "%d EXP" % tk["exp"] if tk["exp"] is not None else "") if x)
  blocks = ["\n".join(x for x in (heading, tk["faction_name"], level) if x)]
  if tk["effect"]:
    blocks.append(tk["effect"])
  if tk["flavor"]:
    flavor = tk["flavor"]
    if not (flavor.startswith('"') and flavor.endswith('"')):
      flavor = '"%s"' % flavor
    blocks.append(flavor)
  return "\n\n".join(b for b in blocks if b)


def unique_ids(rows, key):
  """The set of `key` values across rows, failing on a repeat."""
  seen = {}
  for r in rows:
    if r[key] in seen:
      sys.exit("duplicate %s %r (%s and %s)"
               % (key, r[key], seen[r[key]], r["_where"]))
    seen[r[key]] = r["_where"]
  return set(seen)


def read_loot_tables(wb, tile_names):
  """The loot_ids on the loot_table sheet, every drop checked.

  Same columns and spawn-cell grammar as lootbox_table. A drop naming an
  item tiles.xlsx does not have would fail only when the token dies, so it
  fails here instead. Statuses come from their own bag and are not checked.
  """
  rows = read_rows(TOKENS, LOOT_TABLE_SHEET, "loot_id", wb)
  for r in rows:
    read_spawn(r)   # exits on a malformed spawngold
    for ref in referenced_names(r, keys=("items",)):
      if ref not in tile_names:
        sys.exit("%s: drops %r, which is not in tiles.xlsx"
                 % (r["_where"], ref))
  return unique_ids(rows, "loot_id")


def read_tokens(seen_names, template_types):
  """Every row of tokens.xlsx, validated, in sheet order.

  `seen_names` and `template_types` hold what the tiles already claimed and
  are extended here: seen_names is every name a spawn cell may reference, and
  one template object is one TTS type.
  """
  if not os.path.exists(TOKENS):
    warn("missing %s -- no tokens imported" % TOKENS)
    return []
  wb = load(TOKENS)
  vocab = read_values(TOKENS)
  factions = {f["faction_id"]: f.get("name") or f["faction_id"]
              for f in read_rows(TOKENS, FACTIONS_SHEET, "faction_id", wb)}
  loot_ids = read_loot_tables(wb, set(seen_names))
  stats_ids = unique_ids(read_rows(TOKENS, STATS_TABLE_SHEET, "stats_id", wb),
                         "stats_id")

  # A shops.xlsx row without a display name is a prefilled id, not a shop.
  shop_ids = set()
  if os.path.exists(SHOPS):
    shop_ids = {r["shop_id"] for r in read_rows(SHOPS, "shops", "shop_id")
                if r.get("shop_role_display")}
  shop_owner = {}

  tokens = []
  seen_ids = {}
  token_names = {}
  # NAME makes a row a token, exactly as for tiles: ids, template and
  # tts_type are prefilled far ahead of the tokens themselves.
  for r in read_rows(TOKENS, TOKEN_SHEET, "name", wb):
    where = r["_where"]
    name = r["name"]
    tid = r.get("token_id", "")
    tts_type = r.get("tts_type", "").lower()
    role = r.get("role", "").lower()
    subtype = r.get("subtype", "").lower()
    affiliation = r.get("affiliation", "").lower()
    # Blank faction means the Woodland's own unaligned folk.
    faction = r.get("faction", "") or "none"

    # role and affiliation only describe a token, so either may be blank.
    for field, value in (("token_id", tid), ("set", r.get("set", ""))):
      if not value:
        sys.exit("%s (%s): missing %s" % (where, name, field))
    if tts_type != "token":
      sys.exit("%s (%s): tts_type must be 'token' in tokens.xlsx, got %r"
               % (where, name, tts_type))
    for field, value in (("role", role), ("affiliation", affiliation)):
      allowed = vocab.get(field, ())
      if value and allowed and value not in allowed:
        sys.exit("%s (%s): %s %r is not on the _values sheet (allowed: %s)"
                 % (where, name, field, value, "/".join(sorted(allowed))))

    #[[ A role with a sub_<role> column on _values must pick from it; a role
    # without one (shop, flavor) has no subtype at all.
    subtypes = vocab.get("sub_" + role)
    if subtypes:
      if subtype not in subtypes:
        sys.exit("%s (%s): a %s token's subtype must be one of %s, got %r"
                 % (where, name, role, "/".join(sorted(subtypes)), subtype))
    elif subtype:
      sys.exit("%s (%s): a %s token has no subtype; leave it blank"
               % (where, name, role or "role-less"))

    if faction not in factions:
      sys.exit("%s (%s): faction %r is not on the factions sheet"
               % (where, name, faction))
    tier = int_cell(r.get("tier"), where, "tier")
    if tier is not None and tier > 3:
      sys.exit("%s (%s): tier must be 0-3, got %d" % (where, name, tier))
    exp = int_cell(r.get("exp"), where, "exp")

    #[[ A friendly token cannot be killed, so it drops nothing; a token that
    # never fights has no combat numbers.
    loot = r.get("loot_table", "")
    if loot and loot not in loot_ids:
      sys.exit("%s (%s): loot_table %r is not on the loot_table sheet"
               % (where, name, loot))
    if loot and affiliation == "friendly":
      sys.exit("%s (%s): a friendly token cannot be killed; leave loot_table "
               "blank" % (where, name))
    stats = r.get("stats_table", "")
    if stats and stats not in stats_ids:
      sys.exit("%s (%s): stats_table %r is not on the stats_table sheet"
               % (where, name, stats))
    if stats and role != COMBAT_ROLE:
      sys.exit("%s (%s): a %s token does not fight; leave stats_table blank"
               % (where, name, role))

    template = template_cell(r, where)
    first = template_types.setdefault(template, (tts_type, where))
    if first[0] != tts_type:
      sys.exit("%s (%s): template %s is a %s here but a %s at %s -- one "
               "template object is one TTS type"
               % (where, name, template, tts_type, first[0], first[1]))

    if tid in seen_ids:
      sys.exit("duplicate token_id %r (%s and %s)"
               % (tid, seen_ids[tid], where))
    seen_ids[tid] = where
    #[[ Tokens live in the meeple bag, tiles in the item bag, so only a
    # repeat among TOKENS collides. seen_names still collects them all, as
    # the set of names a spawn cell may reference.
    if name in token_names:
      sys.exit("duplicate token name %r (%s and %s) -- tokens share the meeple "
               "bag, so findInBag would never reach the second one"
               % (name, token_names[name], where))
    token_names[name] = where
    seen_names.setdefault(name, where)

    gmnotes = normalise_newlines(r.get("gmnotes"),
                                 "%s (%s) gmnotes" % (where, name))
    #[[ The Merchant Board reads a shop token's GMNotes as its shop_id, and
    # sync_merchant_board.py takes the shop's tier and faction from this row.
    if role == SHOP_ROLE:
      if tier is None:
        sys.exit("%s (%s): a shop token needs a tier (0-3) -- the board shows "
                 "it as the settlement size" % (where, name))
      if gmnotes not in shop_ids:
        sys.exit("%s (%s): a shop token's gmnotes must be a shop_id from "
                 "shops.xlsx, got %r" % (where, name, gmnotes))
      if gmnotes in shop_owner:
        sys.exit("%s (%s): shop_id %r is already used by %s"
                 % (where, name, gmnotes, shop_owner[gmnotes]))
      shop_owner[gmnotes] = where

    if not r.get("image_front"):
      warn("%s (%s): no image_front -- clone keeps the template's face"
           % (where, name))

    tk = {
      "id": tid,
      "name": name,
      "tts_type": tts_type,
      "template": template,
      "set": r["set"],
      "role": role,
      "subtype": subtype,
      "affiliation": affiliation,
      "faction": faction,
      "faction_name": factions[faction],
      "tier": tier,
      "exp": exp,
      "loot_table": loot,
      "stats_table": stats,
      "effect": normalise_newlines(r.get("effect"),
                                   "%s (%s) effect" % (where, name)),
      "flavor": normalise_newlines(r.get("flavor"),
                                   "%s (%s) flavor" % (where, name)),
      "gmnotes": gmnotes,
      "front": r.get("image_front", ""),
    }
    tk["description"] = compose_token_description(tk)
    tokens.append(tk)

  for sid in sorted(shop_ids - set(shop_owner)):
    warn("shops.xlsx %s has no shop token in tokens.xlsx -- "
         "sync_merchant_board.py will refuse it" % sid)

  tokens += read_landmarks(wb, factions, seen_ids, token_names, seen_names, template_types)
  return tokens


def read_landmarks(wb, factions, seen_ids, token_names, seen_names, template_types):
  """The landmarks sheet: map places (caves, shrines, camps) as tokens.

  Shares the meeple bag with tokens, so ids and names must not repeat across
  the two sheets. Columns: landmark_id, template, tts_type, set, name,
  faction, tier, effect, gmnotes, image_front. Description reads
  "Landmark / <faction> / Tier N / effect".
  """
  if LANDMARK_SHEET not in wb.sheetnames:
    return []
  out = []
  for r in read_rows(TOKENS, LANDMARK_SHEET, "name", wb):
    where = r["_where"]
    name = r["name"]
    lid = r.get("landmark_id", "")
    tts_type = r.get("tts_type", "").lower()
    faction = r.get("faction", "") or "none"
    for field, value in (("landmark_id", lid), ("set", r.get("set", ""))):
      if not value:
        sys.exit("%s (%s): missing %s" % (where, name, field))
    if tts_type != "token":
      sys.exit("%s (%s): tts_type must be 'token', got %r" % (where, name, tts_type))
    if faction not in factions:
      sys.exit("%s (%s): faction %r is not on the factions sheet" % (where, name, faction))
    tier = int_cell(r.get("tier"), where, "tier")
    if tier is not None and tier > 3:
      sys.exit("%s (%s): tier must be 0-3, got %d" % (where, name, tier))
    template = template_cell(r, where)
    first = template_types.setdefault(template, (tts_type, where))
    if first[0] != tts_type:
      sys.exit("%s (%s): template %s is a %s here but a %s at %s -- one "
               "template object is one TTS type"
               % (where, name, template, tts_type, first[0], first[1]))
    if lid in seen_ids:
      sys.exit("duplicate id %r (%s and %s)" % (lid, seen_ids[lid], where))
    seen_ids[lid] = where
    if name in token_names:
      sys.exit("duplicate token name %r (%s and %s) -- landmarks share the meeple "
               "bag with tokens, so findInBag would never reach the second one"
               % (name, token_names[name], where))
    token_names[name] = where
    seen_names.setdefault(name, where)
    if not r.get("image_front"):
      warn("%s (%s): no image_front -- clone keeps the template's face" % (where, name))
    tk = {
      "id": lid, "name": name, "tts_type": tts_type, "template": template, "set": r["set"],
      "role": LANDMARK_ROLE, "subtype": "", "affiliation": "", "faction": faction,
      "faction_name": factions[faction],
      "tier": tier, "exp": None, "loot_table": "", "stats_table": "",
      "effect": normalise_newlines(r.get("effect"), "%s (%s) effect" % (where, name)),
      "flavor": "",
      "gmnotes": normalise_newlines(r.get("gmnotes"), "%s (%s) gmnotes" % (where, name)),
      "front": r.get("image_front", ""),
    }
    tk["description"] = compose_token_description(tk)
    out.append(tk)
  return out


def main():
  #[[ NAME is what makes a row an item. Nothing else does.
  #
  # The sheets carry their derived formulas down every row to row 500, and
  # item_id / tts_type / set are routinely PREFILLED far ahead of the item
  # itself -- a block of ids reserved for a set that has not been written
  # yet. Neither a formula artefact nor a prefilled id is an item, so a row
  # joins the build the moment it is given a name and not before.
  rows = read_rows(TILES, ITEM_SHEETS, "name")

  if not rows:
    sys.exit("no items in " + TILES)

  items = []
  seen_ids = {}
  seen_names = {}
  template_types = {}

  # The vocabularies Excel enforces, read from the same sheet the dropdowns
  # use -- so extending a list means adding a row there, nothing here.
  vocab = read_values(TILES)

  for r in rows:
    where = r["_where"]
    iid = (r.get("item_id") or "").strip()
    name = (r.get("name") or "").strip()
    tts_type = (r.get("tts_type") or "").strip().lower()
    iset = (r.get("set") or "").strip()
    itype = (r.get("type") or "").strip().lower()
    subtype = (r.get("subtype") or "").strip().lower()
    subsubtype = (r.get("subsubtype") or "").strip().lower()

    #[[ A named row is a real item, so it must now carry the rest. item_id is
    # checked HERE rather than at read time: prefilling ids ahead of the items
    # is fine, but a named item without one is an authoring slip.
    if not iid:
      sys.exit("%s (%s): missing item_id" % (where, name))
    if not iset:
      sys.exit("%s (%s): missing set" % (where, name))

    for field, value in (("tts_type", tts_type), ("type", itype),
                         ("subtype", subtype)):
      allowed = vocab.get(field, ())
      if value and allowed and value not in allowed:
        sys.exit("%s (%s): %s %r is not on the _values sheet (allowed: %s)"
                 % (where, name, field, value, "/".join(sorted(allowed))))
    if not tts_type:
      sys.exit("%s (%s): missing tts_type" % (where, name))
    if not itype:
      sys.exit("%s (%s): missing type" % (where, name))

    #[[ One template object is one TTS type. The importer checks the object
    # against its first row's tts_type, so rows that disagree would clone the
    # wrong kind of object for the rest.
    template = template_cell(r, where)
    first = template_types.setdefault(template, (tts_type, where))
    if first[0] != tts_type:
      sys.exit("%s (%s): template %s is a %s here but a %s at %s -- one "
               "template object is one TTS type"
               % (where, name, template, tts_type, first[0], first[1]))

    if iid in seen_ids:
      sys.exit("duplicate item_id %r (%s and %s)" % (iid, seen_ids[iid], where))
    seen_ids[iid] = where
    # A duplicate name is fatal: findInBag() in global.lua returns the FIRST
    # match, so the later copy would be permanently unreachable.
    if name in seen_names:
      sys.exit("duplicate item name %r (%s and %s) -- findInBag would "
               "never reach the second one" % (name, seen_names[name], where))
    seen_names[name] = where

    #[[ Gear sits on the tier ladder; everything else does not.
    #
    # A weapon's subtype is its CATEGORY (hacking, warding, ...); an armor's
    # subtype is its WEIGHT (heavy/medium/light). Both drive the qualifying
    # stat and, for weapons, the damage range.
    tier = int_cell(r.get("tier"), where, "tier")
    hands = None
    damage = None
    stats = ()

    if itype in GEAR_TYPES:
      if tier is None and subtype != MISC:
        sys.exit("%s (%s): %s needs a tier (0-3)" % (where, name, itype))
      if tier is not None and tier > 3:
        sys.exit("%s (%s): tier must be 0-3, got %d" % (where, name, tier))

      if itype == "weapon":
        if subtype not in WEAPON_CATEGORIES:
          sys.exit("%s (%s): a weapon's subtype must be a category (%s), got %r"
                   % (where, name, "/".join(WEAPON_CATEGORIES), subtype))
        #[[ subsubtype names the variant, e.g. "2H Greatsword" or
        # "1H Fire Mote". The hand count is its prefix and, for an infusion,
        # the element is the word in the middle -- both are read out of the
        # text so the sheet carries one human-readable value instead of three
        # machine columns.
        if not subsubtype:
          sys.exit("%s (%s): a weapon needs a subsubtype naming its variant, "
                   "e.g. '1H Sword' or '2H Fire Heart'" % (where, name))
        if not subsubtype.startswith(("1h", "2h")):
          sys.exit("%s (%s): subsubtype %r must start with 1H or 2H"
                   % (where, name, subsubtype))
        hands = 2 if subsubtype.startswith("2h") else 1
        damage = damage_range(tier, hands, subtype)
        stats = list(STAT_BY_CATEGORY[subtype])
        if subtype == "infusing":
          for element, extra in STAT_BY_ELEMENT.items():
            if element in subsubtype:
              stats.append(extra)
              break
      else:  # armor
        if subtype not in ARMOR_SUBTYPES:
          sys.exit("%s (%s): an armor's subtype must be one of %s, got %r"
                   % (where, name, "/".join(ARMOR_SUBTYPES), subtype))
        # a trinket has no weight, so no qualifying stat -- anyone may wear it
        stats = list(STAT_BY_WEIGHT.get(subtype, ()))
    elif tier is not None:
      #[[ Non-gear may carry a tier too -- a tier-0 ore feeds a tier-0 weapon,
      # so materials, consumables and goods all sit on the same ladder. They
      # simply have no damage range and no qualifying stat derived from it.
      if tier is not None and tier > 3:
        sys.exit("%s (%s): tier must be 0-3, got %d" % (where, name, tier))

    #[[ `stat` is DERIVED, never authored: it follows from the category or
    # weight, so the sheet cannot disagree with the taxonomy. If the author
    # filled it in anyway, it must match.
    authored = (r.get("stat") or "").strip().upper()
    derived = " OR ".join(stats)
    if authored and derived and authored.replace(" OR ", " OR ") != derived:
      warn("%s (%s): stat %r was authored but is derived as %r -- the derived "
           "value wins" % (where, name, authored, derived))

    front = (r.get("image_front") or "").strip()
    back = (r.get("image_back") or "").strip()

    # Tokens are a single image with a generated outline; they have no
    # image_bottom. A back URL on one is dead data, not an error.
    if tts_type == "token" and back:
      warn("%s (%s): image_back is ignored for tokens" % (where, name))
    if not front:
      warn("%s (%s): no image_front -- clone keeps the template's face"
           % (where, name))

    #[[ Cooldown and uses are MAXIMA, authored here. `memo` is their runtime
    # counterpart and is NOT authored: the importer seeds it from these numbers
    # and the game owns it from then on.
    #
    #   sheet   cooldown=3, uses=5     the maxima
    #   memo    "CD: 0 | Use: 5"       seeded at import, then mutated in play
    #
    # An item becomes interactive purely by having one of these filled in --
    # no type or subtype gates it. The tags are derived from the same numbers,
    # so a tag can never disagree with them.
    #
    # CD seeds at 0 (READY), not at its maximum: cooldown counts time
    # REMAINING, so a fresh item is usable and jumps to the full value when
    # spent. Uses seed at their maximum, counting down.
    cooldown = int_cell(r.get("cooldown"), where, "cooldown")
    uses = int_cell(r.get("uses"), where, "uses")
    if cooldown == 0:
      sys.exit("%s (%s): cooldown 0 means no cooldown; leave it blank"
               % (where, name))
    if uses == 0:
      sys.exit("%s (%s): uses 0 means the item is already spent; leave it "
               "blank" % (where, name))

    tags = []
    memo_parts = []
    if cooldown is not None:
      tags.append("Item-Cooldown")
      memo_parts.append("CD: 0")
    if uses is not None:
      tags.append("Item-Uses")
      memo_parts.append("Use: %d" % uses)
    memo = " | ".join(memo_parts)

    items.append({
      "id": iid,
      "name": name,
      "tts_type": tts_type,
      "template": template,
      "set": iset,
      "type": itype,
      "subtype": subtype,
      "subsubtype": subsubtype,
      "tier": tier,
      "hands": hands,
      "damage": damage,
      "stats": stats,
      "tags": tags,
      "cooldown": cooldown,
      "uses": uses,
      "memo": memo,
      "front": front,
      "back": back,
      # Computed by tools/sync/sync_gold.py. Kept as an int so ITEM_DATA can carry
      # it for a vendor to price against, not just render it into the text.
      "base_gold": int_cell(r.get("base_gold"), where, "base_gold"),
      "armor_range": (r.get("armor_range") or "").strip(),
      # Derived like damage_type: the sheet's formula cache does not survive a
      # tool writing the file, so Python is the authority for both.
      "armor_type": (damage_type(subtype) if itype == "armor" else "") or "",
      "armor_range2": (r.get("armor_range2") or "").strip(),
      "armor_type2": (r.get("armor_type2") or "").strip(),
      "damage_type": (damage_type(subtype) if damage else "") or "",
      "damage_range2": (r.get("damage_range2") or "").strip(),
      "damage_type2": (r.get("damage_type2") or "").strip(),
      "effect": normalise_newlines(r.get("effect"),
                                   "%s (%s) effect" % (where, name)),
      "description": normalise_newlines(r.get("flavor"),
                                        "%s (%s) flavor" % (where, name)),
      "gmnotes": normalise_newlines(r.get("gmnotes"),
                                    "%s (%s) gmnotes" % (where, name)),
    })

  tokens = read_tokens(seen_names, template_types)

  template_collisions(template_types,
                      [it["gmnotes"] for it in items + tokens],
                      "an item's gmnotes")

  # ---- cross-check against the event spawn tables -------------------------
  # This is the check worth having: an item name typo'd in scenarios.xlsx
  # currently fails only in-game, and silently enough to miss.
  #[[ The REVERSE is deliberately NOT checked. An item no event spawns is
  # normal -- most items are shop, drop-table or lootbox content and are never
  # named by an event, so flagging them was noise on almost every build.
  known = set(seen_names)
  if os.path.exists(SCENARIOS):
    # Only outcomes spawn; intros have no spawn columns.
    for r in read_rows(SCENARIOS, SCENARIO_OUTCOMES, "outcome_key"):
      nid = outcome_id(r.get("scenario_id", ""), r["outcome_key"])
      # items only: statuses come from their own bag and are not in tiles.xlsx.
      seen_missing = set()
      for nm in referenced_names(r, keys=("items",)):
        if nm not in known and nm not in seen_missing:
          seen_missing.add(nm)
          #[[ A WARNING, not a failure. Content is authored in two places at
          # different speeds: an event may name an item before the sheet has
          # it. The spawn will fail in game with '"X" is not in bag ...', so
          # this still needs fixing -- it just must not block the build.
          warn("scenarios.xlsx node %s spawns %r, which is not in "
               "tiles.xlsx -- the spawn will fail in game" % (nid, nm))
  else:
    warn("missing %s -- skipped the spawn cross-check" % SCENARIOS)

  # The description shown in game is composed from the columns, not authored.
  for it in items:
    it["description"] = compose_description(it)

  # ---- build the Lua ------------------------------------------------------
  # Array-ordered (sheet order) so the import order is the authored order, plus a
  # derived set index so the button grid needs no runtime scanning.
  def num(v):
    return "nil" if v is None else str(v)

  L = ["-- GENERATED by tools/sync/sync_items_data.py -- do not edit by hand",
       "ITEM_DATA = {"]
  for it in items:
    dmg = it["damage"]
    L.append("  {id = %s, name = %s, tts_type = %s, template = %s, set = %s,"
             % (lua_str(it["id"]), lua_str(it["name"]),
                lua_str(it["tts_type"]), lua_str(it["template"]),
                lua_str(it["set"])))
    L.append("   type = %s, subtype = %s, subsubtype = %s,"
             % (lua_str(it["type"]), lua_str(it["subtype"]),
                lua_str(it["subsubtype"])))
    L.append("   tier = %s, hands = %s, stats = {%s},"
             % (num(it["tier"]), num(it["hands"]),
                ", ".join(lua_str(x) for x in it["stats"])))
    L.append("   damage_low = %s, damage_high = %s, tags = {%s},"
             % (num(dmg[0] if dmg else None), num(dmg[1] if dmg else None),
                ", ".join(lua_str(t) for t in it["tags"])))
    L.append("   cooldown = %s, uses = %s, base_gold = %s,"
             % (num(it["cooldown"]), num(it["uses"]),
                num(it["base_gold"])))
    L.append("   image_front = %s, image_back = %s,"
             % (lua_str(it["front"]), lua_str(it["back"])))
    L.append("   description = %s, gmnotes = %s, memo = %s},"
             % (lua_str(it["description"]), lua_str(it["gmnotes"]),
                lua_str(it["memo"])))
  #[[ Tokens carry their own fields plus the few the importer reads off every
  # entry (template, tts_type, set, name, images, description, gmnotes, memo,
  # tags), so one import loop serves both.
  for tk in tokens:
    L.append("  {id = %s, name = %s, tts_type = \"token\", template = %s, "
             "set = %s," % (lua_str(tk["id"]), lua_str(tk["name"]),
                            lua_str(tk["template"]), lua_str(tk["set"])))
    L.append("   role = %s, subtype = %s, affiliation = %s, faction = %s,"
             % (lua_str(tk["role"]), lua_str(tk["subtype"]),
                lua_str(tk["affiliation"]), lua_str(tk["faction"])))
    L.append("   tier = %s, exp = %s, loot_table = %s, stats_table = %s,"
             % (num(tk["tier"]), num(tk["exp"]), lua_str(tk["loot_table"]),
                lua_str(tk["stats_table"])))
    L.append("   tags = {}, image_front = %s, image_back = \"\","
             % lua_str(tk["front"]))
    L.append("   description = %s, gmnotes = %s, memo = \"\"},"
             % (lua_str(tk["description"]), lua_str(tk["gmnotes"])))
  L.append("}")
  L.append("")

  # Sets per tts_type, in first-seen order -- the order the buttons appear in.
  L.append("-- Sets per tts_type, in sheet order. Drives the button grid.")
  L.append("ITEM_SETS = {")
  for t in ("tile", "token"):
    ordered = []
    for it in items + tokens:
      if it["tts_type"] == t and it["set"] not in ordered:
        ordered.append(it["set"])
    L.append("  %s = {%s}," % (t, ", ".join(lua_str(x) for x in ordered)))
  L.append("}")
  data_lua = "\n".join(L)

  os.makedirs(os.path.dirname(OUT), exist_ok=True)
  with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(data_lua + "\n")

  if not os.path.exists(SRC):
    sys.exit("missing %s" % SRC)
  with open(SRC, encoding="utf-8") as f:
    script = inline_shared(f.read())
  block = BEGIN + "\n" + data_lua + "\n" + END
  if BEGIN in script and END in script:
    script = script.split(BEGIN)[0] + block + script.split(END, 1)[1]
  else:
    script = block + "\n\n" + script
  bag_script = staged_path(BAG_GUID)
  with open(bag_script, "w", encoding="utf-8", newline="\n") as f:
    f.write(script)

  for w in warnings:
    print("  warning: " + w)
  gear = [it for it in items if it["tier"] is not None]
  print("wrote %s (%d items, %d gear, %d tokens)"
        % (os.path.relpath(OUT, ROOT), len(items), len(gear), len(tokens)))
  print("wrote %s (%d bytes, data inlined)"
        % (os.path.relpath(bag_script, WORKSPACE), len(script)))


main()
