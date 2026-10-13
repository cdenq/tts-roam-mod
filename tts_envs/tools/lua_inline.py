"""Paste shared Lua from src/lib/ into an object script at sync time.

Object scripts cannot require() one another, and this repo does no bundling,
so shared code goes in the same way generated data does: the source script
carries an empty marker block, and the sync fills it.

  --[[ BEGIN SHARED template_import.lua -- do not edit ]]
  --[[ END SHARED template_import.lua ]]

The file named in the markers is read from src/lib/. Edit it there; the copy
in a staged script is overwritten on every sync.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "src", "lib")

BLOCK = re.compile(r"(--\[\[ BEGIN SHARED (\S+) -- do not edit \]\]\n)"
                   r".*?(--\[\[ END SHARED \2 \]\])", re.S)


def inline_shared(script):
  def fill(m):
    path = os.path.join(LIB, m.group(2))
    if not os.path.exists(path):
      sys.exit("shared Lua %s is missing from src/lib/" % m.group(2))
    with open(path, encoding="utf-8") as f:
      body = f.read().rstrip("\n")
    return m.group(1) + body + "\n" + m.group(3)
  return BLOCK.sub(fill, script)
