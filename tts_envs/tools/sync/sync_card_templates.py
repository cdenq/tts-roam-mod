#!/usr/bin/env python3
"""Fill the derived `template` column on cards.xlsx event_intro and origins.

The templates ARE generic cards: a generic row's id is the GMNotes of the card
the importer clones, and its `template_for` says whose template it is -- a
region from _values, or "origins". So:

  event_intro.template  = id of the generic row whose template_for is the row's region
  origins.template      = id of the generic row whose template_for is "origins"

Also checks every event_intro region against _values (the dropdown's source).
Writes INTO data/, like sync_gold; runs before the syncs that read template.

Run: python tools/sync/sync_card_templates.py
"""
import os, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from datasets import (CARDS, GENERIC_SHEET, EVENT_INTRO, ORIGINS_SHEET,
                      TEMPLATE_FOR, ORIGINS_TEMPLATE_FOR, load, read_rows,
                      region_values, write_back, save)


def templates_by_target(wb, regions):
  allowed = set(regions) | {ORIGINS_TEMPLATE_FOR}
  out = {}
  for r in read_rows(CARDS, GENERIC_SHEET, "id", wb):
    target = r.get(TEMPLATE_FOR, "")
    if not target:
      continue
    if target not in allowed:
      sys.exit("%s: %s %r is not a region in _values or %r"
               % (r["_where"], TEMPLATE_FOR, target, ORIGINS_TEMPLATE_FOR))
    if target in out:
      sys.exit("%s: %s %r is already %s's" % (r["_where"], TEMPLATE_FOR, target, out[target]))
    out[target] = r["id"]
  return out


def fill(rows, template_of):
  """Set each row's template; returns how many changed."""
  changed = 0
  for r in rows:
    t = template_of(r)
    if r.get("template", "") != t:
      r["template"] = t
      changed += 1
  return changed


def main():
  wb = load(CARDS, data_only=False)
  regions = region_values(wb)
  by_target = templates_by_target(wb, regions)

  events = read_rows(CARDS, EVENT_INTRO, "event_id", wb)
  for r in events:
    region = r.get("region", "")
    if region not in regions:
      sys.exit("%s: region %r is not in _values (have: %s)" % (r["_where"], region, " ".join(regions)))
    if region not in by_target:
      sys.exit("%s: no generic row has %s %r -- nothing to clone %s cards from"
               % (r["_where"], TEMPLATE_FOR, region, region))
  e_changed = fill(events, lambda r: by_target[r["region"]])

  origins = read_rows(CARDS, ORIGINS_SHEET, "origin_id", wb)
  if origins and ORIGINS_TEMPLATE_FOR not in by_target:
    sys.exit("cards.xlsx %s: no row has %s %r -- nothing to clone origins from"
             % (GENERIC_SHEET, TEMPLATE_FOR, ORIGINS_TEMPLATE_FOR))
  o_changed = fill(origins, lambda r: by_target[ORIGINS_TEMPLATE_FOR])

  if e_changed or o_changed:
    write_back(wb, EVENT_INTRO, events, ("template",))
    write_back(wb, ORIGINS_SHEET, origins, ("template",))
    save(wb, CARDS)
  print("sync_card_templates: %d event, %d origin templates updated" % (e_changed, o_changed))


if __name__ == "__main__":
  main()
