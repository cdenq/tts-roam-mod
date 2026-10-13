#!/usr/bin/env python3
"""Write master_reload.lua = the built Global script + a live-apply call.

Execute Code on master_reload.lua applies the current script to the LIVE world:
no Save and Play, no world reload, so hand-made changes to the table survive.
The trailing call defaults to onLoad(); pass another as argv[1].
"""
import io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
SCRIPT = os.path.join(WORKSPACE, ".tts", "objects", "Global.lua")
OUT = os.path.join(ROOT, "master_reload.lua")

tail = sys.argv[1] if len(sys.argv) > 1 else "onLoad()"
src = io.open(SCRIPT, encoding="utf-8").read()
io.open(OUT, "w", encoding="utf-8", newline="\n").write(
    src + "\n\n-- apply to the live table right now\n" + tail + "\n")
print("wrote %s (%d bytes), tail = %s" % (OUT, os.path.getsize(OUT), tail))
