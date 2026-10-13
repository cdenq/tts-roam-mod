#!/usr/bin/env python3
"""Write the card importer's object script.

Unlike sync_items_data.py this inlines NO data -- only the shared template
import code from src/lib/ (see lua_inline.py). Cards carry only an id in
GMNotes; Global owns EVENT_DATA and does all the rendering, so the importer
reads CARD_SETS out of Global at runtime (Global.getVar). That is what keeps a
text fix cheap -- edit the CSV, sync, push, and cards already on the table
re-render without being re-imported.

So this is src/card_importer.lua, shared code pasted in, copied into the
extension's staging area under the bag's name. It exists so the bag is covered by master_sync.cmd
like everything else, and so the filename stays in one place.

Run: python tools/sync_card_importer.py
"""
import io, os, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spawn_cells import staged_path
from lua_inline import inline_shared

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
SRC = os.path.join(ROOT, "src", "card_importer.lua")

# The card importer bag in-game. BAG_NAME must match the filename the extension
# writes, which comes from the object's Nickname with /:<>"|?* and newlines
# stripped. Set BAG_GUID once the bag exists and has been pulled with Ctrl+Alt+L.
BAG_GUID = "4b808d"
BAG_NAME = "Card Importer"

# Staged filename resolved from the GUID at run time -- see staged_path.


def main():
  if not os.path.exists(SRC):
    sys.exit("missing %s" % SRC)
  script = inline_shared(io.open(SRC, encoding="utf-8").read())

  if BAG_GUID == "REPLACE_ME":
    print("  card importer: BAG_GUID not set yet in tools/sync_card_importer.py")
    print("  -> put the bag on the table, give it a one-line script in TTS,")
    print("     press Ctrl+Alt+L, then copy its GUID from the filename in")
    print("     .tts/objects/ into BAG_GUID and re-run.")
    return

  out = staged_path(BAG_GUID)
  with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write(script)
  print("wrote %s (%d bytes)" % (os.path.relpath(out, WORKSPACE), len(script)))



main()
