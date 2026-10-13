#!/usr/bin/env python3
"""Stage src/change_converter.lua to .tts/objects/ for the extension to push.

The Change Converter (GUID 305b4a) has no generated data -- it is hand-written
Lua. This tool exists anyway for two reasons:

  1. Ctrl+Alt+L wipes .tts/objects/ and refills it from the GAME, so a script
     edited in src/ but never pushed is silently reverted to whatever the bag
     last held. Putting the copy in master_sync.cmd means a sync always
     restores it, the same guarantee every generated script already has.
  2. TTS runs MoonSharp, which is Lua 5.2. The offline harness in tools/bin is
     Lua 5.4, so 5.3+ syntax passes every local test and fails only in game --
     an integer-division `//` shipped that way once. check_lua52() rejects it
     at build time instead.

Run: python tools/sync_change_converter.py
"""
import os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spawn_cells import staged_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "change_converter.lua")
WORKSPACE = os.path.dirname(ROOT)  # .tts/ sits at the VS Code workspace root
GUID = "305b4a"

#[[ Syntax MoonSharp (Lua 5.2) does not have. Each entry is a pattern and what
# to use instead. Checked against code only -- comments and strings are
# stripped first, since `//` appears in URLs and prose constantly.
LUA53_SYNTAX = [
  (r"//", "integer division -- use math.floor(a / b)"),
  (r"<<|>>", "bit shift -- not available"),
  (r"\bmath\.type\b", "math.type -- 5.3 only"),
  (r"\bmath\.tointeger\b", "math.tointeger -- use math.floor"),
  (r"\bgoto\b", "goto -- 5.2 has it but MoonSharp support is unreliable"),
]


def strip_noncode(text):
  """Blank out comments and string literals so a scan sees only code.

  Replaces with spaces rather than deleting, so reported line numbers stay
  correct.
  """
  out = []
  i, n = 0, len(text)
  while i < n:
    # long comment / long string: --[[ ]] or [[ ]]
    m = re.match(r"(--)?\[(=*)\[", text[i:])
    if m:
      close = "]" + m.group(2) + "]"
      end = text.find(close, i + m.end())
      end = n if end == -1 else end + len(close)
      out.append(re.sub(r"[^\n]", " ", text[i:end]))
      i = end
      continue
    if text.startswith("--", i):
      end = text.find("\n", i)
      end = n if end == -1 else end
      out.append(" " * (end - i))
      i = end
      continue
    if text[i] in "\"'":
      quote = text[i]
      j = i + 1
      while j < n and text[j] != quote:
        j += 2 if text[j] == "\\" else 1
      j = min(j + 1, n)
      out.append(re.sub(r"[^\n]", " ", text[i:j]))
      i = j
      continue
    out.append(text[i])
    i += 1
  return "".join(out)


def check_lua52(text, where):
  """Fail the build on syntax TTS cannot parse."""
  code = strip_noncode(text)
  bad = []
  for line_no, line in enumerate(code.split("\n"), 1):
    for pattern, why in LUA53_SYNTAX:
      if re.search(pattern, line):
        bad.append("  %s:%d  %s" % (where, line_no, why))
  if bad:
    raise SystemExit("Lua 5.3+ syntax -- MoonSharp is 5.2:\n"
                     + "\n".join(bad))


def check_all_sources():
  """Every script in src/ gets the 5.2 check, not just this one.

  The cost is a few file reads and the benefit is that the whole mod is
  covered by one build step, rather than each script waiting for its own
  staging tool to exist.
  """
  srcdir = os.path.join(ROOT, "src")
  for name in sorted(os.listdir(srcdir)):
    if not name.endswith(".lua"):
      continue
    path = os.path.join(srcdir, name)
    with open(path, encoding="utf-8") as f:
      check_lua52(f.read(), os.path.join("src", name))


def main():
  if not os.path.exists(SRC):
    raise SystemExit("missing %s" % os.path.relpath(SRC, ROOT))
  with open(SRC, encoding="utf-8") as f:
    script = f.read()

  check_all_sources()

  dest = staged_path(GUID)

  with open(dest, "w", encoding="utf-8", newline="\n") as f:
    f.write(script)
  print("wrote %s (%d bytes)"
        % (os.path.relpath(dest, WORKSPACE), len(script)))
  return 0


if __name__ == "__main__":
  sys.exit(main())
