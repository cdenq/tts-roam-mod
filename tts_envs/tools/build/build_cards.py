#!/usr/bin/env python3
"""Compose card fronts + backs around a gem, after assets/reference/City_*.png.

  data/asset_variables.csv  ->  assets/cards/<colour>_front.png
  (card rows)                   assets/cards/<colour>_back.png
  assets/gems/*.png             assets/cards/manifest.csv

Front: dark grunge ground, gradient band near the top with the gem on
it, a lighter text panel below. Back: same ground, band across the middle,
gem standing on it. Every `name=gem` pair in `card.gems` (`origin=ruby_heart1|...`,
gem names from build_gems.py, so run that first) gets one of each, named by
the pair's name.

Layout lengths are design units of a 750-wide card, scaled to `out_w`.
Deterministic: the grunge is seeded from the colour.

Not part of master_sync.cmd: art is rebuilt by hand, then uploaded by hand.

Run: python tools/build/build_cards.py           every gem in card.gems + every deck
     python tools/build/build_cards.py ruby      one card (others untouched)
"""
import csv, os, sys, zlib

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from datasets import ROOT, ASSET_VARS
import build_map_tiles as bm

import numpy as np
from PIL import Image

ASSETS = os.path.join(os.path.dirname(ROOT), "assets")
GEM_DIR = os.path.join(ASSETS, "gems")
OUT_DIR = os.path.join(ASSETS, "cards")
MANIFEST = os.path.join(OUT_DIR, "manifest.csv")
CARD_UNITS = 750.0
CARD_COLOURS = ("bg", "panel", "band_edge", "band_mid")
CARD_NUMBERS = ("bg_grunge", "panel_grunge", "vignette", "front_gem_y", "front_gem_long", "front_gem_max_h",
                "back_gem_y", "back_gem_long", "back_gem_max_h")
CARD_BOXES = {"panel_box": 4, "front_band": 2, "back_band": 2}


def die(msg):
  sys.exit("asset_variables.csv: " + msg)


# ---------------------------------------------------------------- config
def parse_card(raw):
  for k in ("out_w", "out_h", "seed_offset", "gems") + CARD_COLOURS + CARD_NUMBERS + tuple(CARD_BOXES):
    if k not in raw:
      die("card.%s is missing" % k)
  c = {}
  try:
    for k in ("out_w", "out_h", "seed_offset"):
      c[k] = int(raw[k])
    for k in CARD_COLOURS:
      c[k] = bm.hexrgb(raw[k])
    for k in CARD_NUMBERS:
      c[k] = float(raw[k])
    for k, n in CARD_BOXES.items():
      c[k] = [float(v) for v in raw[k].split("|")]
      if len(c[k]) != n:
        die("card.%s needs %d values separated by |" % (k, n))
  except ValueError as e:
    die("card: bad value %s" % e)
  return c


def parse_cards(raw, gems):
  """card.gems `origin=ruby_heart1|...` -> {card name: gem name}."""
  cards = {}
  for pair in (p.strip() for p in raw.split("|")):
    if not pair:
      continue
    name, sep, gem = (v.strip() for v in pair.partition("="))
    if not sep or not name or not gem:
      die("card.gems: %r is not name=gem" % pair)
    if gem not in gems:
      die("card.gems: unknown gem %r (names come from assets/gems/manifest.csv; run build_gems.py)" % gem)
    if name in cards:
      die("card.gems: %s is named twice" % name)
    cards[name] = gem
  if not cards:
    die("card.gems is empty")
  return cards


def add_deck_cards(cards, groups, gems):
  """One card per event deck, wearing the gem its maptile back wears."""
  for did, deck in bm.parse_decks({g: r for g, r in groups.items() if g.startswith("deck_")}).items():
    if did in cards:
      die("deck_%s: card.gems already has a card called %r" % (did, did))
    if deck["gem"] not in gems:
      die("deck_%s.gem: unknown gem %r (run build_gems.py?)" % (did, deck["gem"]))
    cards[did] = deck["gem"]
  return cards


def gem_names():
  path = os.path.join(GEM_DIR, "manifest.csv")
  if not os.path.exists(path):
    sys.exit("assets/gems/manifest.csv not found: run tools/build/build_gems.py first")
  with open(path, newline="", encoding="utf-8") as f:
    return {r["name"]: r for r in csv.DictReader(f)}


# ---------------------------------------------------------------- layers
def grunge(w, h, seed, amount):
  """Blotchy multiplier around 1: big soft stains, scratchy mid detail, fine grain."""
  side = max(w, h)
  stains = bm.fbm(side, seed, octaves=4, base=3)[:h, :w]
  scratches = bm.fbm(side, seed + 7, octaves=3, base=40)[:h, :w]
  grain = np.random.default_rng(seed + 1).random((h, w))
  return 1 + amount * ((stains - 0.5) * 1.4 + (scratches - 0.5) * 1.0 + (grain - 0.5) * 0.3)


