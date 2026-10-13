#!/usr/bin/env python3
"""Align each origin's effect prose to its spawngold value.

sync_gold.py computes spawngold from the origin's gold_tier, which leaves the
authored "Gain N gold." sentence stating a number the button no longer spawns.
The player reads the prose; the button pays spawngold. This rewrites the prose
to match.

spawngold is the authority here -- never the text. Only the number inside an
existing "Gain N gold." sentence is touched; nothing else in the effect moves.

Run AFTER tools/sync_gold.py (which writes spawngold) and BEFORE
tools/sync_origins_data.py (which reads effect into ORIGIN_DATA).

Run: python tools/sync_origin_text.py
"""
import os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasets import ORIGINS, ORIGINS_SHEET, load, read_rows, write_back, save

GOLD_SENTENCE = re.compile(r"Gain (\d+) gold\b")

warnings_out = []


def warn(msg):
  warnings_out.append(msg)


def main():
  wb = load(ORIGINS, data_only=False)
  rows = read_rows(ORIGINS, ORIGINS_SHEET, "origin_id", wb)
  if not rows:
    sys.exit("no origins in " + ORIGINS)
  for col in ("effect", "spawngold"):
    if col not in rows[0]:
      sys.exit("origins.xlsx has no %s column" % col)

  edits = []
  for r in rows:
    oid = (r.get("origin_id") or "").strip()
    name = (r.get("name") or "").strip()
    effect = r.get("effect") or ""
    raw = (r.get("spawngold") or "").strip()

    found = GOLD_SENTENCE.search(effect)

    if not raw:
      #[[ No coin to grant. A leftover "Gain N gold." would promise payment the
      # button never makes, so it is the text that is wrong -- but removing a
      # sentence cleanly is an authoring call, not a substitution.
      if found:
        warn("%s (%s): text says %s gold but spawngold is empty -- drop the "
             "sentence by hand" % (oid, name, found.group(1)))
      continue

    try:
      value = int(raw)
    except ValueError:
      warn("%s (%s): spawngold %r is not a number -- text left alone"
           % (oid, name, raw))
      continue

    if not found:
      warn("%s (%s): grants %d gold but the text never mentions gold -- add "
           "the sentence by hand" % (oid, name, value))
      continue

    if int(found.group(1)) == value:
      continue

    # One sentence per effect in practice; count=0 keeps a second one honest
    # rather than leaving it stale.
    r["effect"] = GOLD_SENTENCE.sub("Gain %d gold" % value, effect)
    edits.append((oid, name, found.group(1), value))

  if edits:
    write_back(wb, ORIGINS_SHEET, rows, ("effect",))
    save(wb, ORIGINS)

  for oid, name, was, now in edits:
    print("  %s (%s): %s -> %d gold" % (oid, name, was, now))
  print("sync_origin_text: rewrote %d of %d origin%s"
        % (len(edits), len(rows), "" if len(rows) == 1 else "s"))
  for w in warnings_out:
    print("  warning: " + w)
  return 0


if __name__ == "__main__":
  sys.exit(main())