def vignette(w, h, amount):
  yy, xx = np.mgrid[0:h, 0:w]
  r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
  return 1 - amount * (r2 / 2).clip(0, 1)


def band(a, card, y0, y1, u):
  """Full-width bar: dark at both edges, warm in the middle (smoothstep)."""
  w = a.shape[1]
  t = 1 - np.abs(np.linspace(-1, 1, w))
  t = t * t * (3 - 2 * t)
  edge, mid = np.array(card["band_edge"], float), np.array(card["band_mid"], float)
  row = edge + (mid - edge) * t[:, None]
  a[int(y0 * u):int(y1 * u)] = row[None]


def place_gem(img, gem_path, cy, long_side, max_h, u):
  """Crop the gem to its alpha box, scale its longer side (height capped at
  max_h), centre it at (card centre, cy). Never rotated."""
  gem = Image.open(gem_path).convert("RGBA")
  gem = gem.crop(gem.getchannel("A").getbbox())
  f = min(long_side / max(gem.size), max_h / gem.height) * u
  gem = gem.resize((max(1, round(gem.width * f)), max(1, round(gem.height * f))), Image.LANCZOS)
  img.alpha_composite(gem, (round(img.width / 2 - gem.width / 2), round(cy * u - gem.height / 2)))


def ground(card, seed):
  w, h = card["out_w"], card["out_h"]
  a = np.ones((h, w, 3)) * np.array(card["bg"], float)
  return a * (grunge(w, h, seed, card["bg_grunge"]) * vignette(w, h, card["vignette"]))[..., None]


def to_image(a):
  return Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert("RGBA")


def draw_front(card, gem_path, seed):
  u = card["out_w"] / CARD_UNITS
  a = ground(card, seed)
  x0, y0, x1, y1 = (int(v * u) for v in card["panel_box"])
  panel = np.array(card["panel"], float) * grunge(x1 - x0, y1 - y0, seed + 2, card["panel_grunge"])[..., None]
  a[y0:y1, x0:x1] = panel
  band(a, card, *card["front_band"], u)
  img = to_image(a)
  place_gem(img, gem_path, card["front_gem_y"], card["front_gem_long"], card["front_gem_max_h"], u)
  return img.convert("RGB")


def draw_back(card, gem_path, seed):
  u = card["out_w"] / CARD_UNITS
  a = ground(card, seed + 3)
  band(a, card, *card["back_band"], u)
  img = to_image(a)
  place_gem(img, gem_path, card["back_gem_y"], card["back_gem_long"], card["back_gem_max_h"], u)
  return img.convert("RGB")


# ---------------------------------------------------------------- build
def card_seed(card, name):
  # crc32 rather than hash(): stable across runs, so unchanged knobs = unchanged image
  return (zlib.crc32(("card|" + name).encode()) + bm.G["seed"] * 7919 + card["seed_offset"] * 104729) % (2 ** 31)


def read_manifest():
  if not os.path.exists(MANIFEST):
    return []
  with open(MANIFEST, newline="", encoding="utf-8") as f:
    return list(csv.DictReader(f))


def main():
  glob, groups = bm.load_config(ASSET_VARS, skip=())
  bm.setup(bm.parse_global(glob))
  card = parse_card(groups.get("card", {}))
  gems = gem_names()
  cards = add_deck_cards(parse_cards(groups.get("card", {}).get("gems", ""), gems), groups, gems)
  only = sys.argv[1:]
  for name in only:
    if name not in cards:
      sys.exit("unknown card %r (have: %s)" % (name, " ".join(cards)))
  todo = [c for c in cards if not only or c in only]
  os.makedirs(OUT_DIR, exist_ok=True)

  rows = []
  for name in todo:
    seed = card_seed(card, name)
    gem_path = os.path.join(GEM_DIR, gems[cards[name]]["file"])
    for side, draw in (("front", draw_front), ("back", draw_back)):
      file = "%s_%s.png" % (name, side)
      draw(card, gem_path, seed).save(os.path.join(OUT_DIR, file))
      rows.append({"name": "%s_%s" % (name, side), "card": name, "side": side, "gem": cards[name], "file": file})
    print("  " + name)

  # Merge with the previous manifest: untouched cards keep their rows; a
  # dropped card's files are deleted.
  rebuilt = set(todo)
  kept = []
  for old in read_manifest():
    if old["card"] in cards and old["card"] not in rebuilt:
      kept.append(old)
    elif old["card"] not in cards:
      stale = os.path.join(OUT_DIR, old["file"])
      if os.path.exists(stale):
        os.remove(stale)
        print("  removed stale " + old["file"])
  order = list(cards)
  rows = sorted(kept + rows, key=lambda r: (order.index(r["card"]), r["side"] != "front"))
  with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "card", "side", "gem", "file"])
    w.writeheader()
    w.writerows(rows)
  print("%d cards -> %s" % (len(todo), os.path.relpath(OUT_DIR, os.path.dirname(ROOT))))


if __name__ == "__main__":
  main()
