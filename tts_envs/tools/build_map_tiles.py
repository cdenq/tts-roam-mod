#!/usr/bin/env python3
"""Draw the storybook overworld tiles described by data/asset_variables.csv.

Every tile is code-drawn: flat fills, ink outlines, hand wobble, paper grain.
All shapes go through one stamp() helper, which is what keeps the style from
drifting between tiles.

  data/asset_variables.csv   ->  assets/maptiles/<region>/<region>_<pattern>_<edges><n>_d<density>.png
  assets/gems/<back_gem>.png        assets/maptiles/backs/<region>_back.png
                                    assets/maptiles/manifest.csv

A path leaves a tile at the exact midpoint of each open edge, so neighbours
join up. Every DISTINCT rotation of a pattern is drawn as its own image, so a
tile is never rotated in TTS (which would also turn its shadows):

  pattern   orientations                     count
  none      -                                1
  deadend   N  E  S  W                       4
  corner    NE ES SW NW                      4
  straight  NS EW                            2
  tee       NES ESW NSW NEW                  4
  cross     NESW                             1

`variants` is the number of looks per orientation (forest_tee_NES1, _NES2..).

Density is how crowded the scatter is, in 5 stages (d1 sparse .. d5 dense).
Each stage scales the region's `spacing` by `global.density_scale`; a region
draws every stage listed in its `densities`. Seeds ignore density, so the
roads of forest_corner_ES1_d1 and _d5 are identical -- only the trees change.

The tile back is the region colour, a gem PNG from assets/gems/ and the name
on a ribbon in `global.back_font`.

Same CSV + same seed = byte-identical output, so a re-run only changes the
tiles whose knobs changed. Names never depend on how many variants exist,
so raising `variants` adds files without renaming old ones.

Not part of master_sync.cmd: art is rebuilt by hand, then uploaded by hand.

Run: python tools/build_map_tiles.py [--region R ..] [--shape S ..] [--density 1-4] [--variants N] [--prune]

  --region    regions to draw (default: every region in the CSV)
  --shape     back, none, deadend, corner, straight, tee, cross, or one
              orientation such as corner_ES (default: the region's patterns + back)
  --density   stages to draw: 3, 1-4 or 1|3|5 (default: the region's densities)
  --variants  looks per orientation, numbered 1..N (default: the region's variants)
  --prune     delete images the CSV (without these overrides) no longer describes

Flags only choose what to draw this run. Drawn images are added to / replace
their manifest rows; nothing else is touched unless --prune is given.
"""
import argparse, csv, math, os, re, sys, zlib

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasets import ROOT, ASSET_VARS

try:
  import numpy as np
  from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
except ImportError:
  sys.exit("build_map_tiles.py needs Pillow and numpy: pip install pillow numpy")

OUT_DIR = os.path.join(os.path.dirname(ROOT), "assets", "maptiles")
MANIFEST = os.path.join(OUT_DIR, "manifest.csv")
WORKSPACE = os.path.dirname(ROOT)
GEM_DIR = os.path.join(WORKSPACE, "assets", "gems")
DENSITY_STAGES = 5

PATTERNS = {
  "none": (),
  "deadend": ("N",),
  "corner": ("N", "E"),
  "straight": ("N", "S"),
  "tee": ("N", "E", "S"),
  "cross": ("N", "E", "S", "W"),
}
EDGE_ORDER = "NESW"


def orientations(pattern):
  """Distinct quarter-turn rotations of a pattern, each as edges in NESW order."""
  seen = []
  for k in range(4):
    turned = {EDGE_ORDER[(EDGE_ORDER.index(e) + k) % 4] for e in PATTERNS[pattern]}
    edges = tuple(e for e in EDGE_ORDER if e in turned)
    if edges not in seen:
      seen.append(edges)
  return seen


REGION_KEYS = ("variants", "patterns", "seed_offset", "ground", "deck",
               "densities", "clearing", "clearing_style", "spacing", "fields",
               "grass", "icons")
GLOBAL_COLOURS = ("ink", "frame", "paper", "path", "path_pebble", "clearing",
                  "cobble", "cobble_line", "grass", "trunk", "leaf", "leaf_dk",
                  "leaf_lt", "pine", "pine_dk", "bush", "rock_lt", "rock_dk",
                  "snow", "wall", "wall_dk", "window", "field_lt", "palisade", "palisade_dk",
                  "guild_roof", "guild_roof_dk", "stone", "stone_dk", "timber", "banner", "banner_lt",
                  "water", "water_dk", "water_lt", "reed", "cattail", "blossom", "blossom_dk",
                  "blossom_lt", "oak", "oak_dk", "oak_lt", "fruit", "heather", "heather_dk", "heather_lt",
                  "deadwood", "charred", "stump_top", "cap", "cap_dk", "stem", "hill", "hill_dk",
                  "hill_lt", "hay", "hay_dk", "statue", "statue_dk", "statue_lt",
                  "gnarl_bark", "gnarl_bark_dk", "gnarl_leaf", "gnarl_leaf_dk", "gnarl_leaf_lt", "moss", "glow",
                  "chasm", "chasm_wall", "spring", "spring_dk", "mud", "mud_dk", "briar", "briar_dk",
                  "berry", "cat_banner", "bird_banner", "foam")
GLOBAL_LISTS = ("roofs", "fields", "flower_colours")
# Region keys that may be left out; the default reproduces an unwalled region.
OPTIONAL_REGION_KEYS = {"town_radius": "0", "wall": "none", "outer_icons": "", "outer_spacing": "",
                        "centerpiece": "none", "centerpiece_size": "0",
                        "feature": "none", "speckle": "", "layout": "scatter", "required": ""}
WALLS = ("none", "palisade", "menhirs")
CENTERPIECES = ("none", "guildhall", "windmill", "statue")
# how far north of the plaza centre a centerpiece's base sits, as a fraction of
# the clearing radius -- the statue stands back so tokens fit in front of it
CENTERPIECE_SETBACK = {"guildhall": 0.3, "windmill": 0.3, "statue": 0.55}
# area the scatter keeps clear, as (half-width, height) fractions of centerpiece_size
CENTERPIECE_BOX = {"guildhall": (0.56, 0.66), "windmill": (0.56, 0.66), "statue": (0.42, 1.12)}
FEATURES = ("none", "river", "pools", "pit", "lake", "canyon", "falls", "mud", "springs")
LAYOUTS = ("scatter", "rows")
GLOBAL_STRINGS = ("back_font",)
GLOBAL_NUMBER_LISTS = ("density_scale",)
# Feature + wall tuning. Numbers are design units unless named *_count.
GLOBAL_FEATURE_NUMBERS = ("river_anchor", "river_width", "canyon_width", "pool_count", "mud_count", "spring_count",
                          "menhir_spacing", "stake_spacing")
# "lo-hi" pairs
GLOBAL_RANGES = ("lake_size", "falls_size", "pit_size", "pool_size", "mud_size", "spring_size",
                 "menhir_size", "stake_size", "field_width", "field_height", "reed_size")
# Groups in asset_variables.csv that belong to other generators, not regions.
OTHER_GROUPS = ("gem", "gem_colour", "landmark", "landmark_size", "landmark_colour", "card")
GLOBAL_NUMBERS = ("out_size", "supersample", "seed", "frame_width", "paper_tint", "back_gem_size",
                  "paper_grain", "vignette", "path_width", "path_wobble")

# Set by setup() from the CSV. Every length in this file is in DESIGN units
# (a tile is 1024 wide); u() converts to canvas pixels.
G = {}
R = 1024
U = 1.0
PAD = 32


def u(v):
  return v * U


def die(msg):
  sys.exit("asset_variables.csv: " + msg)


def hexrgb(h):
  h = h.strip().lstrip("#")
  if len(h) != 6:
    raise ValueError(h)
  return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- config
def load_config(path, skip=OTHER_GROUPS):
  glob, regions = {}, {}
  with open(path, newline="", encoding="utf-8-sig") as f:
    for n, row in enumerate(csv.DictReader(f), start=2):
      group = (row.get("group") or "").strip()
      key = (row.get("key") or "").strip()
      if not group or not key or group.startswith("#") or group in skip:
        continue
      target = glob if group == "global" else regions.setdefault(group, {})
      if key in target:
        die("line %d: %s.%s is set twice" % (n, group, key))
      target[key] = (row.get("value") or "").strip()
  return glob, regions


def parse_global(raw):
  g = {}
  for k in (GLOBAL_COLOURS + GLOBAL_LISTS + GLOBAL_STRINGS + GLOBAL_NUMBER_LISTS + GLOBAL_NUMBERS
            + GLOBAL_FEATURE_NUMBERS + GLOBAL_RANGES):
    if k not in raw:
      die("global.%s is missing" % k)
  try:
    for k in GLOBAL_COLOURS:
      g[k] = hexrgb(raw[k])
    for k in GLOBAL_LISTS:
      g[k] = [hexrgb(c) for c in raw[k].split("|") if c.strip()]
    for k in GLOBAL_NUMBERS:
      g[k] = float(raw[k])
    for k in GLOBAL_NUMBER_LISTS:
      g[k] = [float(v) for v in raw[k].split("|") if v.strip()]
    for k in GLOBAL_FEATURE_NUMBERS:
      g[k] = float(raw[k])
    for k in GLOBAL_RANGES:
      lo, hi = (float(v) for v in raw[k].split("-"))
      if lo > hi:
        die("global.%s: %s is not lo-hi" % (k, raw[k]))
      g[k] = (lo, hi)
  except ValueError as e:
    die("global: bad value %s" % e)
  for k in ("pool_count", "mud_count", "spring_count"):
    g[k] = int(g[k])
  for k in ("out_size", "supersample", "seed"):
    g[k] = int(g[k])
  if len(g["density_scale"]) != DENSITY_STAGES:
    die("global.density_scale needs %d values (d1..d%d), got %d"
        % (DENSITY_STAGES, DENSITY_STAGES, len(g["density_scale"])))
  # relative to the repo root, so the font can ship with the repo
  g["back_font"] = os.path.join(WORKSPACE, raw["back_font"])
  if not os.path.exists(g["back_font"]):
    die("global.back_font: %s not found" % raw["back_font"])
  return g


def parse_stages(name, cell):
  """'1-5', '3' or '1|3|5' -> sorted unique stage numbers."""
  stages = set()
  for part in cell.split("|"):
    part = part.strip()
    try:
      lo, _, hi = part.partition("-")
      lo, hi = int(lo), int(hi or lo)
    except ValueError:
      die("%s.densities: %r is not a stage, range (1-5) or list (1|3|5)" % (name, cell))
    stages.update(range(lo, hi + 1))
  if not stages or min(stages) < 1 or max(stages) > DENSITY_STAGES:
    die("%s.densities: stages run 1-%d, got %r" % (name, DENSITY_STAGES, cell))
  return sorted(stages)


def parse_region(name, raw):
  for k in REGION_KEYS:
    if k not in raw:
      die("%s.%s is missing" % (name, k))
  r = {"name": name}
  try:
    r["variants"] = int(raw["variants"])
    r["seed_offset"] = int(raw["seed_offset"])
    r["ground"] = hexrgb(raw["ground"])
    r["clearing"] = float(raw["clearing"])
    r["spacing"] = float(raw["spacing"])
    r["fields"] = int(raw["fields"])
    r["grass"] = int(raw["grass"])
  except ValueError as e:
    die("%s: bad value %s" % (name, e))
  r["patterns"] = [p.strip() for p in raw["patterns"].split("|") if p.strip()]
  for p in r["patterns"]:
    if p not in PATTERNS:
      die("%s.patterns: unknown %r (use %s)" % (name, p, " ".join(PATTERNS)))
  r["deck"] = raw["deck"]  # checked against the deck_<id> groups in main()
  r["densities"] = parse_stages(name, raw["densities"])
  if raw["clearing_style"] not in ("plain", "cobble"):
    die("%s.clearing_style must be plain or cobble" % name)
  r["clearing_style"] = raw["clearing_style"]
  r["icons"] = parse_icons(name, "icons", raw["icons"])
  if not r["icons"]:
    die("%s.icons is empty" % name)
  opt = dict(OPTIONAL_REGION_KEYS, **{k: v for k, v in raw.items() if k in OPTIONAL_REGION_KEYS and v})
  try:
    r["town_radius"] = float(opt["town_radius"])
    r["outer_spacing"] = float(opt["outer_spacing"] or raw["spacing"])
  except ValueError as e:
    die("%s: bad value %s" % (name, e))
  if opt["wall"] not in WALLS:
    die("%s.wall: unknown %r (use %s)" % (name, opt["wall"], " ".join(WALLS)))
  r["wall"] = opt["wall"]
  if opt["centerpiece"] not in CENTERPIECES:
    die("%s.centerpiece: unknown %r (use %s)" % (name, opt["centerpiece"], " ".join(CENTERPIECES)))
  r["centerpiece"] = opt["centerpiece"]
  try:
    r["centerpiece_size"] = float(opt["centerpiece_size"])
  except ValueError as e:
    die("%s: bad value %s" % (name, e))
  if r["centerpiece"] != "none" and r["centerpiece_size"] <= 0:
    die("%s: centerpiece needs a centerpiece_size" % name)
  for key, allowed in (("feature", FEATURES), ("layout", LAYOUTS)):
    if opt[key] not in allowed:
      die("%s.%s: unknown %r (use %s)" % (name, key, opt[key], " ".join(allowed)))
    r[key] = opt[key]
  r["speckle"] = []
  for part in opt["speckle"].split("|"):
    if not part.strip():
      continue
    try:
      colour, count = part.split(":")
      r["speckle"].append((hexrgb(colour), int(count)))
    except ValueError:
      die("%s.speckle: %r is not #colour:count" % (name, part))
  r["outer_icons"] = parse_icons(name, "outer_icons", opt["outer_icons"])
  # same grammar as icons, but the middle number is a COUNT that is guaranteed
  r["required"] = [(painter, int(count), lo, hi)
                   for painter, count, lo, hi in parse_icons(name, "required", opt["required"])]
  if (r["wall"] != "none" or r["outer_icons"]) and r["town_radius"] <= r["clearing"]:
    die("%s: a wall or outer_icons needs town_radius larger than clearing" % name)
  return r


def parse_icons(name, key, cell):
  """'tree:6:85-115|pine:3:90-120' -> [(painter, weight, lo, hi)]."""
  icons = []
  for part in cell.split("|"):
    if not part.strip():
      continue
    try:
      painter, weight, sizes = part.strip().split(":")
      lo, hi = (float(v) for v in sizes.split("-"))
      weight = float(weight)
    except ValueError:
      die("%s.%s: %r is not painter:weight:lo-hi" % (name, key, part))
    if painter not in PAINTERS:
      die("%s.%s: unknown painter %r (use %s)" % (name, key, painter, " ".join(PAINTERS)))
    icons.append((painter, weight, lo, hi))
  return icons


def setup(g):
  global G, R, U, PAD
  G = g
  R = g["out_size"] * g["supersample"]
  U = R / 1024.0
  PAD = int(u(32))


# ---------------------------------------------------------------- noise
def fbm(size, seed, octaves=5, base=3, persist=0.5):
  rng = np.random.default_rng(seed)
  out = np.zeros((size, size))
  amp, total = 1.0, 0.0
  for o in range(octaves):
    n = base * 2 ** o + 1
    g = (rng.random((n, n)) * 255).astype(np.uint8)
    out += amp * np.asarray(Image.fromarray(g).resize((size, size), Image.BICUBIC)) / 255.0
    total += amp
    amp *= persist
  out /= total
  return (out - out.min()) / (out.max() - out.min() + 1e-9)


# ---------------------------------------------------------------- stamping
def ink_ring(mask):
  """Grow a mask by the ink width. Separable max: Pillow's MaxFilter is
  quadratic in the kernel size and was 80% of the run time."""
  r = max(1, int(u(4.5)))
  a = np.asarray(mask)
  h, w = a.shape
  p = np.pad(a, ((0, 0), (r, r)))
  out = p[:, 0:w].copy()
  for k in range(1, 2 * r + 1):
    np.maximum(out, p[:, k:k + w], out=out)
  p = np.pad(out, ((r, r), (0, 0)))
  out = p[0:h].copy()
  for k in range(1, 2 * r + 1):
    np.maximum(out, p[k:k + h], out=out)
  return Image.fromarray(out)


def stamp(canvas, mask, x, y, fill, shade=None, light=None):
  """Ink ring, flat fill, bottom-right shade crescent, top-left light crescent."""
  w, h = mask.size
  box = (int(x), int(y), int(x) + w, int(y) + h)
  canvas.paste(G["ink"], box, ink_ring(mask))
  canvas.paste(fill, box, mask)
  if shade:
    canvas.paste(shade, box, ImageChops.subtract(mask, ImageChops.offset(mask, -int(u(14)), -int(u(12)))))
  if light:
    cres = ImageChops.subtract(mask, ImageChops.offset(mask, int(u(12)), int(u(12))))
    canvas.paste(light, box, ImageChops.multiply(cres, ImageChops.offset(mask, -int(u(6)), -int(u(6)))))


def blank(w, h):
  return Image.new("L", (int(w) + 2 * PAD, int(h) + 2 * PAD), 0)


def wobble(pts, rng, amp, sub=4):
  """Subdivide each edge and nudge the points sideways: the hand-drawn look."""
  out = []
  for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
    nx, ny = y1 - y0, x0 - x1
    ln = math.hypot(nx, ny) or 1
    for k in range(sub):
      t = k / sub
      j = rng.normal(0, u(amp)) if k else 0
      out.append((x0 + (x1 - x0) * t + nx / ln * j, y0 + (y1 - y0) * t + ny / ln * j))
  return out


def shade_of(c, f):
  return tuple(int(v * f) for v in c)


# ---------------------------------------------------------------- painters
# Each draws one icon whose BASE sits at (ax, ay). s is the icon size in px.
def _tree(canvas, ax, ay, s, rng, fill, dk, lt, trunk=0.08, dots=None):
  w, h = s * 1.2, s * 1.5
  cx, by = PAD + w / 2, PAD + h
  trunk_m = blank(w, h)
  ImageDraw.Draw(trunk_m).rectangle([cx - s * trunk, by - s * 0.5, cx + s * trunk, by], fill=255)
  can = blank(w, h)
  d = ImageDraw.Draw(can)
  ccx, ccy, r = cx, by - s * 0.9, s * 0.5
  d.ellipse([ccx - r * 0.75, ccy - r * 0.75, ccx + r * 0.75, ccy + r * 0.75], fill=255)
  n = int(rng.integers(6, 9))
  for k in range(n):
    a = 2 * math.pi * k / n + rng.normal(0, 0.15)
    rr = r * rng.uniform(0.36, 0.46)
    px, py = ccx + math.cos(a) * r * 0.55, ccy + math.sin(a) * r * 0.5
    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, trunk_m, ox, oy, G["trunk"])
  stamp(canvas, can, ox, oy, fill, dk, lt)
  dc = ImageDraw.Draw(canvas)
  for _ in range(3):
    tx, ty = ccx + ox + rng.uniform(-r * 0.5, r * 0.4), ccy + oy + rng.uniform(-r * 0.4, r * 0.4)
    dc.arc([tx - u(14), ty - u(10), tx + u(14), ty + u(10)], 200, 340, fill=G["ink"], width=max(1, int(u(4))))
  if dots:
    for _ in range(6):
      tx, ty = ccx + ox + rng.uniform(-r * 0.6, r * 0.6), ccy + oy + rng.uniform(-r * 0.45, r * 0.45)
      e = u(7)
      dc.ellipse([tx - e, ty - e, tx + e, ty + e], fill=dots, outline=G["ink"], width=max(1, int(u(2.5))))


def paint_tree(canvas, ax, ay, s, rng):
  _tree(canvas, ax, ay, s, rng, G["leaf"], G["leaf_dk"], G["leaf_lt"])


def paint_blossom(canvas, ax, ay, s, rng):
  _tree(canvas, ax, ay, s, rng, G["blossom"], G["blossom_dk"], G["blossom_lt"])


def paint_fruit(canvas, ax, ay, s, rng):
  _tree(canvas, ax, ay, s, rng, G["leaf"], G["leaf_dk"], G["leaf_lt"], dots=G["fruit"])


def paint_oak(canvas, ax, ay, s, rng):
  """Deepwood giant: darker, heavier trunk."""
  _tree(canvas, ax, ay, s, rng, G["oak"], G["oak_dk"], G["oak_lt"], trunk=0.13)


def paint_pine(canvas, ax, ay, s, rng):
  w, h = s * 0.9, s * 1.7
  cx, by = PAD + w / 2, PAD + h
  trunk = blank(w, h)
  ImageDraw.Draw(trunk).rectangle([cx - s * 0.07, by - s * 0.35, cx + s * 0.07, by], fill=255)
  m = blank(w, h)
  d = ImageDraw.Draw(m)
  for i in range(3):
    top = by - s * 1.65 + i * s * 0.38
    half = s * (0.25 + 0.12 * i)
    d.polygon(wobble([(cx, top), (cx + half, top + s * 0.62), (cx - half, top + s * 0.62)], rng, 3), fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, trunk, ox, oy, G["trunk"])
  stamp(canvas, m, ox, oy, G["pine"], G["pine_dk"])


def _bush(canvas, ax, ay, s, rng, fill, dk, lt):
  w, h = s * 1.1, s * 0.7
  cx, by = PAD + w / 2, PAD + h
  m = blank(w, h)
  d = ImageDraw.Draw(m)
  for k in range(4):
    rr = s * rng.uniform(0.2, 0.28)
    px = cx + (k - 1.5) * s * 0.2
    py = by - rr - rng.uniform(0, s * 0.12)
    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
  stamp(canvas, m, ax - cx, ay - by, fill, dk, lt)


def paint_bush(canvas, ax, ay, s, rng):
  _bush(canvas, ax, ay, s, rng, G["bush"], G["leaf_dk"], G["leaf_lt"])


def paint_heather(canvas, ax, ay, s, rng):
  _bush(canvas, ax, ay, s, rng, G["heather"], G["heather_dk"], G["heather_lt"])
  dc = ImageDraw.Draw(canvas)
  for _ in range(5):  # flower spikes
    x = ax + rng.uniform(-s * 0.35, s * 0.35)
    y = ay - s * rng.uniform(0.35, 0.55)
    dc.line([(x, y), (x, y - u(10))], fill=G["heather_lt"], width=max(1, int(u(4))))


def _local(s_w, s_h):
  """Mask canvas + base point for a painter whose box is s_w x s_h px."""
  return blank(s_w, s_h), PAD + s_w / 2, PAD + s_h


def _mask_poly(w, h, pts, rng, amp=1.5, sub=3):
  m = blank(w, h)
  ImageDraw.Draw(m).polygon(wobble(pts, rng, amp, sub=sub), fill=255)
  return m


def _ink_line(canvas, pts, colour, width):
  """A line with an ink edge: ink first, colour on top."""
  d = ImageDraw.Draw(canvas)
  d.line(pts, fill=G["ink"], width=int(width + u(6)), joint="curve")
  d.line(pts, fill=colour, width=int(width), joint="curve")


def _dead(canvas, ax, ay, s, rng, colour):
  w, h = s * 0.9, s * 1.15
  cx, by = PAD + w / 2, PAD + h
  m = blank(w, h)
  d = ImageDraw.Draw(m)
  lean = rng.uniform(-0.04, 0.04) * s
  d.polygon(wobble([(cx - s * 0.09, by), (cx - s * 0.05 + lean, by - s * 0.75), (cx - s * 0.015 + lean, by - s * 1.08),
                    (cx + s * 0.035 + lean, by - s * 0.78), (cx + s * 0.085, by)], rng, 1.5, sub=2), fill=255)
  for side, y0, reach in ((-1, 0.55, 0.36), (1, 0.42, 0.32), (-1, 0.82, 0.2)):
    yb = by - s * y0
    tip = (cx + side * s * reach + lean, yb - s * 0.3)
    d.polygon([(cx + lean, yb + s * 0.04), tip, (cx + lean, yb - s * 0.06)], fill=255)
    d.line([tip, (tip[0] + side * s * 0.08, tip[1] - s * 0.1)], fill=255, width=max(2, int(s * 0.03)))
  stamp(canvas, m, ax - cx, ay - by, colour, shade_of(colour, 0.7))


def paint_deadtree(canvas, ax, ay, s, rng):
  _dead(canvas, ax, ay, s, rng, G["deadwood"])


def paint_charred(canvas, ax, ay, s, rng):
  _dead(canvas, ax, ay, s, rng, G["charred"])


def paint_stump(canvas, ax, ay, s, rng):
  w, h = s * 1.1, s * 0.8
  cx, by = PAD + w / 2, PAD + h
  m = blank(w, h)
  d = ImageDraw.Draw(m)
  rw, top = s * 0.38, by - s * 0.42
  d.rectangle([cx - rw, top, cx + rw, by - s * 0.06], fill=255)
  d.ellipse([cx - rw, by - s * 0.14, cx + rw, by], fill=255)
  for side in (-1, 1):  # root flare
    d.polygon([(cx + side * rw, by - s * 0.2), (cx + side * (rw + s * 0.14), by - s * 0.02), (cx + side * rw * 0.5, by - s * 0.04)], fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["trunk"], shade_of(G["trunk"], 0.72))
  t = blank(w, h)
  ImageDraw.Draw(t).ellipse([cx - rw, top - s * 0.12, cx + rw, top + s * 0.12], fill=255)
  stamp(canvas, t, ox, oy, G["stump_top"])
  dc = ImageDraw.Draw(canvas)
  for f in (0.55, 0.25):
    dc.ellipse([cx + ox - rw * f, top + oy - s * 0.12 * f, cx + ox + rw * f, top + oy + s * 0.12 * f],
               outline=shade_of(G["stump_top"], 0.7), width=max(1, int(u(3))))


def paint_rock(canvas, ax, ay, s, rng):
  w, h = s * 1.3, s * 0.8
  cx, by = PAD + w / 2, PAD + h
  n = 7
  pts = [(cx + math.cos(math.pi + math.pi * k / (n - 1)) * s * 0.6 * rng.uniform(0.85, 1.1),
          by + math.sin(math.pi + math.pi * k / (n - 1)) * s * 0.62 * rng.uniform(0.75, 1.1)) for k in range(n)]
  m = blank(w, h)
  ImageDraw.Draw(m).polygon(pts, fill=255)
  stamp(canvas, m, ax - cx, ay - by, G["rock_lt"], G["rock_dk"])


def paint_hill(canvas, ax, ay, s, rng):
  w, h = s * 1.9, s * 0.8
  cx, by = PAD + w / 2, PAD + h
  n = 14
  pts = [(cx + math.cos(math.pi + math.pi * k / (n - 1)) * s * 0.92,
          by + math.sin(math.pi + math.pi * k / (n - 1)) * s * 0.62 * rng.uniform(0.92, 1.05)) for k in range(n)]
  m = blank(w, h)
  ImageDraw.Draw(m).polygon(pts, fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["hill"], G["hill_dk"], G["hill_lt"])
  dc = ImageDraw.Draw(canvas)
  for _ in range(3):
    x, y = ax + rng.uniform(-s * 0.45, s * 0.35), ay - s * rng.uniform(0.15, 0.4)
    for k in range(3):
      dc.line([(x + k * u(9), y), (x + k * u(9) + (k - 1) * u(4), y - u(13))], fill=G["hill_dk"], width=max(1, int(u(3))))


def paint_reeds(canvas, ax, ay, s, rng):
  dc = ImageDraw.Draw(canvas)
  n = int(rng.integers(4, 7))
  for k in range(n):
    x = ax + (k - (n - 1) / 2) * s * 0.12 + rng.uniform(-s * 0.03, s * 0.03)
    top = (x + rng.uniform(-s * 0.15, s * 0.15), ay - s * rng.uniform(0.6, 1.0))
    _ink_line(canvas, [(x, ay), top], G["reed"], u(4))
    if k % 2 == 0:
      e, f = u(6), u(14)
      dc.ellipse([top[0] - e - u(3), top[1] - u(3), top[0] + e + u(3), top[1] + 2 * f + u(3)], fill=G["ink"])
      dc.ellipse([top[0] - e, top[1], top[0] + e, top[1] + 2 * f], fill=G["cattail"])


def paint_mushroom(canvas, ax, ay, s, rng):
  w, h = s * 1.1, s * 1.05
  cx, by = PAD + w / 2, PAD + h
  stem = _mask_poly(w, h, [(cx - s * 0.12, by), (cx - s * 0.085, by - s * 0.6), (cx + s * 0.085, by - s * 0.6),
                           (cx + s * 0.12, by)], rng, amp=1)
  ox, oy = ax - cx, ay - by
  stamp(canvas, stem, ox, oy, G["stem"], shade_of(G["stem"], 0.84))
  cy, rx, ry = by - s * 0.56, s * 0.46, s * 0.4
  pts = [(cx + math.cos(math.pi + math.pi * k / 15) * rx, cy + math.sin(math.pi + math.pi * k / 15) * ry) for k in range(16)]
  pts += [(cx + rx * 0.7, cy + s * 0.05), (cx - rx * 0.7, cy + s * 0.05)]
  cap = _mask_poly(w, h, pts, rng, amp=1.5, sub=2)
  stamp(canvas, cap, ox, oy, G["cap"], G["cap_dk"], tuple(min(255, int(c * 1.25)) for c in G["cap"]))
  dc = ImageDraw.Draw(canvas)
  for _ in range(5):
    a = rng.uniform(math.pi * 1.15, math.pi * 1.85)
    rr = rng.uniform(0.3, 0.75)
    x, y = cx + ox + math.cos(a) * rx * rr, cy + oy + math.sin(a) * ry * rr
    e = s * rng.uniform(0.035, 0.06)
    dc.ellipse([x - e, y - e * 0.8, x + e, y + e * 0.8], fill=G["stem"])


def paint_ruinwall(canvas, ax, ay, s, rng):
  w, h = s * 1.4, s * 0.75
  cx, by = PAD + w / 2, PAD + h
  half = s * 0.6
  steps = 6
  top = [(cx - half + half * 2 * k / steps, by - s * rng.uniform(0.22, 0.62)) for k in range(steps + 1)]
  ragged = []
  for i, (x, y) in enumerate(top):
    ragged.append((x, y))
    if i < steps:
      ragged.append((x + half * 2 / steps * 0.5, top[i][1] if rng.random() < 0.5 else top[i + 1][1]))
  m = blank(w, h)
  ImageDraw.Draw(m).polygon([(cx - half, by)] + ragged + [(cx + half, by)], fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["stone"], G["stone_dk"])
  bricks = blank(w, h)
  db = ImageDraw.Draw(bricks)
  row = s * 0.1
  for i in range(1, 7):
    y = by - i * row
    db.line([(cx - half, y), (cx + half, y)], fill=255, width=max(1, int(u(3))))
    for j in range(-6, 7):
      x = cx + j * s * 0.13 + (s * 0.065 if i % 2 else 0)
      db.line([(x, y), (x, y + row)], fill=255, width=max(1, int(u(3))))
  inner = m.filter(ImageFilter.MinFilter(5))
  canvas.paste(G["stone_dk"], (int(ox), int(oy), int(ox) + m.size[0], int(oy) + m.size[1]),
               ImageChops.multiply(bricks, inner))
  for _ in range(2):  # ivy
    x, y = top[int(rng.integers(0, len(top)))]
    _bush(canvas, x + ox, y + oy + s * 0.12, s * 0.35, rng, G["leaf"], G["leaf_dk"], G["leaf_lt"])


def paint_column(canvas, ax, ay, s, rng):
  w, h = s * 0.6, s * 1.1
  cx, by = PAD + w / 2, PAD + h
  ox, oy = ax - cx, ay - by
  height = s * rng.uniform(0.5, 1.0)
  broken = height < s * 0.85
  base = blank(w, h)
  ImageDraw.Draw(base).rectangle([cx - s * 0.17, by - s * 0.08, cx + s * 0.17, by], fill=255)
  sw = s * 0.11
  if broken:
    shaft_pts = [(cx - sw, by - s * 0.07), (cx - sw, by - height), (cx - sw * 0.2, by - height + s * 0.08),
                 (cx + sw * 0.4, by - height - s * 0.05), (cx + sw, by - height + s * 0.03), (cx + sw, by - s * 0.07)]
  else:
    shaft_pts = [(cx - sw, by - s * 0.07), (cx - sw, by - height), (cx + sw, by - height), (cx + sw, by - s * 0.07)]
  shaft = _mask_poly(w, h, shaft_pts, rng, amp=0.8, sub=2)
  stamp(canvas, shaft, ox, oy, G["stone"], G["stone_dk"])
  if not broken:
    cap_m = blank(w, h)
    ImageDraw.Draw(cap_m).rectangle([cx - s * 0.16, by - height - s * 0.07, cx + s * 0.16, by - height + s * 0.01], fill=255)
    stamp(canvas, cap_m, ox, oy, G["stone"], G["stone_dk"])
  stamp(canvas, base, ox, oy, G["stone"], G["stone_dk"])
  dc = ImageDraw.Draw(canvas)
  for f in (-0.4, 0.4):
    dc.line([(cx + ox + sw * f, by + oy - s * 0.1), (cx + ox + sw * f, by + oy - height + s * 0.1)],
            fill=G["stone_dk"], width=max(1, int(u(3))))


def paint_crane(canvas, ax, ay, s, rng):
  """Quarry derrick: A-frame, boom, rope, hanging stone."""
  beam = u(7)
  apex = (ax - s * 0.05, ay - s * 0.9)
  for foot in ((ax - s * 0.28, ay), (ax + s * 0.12, ay)):
    _ink_line(canvas, [foot, apex], G["timber"], beam)
  _ink_line(canvas, [(ax - s * 0.22, ay - s * 0.3), (ax + s * 0.08, ay - s * 0.3)], G["timber"], beam * 0.8)
  tip = (ax + s * 0.5, ay - s * 0.98)
  _ink_line(canvas, [(ax - s * 0.06, ay - s * 0.72), tip], G["timber"], beam)
  dc = ImageDraw.Draw(canvas)
  dc.line([tip, (tip[0], ay - s * 0.45)], fill=G["ink"], width=max(1, int(u(3))))
  bw = s * 0.1
  m = blank(bw * 2, bw * 2)
  ImageDraw.Draw(m).rectangle([PAD, PAD, PAD + bw * 2, PAD + bw * 1.5], fill=255)
  stamp(canvas, m, tip[0] - bw - PAD, ay - s * 0.45 - PAD, G["stone"], G["stone_dk"])


def paint_logpile(canvas, ax, ay, s, rng):
  rr = s * 0.13
  dc = ImageDraw.Draw(canvas)
  for row, count in enumerate((3, 2, 1)):
    for k in range(count):
      x = ax + (k - (count - 1) / 2) * rr * 2.05
      y = ay - rr - row * rr * 1.75
      m = blank(rr * 2, rr * 2)
      ImageDraw.Draw(m).ellipse([PAD, PAD, PAD + rr * 2, PAD + rr * 2], fill=255)
      stamp(canvas, m, x - rr - PAD, y - rr - PAD, G["stump_top"], shade_of(G["stump_top"], 0.8))
      for f in (0.6, 0.3):
        dc.ellipse([x - rr * f, y - rr * f, x + rr * f, y + rr * f], outline=shade_of(G["stump_top"], 0.65),
                   width=max(1, int(u(2.5))))


def paint_haystack(canvas, ax, ay, s, rng):
  w, h = s * 1.0, s * 0.85
  cx, by = PAD + w / 2, PAD + h
  pts = [(cx + math.cos(math.pi + math.pi * k / 13) * s * 0.45,
          by + math.sin(math.pi + math.pi * k / 13) * s * 0.75) for k in range(14)]
  m = _mask_poly(w, h, pts, rng, amp=2, sub=2)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["hay"], G["hay_dk"], tuple(min(255, int(c * 1.12)) for c in G["hay"]))
  dc = ImageDraw.Draw(canvas)
  for _ in range(7):
    x, y = ax + rng.uniform(-s * 0.3, s * 0.3), ay - s * rng.uniform(0.1, 0.55)
    dc.line([(x, y), (x + rng.uniform(-u(6), u(6)), y - u(14))], fill=G["hay_dk"], width=max(1, int(u(3))))


def paint_briar(canvas, ax, ay, s, rng):
  """Bramble mound: lumpy dark mass, curling thorny tendrils, red berries."""
  w, h = s * 1.4, s * 0.85
  cx, by = PAD + w / 2, PAD + h
  m = blank(w, h)
  d = ImageDraw.Draw(m)
  for k in range(6):
    rr = s * rng.uniform(0.17, 0.26)
    px = cx + (k - 2.5) * s * 0.16 + rng.uniform(-s * 0.04, s * 0.04)
    py = by - rr - rng.uniform(0, s * 0.2)
    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["briar"], G["briar_dk"], shade_of(G["briar"], 1.25))
  dc = ImageDraw.Draw(canvas)
  lw = max(1, int(u(3.5)))
  for _ in range(5):  # tendrils with thorn ticks
    x, y = ax + rng.uniform(-s * 0.55, s * 0.55), ay - s * rng.uniform(0.25, 0.6)
    r = s * rng.uniform(0.1, 0.18)
    a0 = rng.uniform(0, 360)
    dc.arc([x - r, y - r, x + r, y + r], a0, a0 + 230, fill=G["ink"], width=lw)
    for t in (0.3, 0.6, 0.9):
      a = math.radians(a0 + 230 * t)
      px, py = x + math.cos(a) * r, y + math.sin(a) * r
      dc.line([(px, py), (px + math.cos(a) * u(9), py + math.sin(a) * u(9))], fill=G["ink"], width=lw)
  for _ in range(int(rng.integers(4, 7))):
    x, y = ax + rng.uniform(-s * 0.45, s * 0.45), ay - s * rng.uniform(0.15, 0.55)
    e = u(6)
    dc.ellipse([x - e, y - e, x + e, y + e], fill=G["berry"], outline=G["ink"], width=max(1, int(u(2.5))))


def paint_flowers(canvas, ax, ay, s, rng):
  """A clump of wildflowers: stems, leaves, round heads with a yellow eye."""
  dc = ImageDraw.Draw(canvas)
  colour = G["flower_colours"][int(rng.integers(0, len(G["flower_colours"])))]
  n = int(rng.integers(4, 8))
  for k in range(n):
    x = ax + (k - (n - 1) / 2) * s * 0.13 + rng.uniform(-s * 0.04, s * 0.04)
    top = (x + rng.uniform(-s * 0.1, s * 0.1), ay - s * rng.uniform(0.4, 0.85))
    _ink_line(canvas, [(x, ay), top], G["leaf"], u(3))
    e = u(rng.uniform(9, 13))
    dc.ellipse([top[0] - e - u(3), top[1] - e - u(3), top[0] + e + u(3), top[1] + e + u(3)], fill=G["ink"])
    dc.ellipse([top[0] - e, top[1] - e, top[0] + e, top[1] + e], fill=colour)
    c = e * 0.4
    dc.ellipse([top[0] - c, top[1] - c, top[0] + c, top[1] + c], fill=G["window"])


def paint_menhir(canvas, ax, ay, s, rng):
  """Standing stone: tall weathered slab, a carved spiral, lichen."""
  w, h = s * 0.6, s * 1.05
  cx, by = PAD + w / 2, PAD + h
  lean = rng.uniform(-0.05, 0.05)
  pts = [(-0.18, 0), (-0.15 + lean, 0.72), (-0.08 + lean, 0.95), (0.05 + lean, 1.0), (0.14 + lean, 0.8), (0.18, 0)]
  m = _mask_poly(w, h, [(cx + x * s, by - y * s) for x, y in pts], rng, amp=1.5, sub=2)
  ox, oy = ax - cx, ay - by
  stamp(canvas, m, ox, oy, G["stone"], G["stone_dk"], shade_of(G["stone"], 1.12))
  dc = ImageDraw.Draw(canvas)
  sx, sy = ax + lean * s * 0.4, ay - s * 0.5
  for r, a0 in ((0.075, 0), (0.045, 180), (0.02, 0)):  # spiral from half-arcs
    rr = r * s
    dc.arc([sx - rr, sy - rr, sx + rr, sy + rr], a0, a0 + 180, fill=G["stone_dk"], width=max(1, int(u(4))))
  for _ in range(4):
    x, y = ax + rng.uniform(-s * 0.12, s * 0.12), ay - s * rng.uniform(0.1, 0.85)
    e = u(rng.uniform(4, 8))
    dc.ellipse([x - e, y - e * 0.7, x + e, y + e * 0.7], fill=G["moss"])


def paint_cart(canvas, ax, ay, s, rng):
  """Broken war cart: tilted plank box, one wheel on, one lying in the mud."""
  w, h = s * 1.5, s * 0.9
  cx, by = PAD + w / 2, PAD + h
  tilt = rng.uniform(0.12, 0.25) * (1 if rng.random() < 0.5 else -1)

  def R2(x, y):  # rotate about the base point
    return (cx + x * math.cos(tilt) - y * math.sin(tilt), by - s * 0.18 + x * math.sin(tilt) + y * math.cos(tilt))

  body = _mask_poly(w, h, [R2(-s * 0.45, 0), R2(s * 0.4, 0), R2(s * 0.45, -s * 0.38), R2(-s * 0.5, -s * 0.38)], rng, amp=1)
  ox, oy = ax - cx, ay - by
  stamp(canvas, body, ox, oy, G["palisade"], G["palisade_dk"])
  dc = ImageDraw.Draw(canvas)
  for t in (-0.2, 0.05, 0.25):
    a, b = R2(s * (t * 1.6), 0), R2(s * (t * 1.6), -s * 0.38)
    dc.line([(a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)], fill=G["palisade_dk"], width=max(1, int(u(3))))
  a, b = R2(s * 0.4, -s * 0.15), R2(s * 0.75, -s * 0.05)  # broken shaft
  _ink_line(canvas, [(a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)], G["timber"], u(6))
  hx, hy = R2(-s * 0.25, s * 0.02)
  r = s * 0.2
  dc.ellipse([hx - r + ox, hy - r + oy, hx + r + ox, hy + r + oy], outline=G["ink"], width=int(u(10)))
  dc.ellipse([hx - r + ox, hy - r + oy, hx + r + ox, hy + r + oy], outline=G["timber"], width=int(u(5)))
  for k in range(4):
    a = k * math.pi / 4 + tilt
    dc.line([(hx + ox - math.cos(a) * r, hy + oy - math.sin(a) * r), (hx + ox + math.cos(a) * r, hy + oy + math.sin(a) * r)],
            fill=G["timber"], width=max(1, int(u(4))))
  fx, fy = ax + s * 0.4, ay - s * 0.02  # the fallen wheel, flat on the ground
  dc.ellipse([fx - r, fy - r * 0.35, fx + r, fy + r * 0.35], outline=G["ink"], width=int(u(9)))
  dc.ellipse([fx - r, fy - r * 0.35, fx + r, fy + r * 0.35], outline=G["timber"], width=int(u(4)))


def paint_spears(canvas, ax, ay, s, rng):
  """Spears and broken lances stuck in the ground at angles."""
  dc = ImageDraw.Draw(canvas)
  for _ in range(int(rng.integers(3, 6))):
    x = ax + rng.uniform(-s * 0.3, s * 0.3)
    a = rng.uniform(-0.45, 0.45)
    ln = s * rng.uniform(0.55, 1.0)
    top = (x + math.sin(a) * ln, ay - math.cos(a) * ln)
    _ink_line(canvas, [(x, ay), top], G["timber"], u(4))
    if rng.random() < 0.7:  # intact head
      dx, dy = math.sin(a), -math.cos(a)
      nx, ny = -dy, dx
      tip = (top[0] + dx * u(22), top[1] + dy * u(22))
      head = [tip, (top[0] + nx * u(7), top[1] + ny * u(7)), (top[0] - nx * u(7), top[1] - ny * u(7))]
      dc.polygon(head, fill=G["rock_lt"], outline=G["ink"])


def paint_warbanner(canvas, ax, ay, s, rng):
  """A torn war banner on a leaning pole: Marquisate orange or Eyrie blue."""
  colour = G["cat_banner"] if rng.random() < 0.5 else G["bird_banner"]
  lean = rng.uniform(-0.12, 0.12)
  top = (ax + lean * s, ay - s)
  _ink_line(canvas, [(ax, ay), top], G["timber"], u(5))
  w, h = s * 0.8, s * 0.7
  cx, by = PAD + w / 2, PAD + h
  fw, fh = s * 0.32, s * 0.4
  x0, y0 = cx + lean * s * 0.9, by - h + s * 0.05
  pts = [(x0, y0), (x0 + fw, y0 + s * 0.03)]
  for k in range(5):  # ragged bottom edge
    t = 1 - k / 4
    pts.append((x0 + fw * t, y0 + fh * rng.uniform(0.55, 1.0)))
  m = _mask_poly(w, h, pts, rng, amp=1, sub=2)
  stamp(canvas, m, ax - cx, ay - by, colour, shade_of(colour, 0.75))


def paint_gnarled(canvas, ax, ay, s, rng):
  """Deepwood ancient: twisted trunk with flared roots, crooked limbs, three
  blue-green canopy clumps, hanging moss and a few glowing motes."""
  w, h = s * 1.6, s * 1.65
  cx, by = PAD + w / 2, PAD + h
  ox, oy = ax - cx, ay - by
  flip = 1 if rng.random() < 0.5 else -1

  def P(x, y):
    return (cx + flip * x * s, by - y * s)

  # canopy clumps first (behind the limbs' tips), as (x, y, radius)
  clumps = [(-0.36, 1.05, 0.27), (0.32, 1.12, 0.29), (-0.02, 1.36, 0.25)]
  for x, y, r in clumps:
    x += rng.uniform(-0.03, 0.03)
    y += rng.uniform(-0.03, 0.03)
    m = blank(w, h)
    d = ImageDraw.Draw(m)
    ccx, ccy = P(x, y)
    rr = r * s
    d.ellipse([ccx - rr * 0.7, ccy - rr * 0.7, ccx + rr * 0.7, ccy + rr * 0.7], fill=255)
    n = int(rng.integers(6, 9))
    for k in range(n):
      a = 2 * math.pi * k / n + rng.normal(0, 0.2)
      br = rr * rng.uniform(0.34, 0.46)
      px, py = ccx + math.cos(a) * rr * 0.55, ccy + math.sin(a) * rr * 0.45
      d.ellipse([px - br, py - br, px + br, py + br], fill=255)
    stamp(canvas, m, ox, oy, G["gnarl_leaf"], G["gnarl_leaf_dk"], G["gnarl_leaf_lt"])
  # trunk + roots + limbs as one twisted silhouette
  trunk = [(-0.5, 0.0), (-0.22, 0.07), (-0.15, 0.25), (-0.07, 0.42), (-0.15, 0.6), (-0.3, 0.88), (-0.36, 0.96),
           (-0.27, 0.95), (-0.1, 0.76), (-0.04, 0.95), (-0.03, 1.2), (0.04, 1.2), (0.06, 0.92), (0.14, 0.82),
           (0.3, 1.0), (0.36, 1.03), (0.3, 0.9), (0.15, 0.66), (0.09, 0.45), (0.15, 0.24), (0.2, 0.07),
           (0.48, 0.0), (0.28, -0.02), (0.08, 0.03), (-0.05, -0.02), (-0.28, -0.02)]
  m = _mask_poly(w, h, [P(x, y) for x, y in trunk], rng, amp=1.5, sub=2)
  stamp(canvas, m, ox, oy, G["gnarl_bark"], G["gnarl_bark_dk"])
  dc = ImageDraw.Draw(canvas)
  lw = max(1, int(u(3.5)))
  for x0, y0, x1, y1 in ((-0.08, 0.12, -0.02, 0.36), (0.06, 0.18, 0.02, 0.4), (-0.06, 0.5, -0.1, 0.7),
                         (0.05, 0.55, 0.1, 0.7)):  # bark lines
    a, b = P(x0, y0), P(x1, y1)
    dc.line([(a[0] + ox, a[1] + oy), ((a[0] + b[0]) / 2 + ox + u(5), (a[1] + b[1]) / 2 + oy), (b[0] + ox, b[1] + oy)],
            fill=G["ink"], width=lw, joint="curve")
  kx, ky = P(0.02, 0.5)  # knot hole
  e = s * 0.045
  dc.ellipse([kx - e * 0.7 + ox, ky - e + oy, kx + e * 0.7 + ox, ky + e + oy], fill=G["ink"])
  # hanging moss under each clump
  for x, y, r in clumps:
    for _ in range(3):
      tx, ty = P(x + rng.uniform(-r * 0.6, r * 0.6), y - r * 0.35)
      ln = s * rng.uniform(0.12, 0.24)
      pts = [(tx + ox, ty + oy), (tx + ox + u(4), ty + oy + ln * 0.5), (tx + ox - u(2), ty + oy + ln)]
      _ink_line(canvas, pts, G["moss"], u(4))
  # glowing motes
  for _ in range(int(rng.integers(3, 6))):
    gx, gy = P(rng.uniform(-0.55, 0.55), rng.uniform(0.3, 1.4))
    for scale, colour in ((2.4, tuple((a + b) // 2 for a, b in zip(G["glow"], G["gnarl_leaf_lt"]))), (1.0, G["glow"])):
      e = u(5) * scale
      dc.ellipse([gx - e + ox, gy - e + oy, gx + e + ox, gy + e + oy], fill=colour)


def paint_statue(canvas, ax, ay, s, rng):
  """Guildhall centrepiece: a weathered bronze vagabond on a stone pedestal.
  Root woodlander -- fox-ish head in three-quarter view, hooded cloak, bushy
  tail, walking staff, satchel, sword hilt over the shoulder. s = total height."""
  bw, bh = s * 0.8, s * 1.15
  cx, by = PAD + bw / 2, PAD + bh
  ox, oy = ax - cx, ay - by

  def P(x, y):
    return (cx + x * s, by - y * s)

  def poly(pts, amp=1.2):
    return _mask_poly(bw, bh, [P(x, y) for x, y in pts], rng, amp=amp, sub=2)

  def oval(x, y, rx, ry, rot=0.0, n=18):
    pts = []
    for k in range(n):
      a = 2 * math.pi * k / n
      px, py = math.cos(a) * rx, math.sin(a) * ry
      pts.append((x + px * math.cos(rot) - py * math.sin(rot), y + px * math.sin(rot) + py * math.cos(rot)))
    m = blank(bw, bh)
    ImageDraw.Draw(m).polygon([P(px, py) for px, py in pts], fill=255)
    return m

  def put(mask, fill, shade=None, light=None):
    stamp(canvas, mask, ox, oy, fill, shade, light)

  bronze = (G["statue"], G["statue_dk"], G["statue_lt"])
  dc = ImageDraw.Draw(canvas)

  def L(pts, colour, width):
    _ink_line(canvas, [(P(x, y)[0] + ox, P(x, y)[1] + oy) for x, y in pts], colour, width)

  # pedestal: step, plinth, cap; gold plaque
  put(poly([(-0.26, 0), (0.26, 0), (0.26, 0.07), (-0.26, 0.07)], 0.8), G["stone"], G["stone_dk"])
  put(poly([(-0.19, 0.06), (0.19, 0.06), (0.19, 0.33), (-0.19, 0.33)], 0.8), G["stone"], G["stone_dk"])
  put(poly([(-0.23, 0.32), (0.23, 0.32), (0.23, 0.38), (-0.23, 0.38)], 0.8), G["stone"], G["stone_dk"])
  x0, y0 = P(-0.09, 0.25)
  x1, y1 = P(0.09, 0.16)
  dc.rectangle([x0 + ox, y0 + oy, x1 + ox, y1 + oy], fill=G["banner_lt"], outline=G["ink"], width=max(1, int(u(3))))
  for yy in (0.225, 0.19):
    a, b = P(-0.06, yy), P(0.06, yy)
    dc.line([(a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)], fill=G["stone_dk"], width=max(1, int(u(2.5))))
  # figure, back to front
  put(oval(-0.2, 0.6, 0.085, 0.17, rot=0.45), *bronze)                       # bushy tail
  L([(-0.075, 0.74), (-0.17, 0.92)], G["statue_dk"], s * 0.022)              # sword grip over the shoulder
  L([(-0.2, 0.88), (-0.135, 0.95)], G["statue_dk"], s * 0.018)               # crossguard
  put(poly([(-0.17, 0.38), (-0.11, 0.78), (0.11, 0.78), (0.17, 0.38)]), *bronze)  # cloak
  put(oval(0.0, 0.79, 0.12, 0.045), G["statue_dk"])                         # hood fallen round the neck
  head = oval(0.0, 0.88, 0.085, 0.085)
  head = ImageChops.lighter(head, oval(0.075, 0.86, 0.065, 0.035))           # snout, turned three-quarters
  head = ImageChops.lighter(head, poly([(-0.075, 0.92), (-0.055, 1.04), (-0.01, 0.95)], 0.6))  # ears
  head = ImageChops.lighter(head, poly([(0.015, 0.95), (0.055, 1.05), (0.08, 0.92)], 0.6))
  put(head, *bronze)
  for (x, y), e in (((0.035, 0.9), 0.011), ((0.138, 0.866), 0.013)):          # eye, nose
    px, py = P(x, y)
    dc.ellipse([px - e * s + ox, py - e * s + oy, px + e * s + ox, py + e * s + oy], fill=G["ink"])
  L([(-0.1, 0.74), (0.12, 0.5)], G["statue_dk"], s * 0.016)                  # satchel strap
  put(poly([(0.06, 0.43), (0.16, 0.43), (0.16, 0.52), (0.06, 0.52)], 0.8), G["statue_dk"])
  L([(0.22, 0.38), (0.25, 1.06)], G["statue"], s * 0.024)                    # staff, planted on the pedestal
  put(oval(0.215, 0.64, 0.04, 0.04), *bronze)                               # paw on the staff
  for _ in range(5):                                                          # moss on the stone
    px, py = P(rng.uniform(-0.2, 0.2), rng.uniform(0.02, 0.36))
    e = s * rng.uniform(0.012, 0.022)
    dc.ellipse([px - e + ox, py - e * 0.7 + oy, px + e + ox, py + e * 0.7 + oy], fill=G["leaf_lt"])


def paint_windmill(canvas, ax, ay, s, rng):
  """Farmstead centrepiece: stone tower, conical cap, four lattice sails."""
  w, h = s * 1.3, s * 1.35
  cx, by = PAD + w / 2, PAD + h
  ox, oy = ax - cx, ay - by

  def P(x, y):
    return (cx + x * s, by - y * s)

  tower = _mask_poly(w, h, [P(-0.18, 0), P(-0.11, 0.62), P(0.11, 0.62), P(0.18, 0)], rng)
  stamp(canvas, tower, ox, oy, G["wall"], G["wall_dk"])
  roofc = G["roofs"][0]
  cap = _mask_poly(w, h, [P(-0.15, 0.6), P(0, 0.8), P(0.15, 0.6)], rng)
  stamp(canvas, cap, ox, oy, roofc, shade_of(roofc, 0.78))
  dc = ImageDraw.Draw(canvas)
  x0, y0 = P(-0.05, 0.16)
  x1, y1 = P(0.05, 0)
  dc.rounded_rectangle([x0 + ox, y0 + oy, x1 + ox, y1 + oy], int(u(8)), fill=G["ink"])
  wx, wy = P(0, 0.38)
  e = s * 0.03
  dc.rectangle([wx - e + ox, wy - e + oy, wx + e + ox, wy + e + oy], fill=G["window"], outline=G["ink"],
               width=max(1, int(u(4))))
  hub = P(0, 0.62)
  spin = rng.uniform(0, math.pi / 2)
  for k in range(4):
    a = spin + k * math.pi / 2
    dx, dy = math.cos(a), -math.sin(a)
    nx, ny = -dy, dx
    near, far, half = s * 0.05, s * 0.55, s * 0.06
    pts = [(hub[0] + dx * near + nx * f * half, hub[1] + dy * near + ny * f * half) for f in (0, 1)] + \
          [(hub[0] + dx * far + nx * f * half, hub[1] + dy * far + ny * f * half) for f in (1, 0)]
    sail = _mask_poly(w, h, pts, rng, amp=0.8, sub=2)
    stamp(canvas, sail, ox, oy, G["stem"], shade_of(G["stem"], 0.85))
    for t in (0.3, 0.5, 0.7, 0.9):
      a0 = (hub[0] + dx * far * t + ox, hub[1] + dy * far * t + oy)
      dc.line([a0, (a0[0] + nx * half, a0[1] + ny * half)], fill=G["timber"], width=max(1, int(u(3))))
    _ink_line(canvas, [(hub[0] + ox, hub[1] + oy), (hub[0] + dx * far + ox, hub[1] + dy * far + oy)],
              G["timber"], u(5))
  e = s * 0.035
  dc.ellipse([hub[0] - e + ox, hub[1] - e + oy, hub[0] + e + ox, hub[1] + e + oy], fill=G["timber"], outline=G["ink"],
             width=max(1, int(u(3))))


def paint_mountain(canvas, ax, ay, s, rng):
  w, h = s * 1.6, s * 1.25
  cx, by = PAD + w / 2, PAD + h
  apex = (cx + rng.uniform(-s * 0.15, s * 0.15), by - h)
  left, right = (cx - w / 2, by), (cx + w / 2, by)
  m = blank(w, h)
  ImageDraw.Draw(m).polygon(wobble([left, apex, right], rng, 5, sub=6), fill=255)
  foot = (apex[0] + s * 0.18, by)
  lit = blank(w, h)
  ImageDraw.Draw(lit).polygon([left, apex, foot], fill=255)
  lit = ImageChops.multiply(lit, m)
  t = 0.32
  sl = (apex[0] + (left[0] - apex[0]) * t, apex[1] + (left[1] - apex[1]) * t)
  sr = (apex[0] + (right[0] - apex[0]) * t, apex[1] + (right[1] - apex[1]) * t)
  zig = [sl] + [(sl[0] + (sr[0] - sl[0]) * k / 5, sl[1] + (u(18) if k % 2 else -u(6))) for k in range(1, 5)]
  snow = blank(w, h)
  ImageDraw.Draw(snow).polygon([apex, sr] + zig[::-1], fill=255)
  snow = ImageChops.multiply(snow, m)
  ox, oy = int(ax - cx), int(ay - by)
  box = (ox, oy, ox + m.size[0], oy + m.size[1])
  stamp(canvas, m, ox, oy, G["rock_dk"])
  canvas.paste(G["rock_lt"], box, lit)
  canvas.paste(G["snow"], box, snow)
  ImageDraw.Draw(canvas).line(
    [(apex[0] + ox, apex[1] + oy),
     (apex[0] + (foot[0] - apex[0]) * 0.6 + ox, apex[1] + (foot[1] - apex[1]) * 0.6 + oy)],
    fill=G["ink"], width=max(1, int(u(5))))


def paint_house(canvas, ax, ay, s, rng):
  w, h = s * 1.2, s * 1.2
  cx, by = PAD + w / 2, PAD + h
  ww, wh = s * rng.uniform(0.7, 0.95), s * rng.uniform(0.45, 0.6)
  wall = blank(w, h)
  ImageDraw.Draw(wall).rectangle([cx - ww / 2, by - wh, cx + ww / 2, by], fill=255)
  rh = s * rng.uniform(0.4, 0.55)
  roof = blank(w, h)
  ImageDraw.Draw(roof).polygon(wobble([(cx - ww / 2 - u(12), by - wh + u(4)), (cx, by - wh - rh),
                                       (cx + ww / 2 + u(12), by - wh + u(4))], rng, 2), fill=255)
  ox, oy = ax - cx, ay - by
  roofc = G["roofs"][int(rng.integers(0, len(G["roofs"])))]
  stamp(canvas, wall, ox, oy, G["wall"], G["wall_dk"])
  stamp(canvas, roof, ox, oy, roofc, shade_of(roofc, 0.78))
  dc = ImageDraw.Draw(canvas)
  dx = cx + ox + rng.uniform(-ww * 0.25, ww * 0.15)
  dc.rounded_rectangle([dx - u(11), by + oy - u(34), dx + u(11), by + oy], int(u(6)), fill=G["ink"])
  wx, wy = cx + ox + ww * 0.22, by + oy - wh * 0.75
  dc.rectangle([wx - u(9), wy, wx + u(9), wy + u(18)], fill=G["window"], outline=G["ink"],
               width=max(1, int(u(4))))


def paint_stake(canvas, ax, ay, s, rng):
  """One palisade log, pointed top. Shaded by a flat strip, not a crescent:
  the crescent offset is wider than the stake itself."""
  w, h = s * 0.36, s
  cx, by = PAD + w / 2, PAD + h
  m = blank(w, h)
  ImageDraw.Draw(m).polygon(wobble([(cx - w / 2, by), (cx - w / 2, by - h * 0.8), (cx, by - h),
                                    (cx + w / 2, by - h * 0.8), (cx + w / 2, by)], rng, 1, sub=2), fill=255)
  dark = blank(w, h)
  ImageDraw.Draw(dark).rectangle([cx + w * 0.12, 0, cx + w, by], fill=255)
  ox, oy = int(ax - cx), int(ay - by)
  stamp(canvas, m, ox, oy, G["palisade"])
  canvas.paste(G["palisade_dk"], (ox, oy, ox + m.size[0], oy + m.size[1]), ImageChops.multiply(dark, m))


def paint_tent(canvas, ax, ay, s, rng):
  """Guild campaign tent: canvas A-frame, guild-colour stripes, pennant."""
  w, h = s * 1.1, s * 0.8
  cx, by = PAD + w / 2, PAD + h * 1.35
  body = blank(w, h * 1.35)
  ImageDraw.Draw(body).polygon(wobble([(cx - w / 2, by), (cx, by - h), (cx + w / 2, by)], rng, 2, sub=3), fill=255)
  ox, oy = ax - cx, ay - by
  stamp(canvas, body, ox, oy, G["wall"], G["wall_dk"])
  d = ImageDraw.Draw(canvas)
  lw = max(1, int(u(6)))
  for f in (-0.28, 0.28):
    d.line([(cx + ox, by + oy - h), (cx + ox + f * w, by + oy)], fill=G["banner"], width=lw)
  d.polygon([(cx + ox - w * 0.12, by + oy), (cx + ox, by + oy - h * 0.45), (cx + ox + w * 0.12, by + oy)],
            fill=G["ink"])
  top = by + oy - h
  d.line([(cx + ox, top), (cx + ox, top - h * 0.3)], fill=G["ink"], width=max(1, int(u(4))))
  d.polygon([(cx + ox, top - h * 0.3), (cx + ox + w * 0.2, top - h * 0.25), (cx + ox, top - h * 0.18)],
            fill=G["banner"], outline=G["ink"])


def paint_guildhall(canvas, ax, ay, s, rng, tier=3):
  """The Guild's hall: big timber-framed hall with two wings, a front gable,
  arched doors, banners and a bell cupola. A meeting house, not a castle.
  s = overall width. Coordinates below are fractions of s: X across from the
  centre, Y up from the ground line.

  tier 1-4 adds detail (build_landmarks.py): 1 lodge with chimney, 2 + gable, banners,
  framing, 3 + wings and cupola (the map-tile centerpiece), 4 + corner towers,
  clock tower, lanterns. Tiers below 4 must keep their draw order: every
  wobbled shape draws from rng, so reordering changes the tile."""
  bw, bh = (s * 1.3, s * 1.1) if tier >= 4 else (s * 1.15, s * 0.95)
  cx, by = PAD + bw / 2, PAD + bh

  def X(f):
    return cx + f * s

  def Y(f):
    return by - f * s

  def poly(pts, amp=1.5):
    m = blank(bw, bh)
    ImageDraw.Draw(m).polygon(wobble([(X(x), Y(y)) for x, y in pts], rng, amp, sub=3), fill=255)
    return m

  def box(x0, y0, x1, y1, amp=1.5):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], amp)

  ox, oy = ax - cx, ay - by
  dark_wood = shade_of(G["timber"], 0.8)

  def put(mask, fill, shade=None, light=None):
    stamp(canvas, mask, ox, oy, fill, shade, light)

  d = ImageDraw.Draw(canvas)
  lw = max(1, int(u(4)))

  def L(pts, colour=G["ink"], width=lw):
    d.line([(X(x) + ox, Y(y) + oy) for x, y in pts], fill=colour, width=width)

  def pennant(x, y0, y1):
    L([(x, y0), (x, y1)])
    d.polygon([(X(px) + ox, Y(py) + oy) for px, py in [(x, y1), (x + 0.1, y1 - 0.027), (x, y1 - 0.055)]],
              fill=G["banner"], outline=G["ink"])

  # wings sit behind the hall
  if tier >= 3:
    for side in (-1, 1):
      put(box(side * 0.48, 0.04, side * 0.235, 0.235), G["wall"], G["wall_dk"])
      put(poly([(side * 0.51, 0.225), (side * 0.45, 0.36), (side * 0.235, 0.36), (side * 0.235, 0.225)]),
          G["guild_roof"], G["guild_roof_dk"])
  if tier >= 4:  # round corner towers capping the wings
    for side in (-1, 1):
      put(box(side * 0.6, 0.0, side * 0.47, 0.42), G["stone"], G["stone_dk"])
      put(poly([(side * 0.625, 0.41), (side * 0.535, 0.6), (side * 0.445, 0.41)]), G["guild_roof"], G["guild_roof_dk"])
      for y in (0.12, 0.27):  # arrow-slit windows
        d.rectangle([X(side * 0.535 - 0.012) + ox, Y(y + 0.06) + oy, X(side * 0.535 + 0.012) + ox, Y(y) + oy],
                    fill=G["window"], outline=G["ink"], width=lw)
      for y in (0.14, 0.29):
        L([(side * 0.6, y), (side * 0.47, y)], G["stone_dk"], max(1, int(u(3))))
      pennant(side * 0.535, 0.6, 0.7)
  # main hall
  put(box(-0.26, 0.04, 0.26, 0.335), G["wall"], G["wall_dk"])
  put(box(0.14, 0.44, 0.185, 0.61), G["stone"], G["stone_dk"])  # chimney, behind the roof edge
  put(poly([(-0.3, 0.325), (-0.2, 0.56), (0.2, 0.56), (0.3, 0.325)]), G["guild_roof"], G["guild_roof_dk"])
  if tier == 3:  # cupola + pennant on the ridge
    put(box(-0.045, 0.555, 0.045, 0.64), G["wall"], G["wall_dk"])
    put(poly([(-0.068, 0.635), (0, 0.745), (0.068, 0.635)]), G["guild_roof"], G["guild_roof_dk"])
    pennant(0, 0.745, 0.85)
    d.rectangle([X(-0.024) + ox, Y(0.615) + oy, X(0.024) + ox, Y(0.575) + oy], fill=G["ink"])  # bell arch
  if tier >= 4:  # clock tower in place of the cupola
    put(box(-0.065, 0.54, 0.065, 0.72), G["wall"], G["wall_dk"])
    put(poly([(-0.095, 0.71), (0, 0.86), (0.095, 0.71)]), G["guild_roof"], G["guild_roof_dk"])
    pennant(0, 0.86, 0.97)
    r = 0.042
    d.ellipse([X(-r) + ox, Y(0.645 + r) + oy, X(r) + ox, Y(0.645 - r) + oy], fill=G["paper"], outline=G["ink"], width=lw)
    L([(0, 0.645), (0, 0.675)])
    L([(0, 0.645), (0.022, 0.645)])
  # timber framing on the walls
  beam = max(1, int(u(7)))
  if tier >= 2:
    for f in (-0.2, -0.13, 0.13, 0.2):
      L([(f, 0.05), (f, 0.32)], G["timber"], beam)
    for a, b in ((-0.26, -0.13), (0.13, 0.26)):
      L([(a, 0.19), (b, 0.19)], G["timber"], beam)
  if tier >= 3:
    for side in (-1, 1):
      for f in (0.42, 0.32):
        L([(side * f, 0.05), (side * f, 0.225)], G["timber"], beam)
      L([(side * 0.48, 0.14), (side * 0.235, 0.14)], G["timber"], beam)
      L([(side * 0.42, 0.14), (side * 0.32, 0.05)], G["timber"], beam)  # brace
  # windows, lit
  win = max(1, int(u(4)))
  windows = ((-0.185, 0.22), (0.145, 0.22))
  if tier >= 3:
    windows += ((-0.395, 0.07), (0.345, 0.07))
  for x0, y0 in windows:
    d.rectangle([X(x0) + ox, Y(y0 + 0.055) + oy, X(x0 + 0.04) + ox, Y(y0) + oy],
                fill=G["window"], outline=G["ink"], width=win)
    L([(x0 + 0.02, y0), (x0 + 0.02, y0 + 0.055)], G["ink"], max(1, int(u(3))))
  def round_window(y, r=0.036):
    d.ellipse([X(-r) + ox, Y(y + r) + oy, X(r) + ox, Y(y - r) + oy], fill=G["window"], outline=G["ink"], width=win)
    L([(-r, y), (r, y)], G["ink"], max(1, int(u(3))))
    L([(0, y - r), (0, y + r)], G["ink"], max(1, int(u(3))))

  if tier == 1:  # no gable: the round window sits on the wall over the door
    round_window(0.28)
  if tier >= 2:
    # front gable over the door, with a round window
    put(poly([(-0.165, 0.29), (0, 0.53), (0.165, 0.29)]), G["guild_roof"], G["guild_roof_dk"])
    put(poly([(-0.12, 0.29), (0, 0.465), (0.12, 0.29)], amp=1), G["wall"], G["wall_dk"])
    round_window(0.375)
    # banners either side of the door
    for f in (-0.095, 0.095):
      put(poly([(f - 0.026, 0.3), (f + 0.026, 0.3), (f + 0.026, 0.15), (f, 0.172), (f - 0.026, 0.15)], amp=0.8),
          G["banner"])
      e = 0.013
      d.ellipse([X(f - e) + ox, Y(0.255 + e) + oy, X(f + e) + ox, Y(0.255 - e) + oy], fill=G["banner_lt"])
  # foundation band, arched double door, steps
  half = 0.49 if tier >= 3 else 0.28
  put(box(-half, 0.0, half, 0.05, amp=1), G["stone"], G["stone_dk"])
  door = blank(bw, bh)
  dd = ImageDraw.Draw(door)
  dd.rectangle([X(-0.058), Y(0.17), X(0.058), Y(0.04)], fill=255)
  dd.ellipse([X(-0.058), Y(0.228), X(0.058), Y(0.112)], fill=255)
  put(door, dark_wood)
  L([(0, 0.04), (0, 0.225)])
  if tier >= 2:
    put(box(-0.1, -0.03, 0.1, 0.02, amp=1), G["stone"], G["stone_dk"])
  if tier >= 3:
    for f in (-0.36, -0.12, 0.12, 0.36):  # mortar ticks on the foundation
      L([(f, 0.0), (f, 0.05)], G["stone_dk"], max(1, int(u(3))))
  if tier >= 4:  # lanterns flanking the steps
    for side in (-1, 1):
      x = side * 0.145
      L([(x, -0.03), (x, 0.13)], G["ink"], max(1, int(u(6))))
      put(box(x - 0.018, 0.12, x + 0.018, 0.17, amp=0.6), G["window"])
      put(poly([(x - 0.026, 0.165), (x, 0.195), (x + 0.026, 0.165)], amp=0.6), G["timber"])


def paint_field(canvas, x0, y0, fw, fh, rng):
  m = blank(fw, fh)
  ImageDraw.Draw(m).polygon(
    wobble([(PAD, PAD), (PAD + fw, PAD), (PAD + fw, PAD + fh), (PAD, PAD + fh)], rng, 5, sub=3), fill=255)
  stripes = Image.new("RGB", m.size, G["fields"][int(rng.integers(0, len(G["fields"])))])
  ds = ImageDraw.Draw(stripes)
  vertical = rng.random() < 0.5
  step, lw = int(u(26)), max(1, int(u(7)))
  for k in range(0, int(max(m.size)), step):
    if vertical:
      ds.line([(k, 0), (k + u(10), m.size[1])], fill=G["field_lt"], width=lw)
    else:
      ds.line([(0, k), (m.size[0], k + u(10))], fill=G["field_lt"], width=lw)
  ox, oy = int(x0 - PAD), int(y0 - PAD)
  canvas.paste(G["ink"], (ox, oy, ox + m.size[0], oy + m.size[1]), ink_ring(m))
  canvas.paste(stripes, (ox, oy), m)


PAINTERS = {"tree": paint_tree, "pine": paint_pine, "bush": paint_bush,
            "mountain": paint_mountain, "house": paint_house, "stake": paint_stake,
            "tent": paint_tent, "guildhall": paint_guildhall, "blossom": paint_blossom,
            "fruit": paint_fruit, "oak": paint_oak, "heather": paint_heather, "deadtree": paint_deadtree,
            "charred": paint_charred, "stump": paint_stump, "rock": paint_rock, "hill": paint_hill,
            "reeds": paint_reeds, "mushroom": paint_mushroom, "ruinwall": paint_ruinwall,
            "column": paint_column, "crane": paint_crane, "logpile": paint_logpile,
            "haystack": paint_haystack, "windmill": paint_windmill, "statue": paint_statue,
            "gnarled": paint_gnarled, "briar": paint_briar, "flowers": paint_flowers,
            "menhir": paint_menhir, "cart": paint_cart, "spears": paint_spears, "warbanner": paint_warbanner}


# ---------------------------------------------------------------- tile
def edge_point(e):
  return {"N": (R / 2, -u(40)), "S": (R / 2, R + u(40)),
          "W": (-u(40), R / 2), "E": (R + u(40), R / 2)}[e]


def seg_dist(p, a, b):
  dx, dy = b[0] - a[0], b[1] - a[1]
  t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy + 1e-9)))
  return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def path_points(e, rng):
  c = (R / 2, R / 2)
  end = edge_point(e)
  # the last stretch runs straight in, so it meets the neighbour's path head on
  inner = (R / 2 + (end[0] - R / 2) * 0.82, R / 2 + (end[1] - R / 2) * 0.82)
  nx, ny = -(inner[1] - c[1]), inner[0] - c[0]
  ln = math.hypot(nx, ny)
  j = rng.normal(0, u(G["path_wobble"]))
  mid = ((c[0] + inner[0]) / 2 + nx / ln * j, (c[1] + inner[1]) / 2 + ny / ln * j)
  pts = [c]
  for k in range(1, 9):
    t = k / 8
    pts.append(((1 - t) ** 2 * c[0] + 2 * (1 - t) * t * mid[0] + t * t * inner[0],
                (1 - t) ** 2 * c[1] + 2 * (1 - t) * t * mid[1] + t * t * inner[1]))
  pts.append(end)
  return pts


def draw_path(d, pts):
  w = int(u(G["path_width"]))
  d.line(pts, fill=G["ink"], width=w + int(u(10)), joint="curve")
  d.line(pts, fill=G["path"], width=w, joint="curve")
  for x, y in pts[1::2]:
    d.ellipse([x - u(4), y - u(3), x + u(4), y + u(3)], fill=G["path_pebble"])


_PAPER = {}


def paper():
  if R not in _PAPER:
    grain = fbm(R, 4242, octaves=3, base=48) * 0.5 + np.random.default_rng(9).random((R, R)) * 0.5
    wash = fbm(R, 99, octaves=3, base=2)
    yy, xx = np.mgrid[0:R, 0:R]
    vig = 1 - G["vignette"] * (((xx - R / 2) ** 2 + (yy - R / 2) ** 2) / (R / 2) ** 2) ** 2
    pg = G["paper_grain"]
    _PAPER[R] = (1 - pg + pg * grain) * (0.95 + 0.08 * wash) * vig.clip(0.7, 1)
  return _PAPER[R]


def finish(img):
  a = np.asarray(img, float) * paper()[..., None]
  t = G["paper_tint"]
  a = a * (1 - t) + np.array(G["paper"], float) * t
  return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def frame(img, edges=(), cuts=()):
  """cuts: (x, [(colour, width), ...]) -- a river or canyon breaking through the
  N and S border, drawn as nested vertical bands (widest first)."""
  d = ImageDraw.Draw(img)
  fw = int(u(G["frame_width"]))
  d.rectangle([0, 0, R - 1, R - 1], outline=G["frame"], width=fw)
  d.rectangle([fw + u(4), fw + u(4), R - fw - u(5), R - fw - u(5)], outline=G["paper"], width=max(1, int(u(4))))
  d.rectangle([fw + u(8), fw + u(8), R - fw - u(9), R - fw - u(9)], outline=G["ink"], width=max(1, int(u(3))))
  for e in edges:  # doorway: the path breaks through the frame
    x, y = edge_point(e)
    x, y = min(max(x, 0), R), min(max(y, 0), R)
    outer, inner, reach = u(33), u(23), fw + u(14)
    if e in "NS":
      d.rectangle([x - outer, y - reach, x + outer, y + reach], fill=G["ink"])
      d.rectangle([x - inner, y - reach, x + inner, y + reach], fill=G["path"])
    else:
      d.rectangle([x - reach, y - outer, x + reach, y + outer], fill=G["ink"])
      d.rectangle([x - reach, y - inner, x + reach, y + inner], fill=G["path"])
  for x, bands in cuts:
    for y0, y1 in ((0, fw + u(14)), (R - fw - u(14), R)):
      for colour, width in bands:
        d.rectangle([x - width / 2, y0, x + width / 2, y1], fill=colour)
  return img


# half-width of a painter's body (x size) for scatter collision, and its ground shadow width
WIDE_BASE = ("hill", "ruinwall", "gnarled", "briar", "cart")
BODY_HALF = {"gnarled": 0.5, "briar": 0.6, "cart": 0.6, "mountain": 0.7, "hill": 0.9, "ruinwall": 0.62, "crane": 0.45, "logpile": 0.35}
SHADOW_WIDTH = {"gnarled": 0.6, "briar": 0.62, "flowers": 0.3, "menhir": 0.22, "cart": 0.6, "spears": 0.25,
                "warbanner": 0.15, "statue": 0.3, "mountain": 0.8, "stake": 0.3, "guildhall": 0.52, "windmill": 0.3, "hill": 0.85,
                "rock": 0.55, "crane": 0.3, "reeds": 0.25, "ruinwall": 0.62, "column": 0.25,
                "logpile": 0.45, "stump": 0.45}


def river_points(rng):
  """A river running N to S down the west side of the tile, clear of the clearing.
  It crosses the N and S edges at exactly x = river_anchor, running straight
  over the seam, so any two river tiles stacked N-S join up (E-W never do).
  The canyon is this mirrored to the east side."""
  ax = u(G["river_anchor"])
  ctrl = [(ax, -u(80)), (ax, R * 0.1)]
  for t in (0.3, 0.5, 0.7):
    ctrl.append((ax + rng.normal(0, u(35)) + math.sin(t * 2 * math.pi) * u(55), R * t))
  ctrl += [(ax, R * 0.9), (ax, R + u(80))]
  for _ in range(3):  # Chaikin smoothing
    smooth = [ctrl[0]]
    for a, b in zip(ctrl, ctrl[1:]):
      smooth += [(a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25), (a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75)]
    ctrl = smooth + [ctrl[-1]]
  return ctrl


def fit_corner(clear_of, max_r, min_r, squash=0.75):
  """Largest ellipse (radius, squash) centred in a tile corner that stays clear
  of roads and the clearing. Off-tile rim points don't count, so it can spill
  over the edge. Returns (centre, radius) or None."""
  best = None
  for fx, fy in ((0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)):
    c = (R * fx, R * fy)
    r = max_r
    while r >= min_r:
      rim = [(c[0] + math.cos(a) * r, c[1] + math.sin(a) * r * squash) for a in np.linspace(0, 2 * math.pi, 20, endpoint=False)]
      if all(clear_of(q, u(15)) for q in rim if 0 <= q[0] <= R and 0 <= q[1] <= R):
        break
      r -= u(15)
    if r >= min_r and (best is None or r > best[1]):
      best = (c, r)
  return best


def blob(img, cx, cy, rx, ry, rng, fill, shade=None, light=None, amp=4):
  """Wobbly ellipse stamped at (cx, cy) -- pools, mud, lakes."""
  m = blank(2 * rx, 2 * ry)
  ring = [(PAD + rx + math.cos(a) * rx, PAD + ry + math.sin(a) * ry) for a in np.linspace(0, 2 * math.pi, 18, endpoint=False)]
  ImageDraw.Draw(m).polygon(wobble(ring, rng, amp, sub=2), fill=255)
  stamp(img, m, cx - rx - PAD, cy - ry - PAD, fill, shade, light)


def crossing(pts, line, width):
  """Where path pts cross a ribbon (line, width): (start, end, ux, uy) or None."""
  dense = []
  for a, b in zip(pts, pts[1:]):
    n = max(1, int(math.dist(a, b) / u(6)))
    dense += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
  lsegs = list(zip(line, line[1:]))
  wet = [i for i, q in enumerate(dense) if any(seg_dist(q, a, b) < width / 2 + u(14) for a, b in lsegs)]
  if not wet:
    return None
  a, b = dense[wet[0]], dense[wet[-1]]
  ln = math.dist(a, b) or 1
  ux, uy = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
  return (a[0] - ux * u(14), a[1] - uy * u(14)), (b[0] + ux * u(14), b[1] + uy * u(14)), ux, uy


def draw_rope_bridge(img, pts, line, width):
  """Plank-and-rope bridge over a canyon: gaps between planks show the drop."""
  hit = crossing(pts, line, width)
  if not hit:
    return
  a, b, ux, uy = hit
  nx, ny = -uy, ux
  half = (u(G["path_width"]) + u(10)) / 2
  d = ImageDraw.Draw(img)
  n = int(math.dist(a, b) / u(16))
  for k in range(n + 1):
    cx, cy = a[0] + ux * k * u(16), a[1] + uy * k * u(16)
    q = [(cx - nx * half, cy - ny * half), (cx + nx * half, cy + ny * half)]
    d.line(q, fill=G["ink"], width=int(u(12)))
    d.line(q, fill=G["palisade"], width=int(u(7)))
  for side in (-1, 1):
    off = (nx * side * (half + u(3)), ny * side * (half + u(3)))
    d.line([(a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])], fill=G["ink"], width=max(1, int(u(4))))
    for end in (a, b):  # posts
      px, py = end[0] + off[0], end[1] + off[1]
      e = u(7)
      d.ellipse([px - e, py - e, px + e, py + e], fill=G["timber"], outline=G["ink"], width=max(1, int(u(3))))


def draw_bridge(img, pts, river, rw):
  """Plank bridge where a path crosses the river."""
  dense = []
  for a, b in zip(pts, pts[1:]):
    n = max(1, int(math.dist(a, b) / u(6)))
    dense += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
  rsegs = list(zip(river, river[1:]))
  wet = [i for i, q in enumerate(dense) if any(seg_dist(q, a, b) < rw / 2 + u(14) for a, b in rsegs)]
  if not wet:
    return
  a, b = dense[wet[0]], dense[wet[-1]]
  dx, dy = b[0] - a[0], b[1] - a[1]
  ln = math.hypot(dx, dy) or 1
  ux, uy = dx / ln, dy / ln
  a, b = (a[0] - ux * u(10), a[1] - uy * u(10)), (b[0] + ux * u(10), b[1] + uy * u(10))
  pw = u(G["path_width"])
  d = ImageDraw.Draw(img)
  d.line([a, b], fill=G["ink"], width=int(pw + u(26)))
  d.line([a, b], fill=G["palisade"], width=int(pw + u(14)))
  nx, ny = -uy, ux
  half = (pw + u(14)) / 2
  n = int(math.dist(a, b) / u(15))
  for k in range(1, n):
    cx, cy = a[0] + ux * k * u(15), a[1] + uy * k * u(15)
    d.line([(cx - nx * half, cy - ny * half), (cx + nx * half, cy + ny * half)], fill=G["palisade_dk"],
           width=max(1, int(u(3))))
  for side in (-1, 1):
    off = (nx * side * (half + u(2)), ny * side * (half + u(2)))
    d.line([(a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])], fill=G["ink"], width=max(1, int(u(5))))


def draw_tile(region, seed, edges, density):
  rng = np.random.default_rng(seed)
  clear_r = u(region["clearing"])
  wash = fbm(R, seed + 7, octaves=3, base=3)
  ground = np.array(region["ground"], float) * (0.93 + 0.14 * wash[..., None])
  img = Image.fromarray(ground.clip(0, 255).astype(np.uint8))
  d = ImageDraw.Draw(img)

  paths = [path_points(e, rng) for e in edges]
  segs = [(a, b) for pts in paths for a, b in zip(pts, pts[1:])]
  half_path = u(G["path_width"]) / 2

  def clear_of(p, margin, extra=()):
    if math.dist(p, (R / 2, R / 2)) < clear_r + margin:
      return False
    return all(seg_dist(p, a, b) > half_path + margin for a, b in list(segs) + list(extra))

  # ground features: drawn under paths; each adds a blocker the scatter avoids
  blockers = []
  bank_spots = []
  river = None
  if region["feature"] == "river":
    river = river_points(rng)
    rw = u(G["river_width"])
    d.line(river, fill=G["ink"], width=int(rw + u(12)), joint="curve")
    d.line(river, fill=G["water"], width=int(rw), joint="curve")
    for _ in range(14):  # ripples
      i = int(rng.integers(1, len(river) - 1))
      x, y = river[i][0] + rng.uniform(-rw * 0.25, rw * 0.25), river[i][1] + rng.uniform(-u(20), u(20))
      d.arc([x - u(16), y - u(6), x + u(16), y + u(6)], 200, 340, fill=G["water_lt"], width=max(1, int(u(4))))
    rsegs = list(zip(river, river[1:]))
    blockers.append(lambda q: any(seg_dist(q, a, b) < rw / 2 + u(25) for a, b in rsegs))
    for i in range(2, len(river) - 2, 3):  # reeds along the banks
      (x0, y0), (x1, y1) = river[i - 1], river[i + 1]
      ln = math.hypot(x1 - x0, y1 - y0) or 1
      nx, ny = -(y1 - y0) / ln, (x1 - x0) / ln
      for side in (-1, 1):
        if rng.random() < 0.55:
          q = (river[i][0] + side * nx * (rw / 2 + u(18)), river[i][1] + side * ny * (rw / 2 + u(18)) + u(20))
          if u(60) < q[0] < R - u(40) and u(80) < q[1] < R - u(40) and clear_of(q, u(15)):
            bank_spots.append((q[0], q[1], "reeds", u(rng.uniform(*G["reed_size"]))))
  elif region["feature"] == "pools":
    pools = []
    for _ in range(300):
      if len(pools) >= G["pool_count"]:
        break
      rx = u(rng.uniform(*G["pool_size"]))
      ry = rx * rng.uniform(0.5, 0.7)
      c = (rng.uniform(u(60) + rx, R - u(60) - rx), rng.uniform(u(60) + ry, R - u(60) - ry))
      rim = [(c[0] + math.cos(a) * rx, c[1] + math.sin(a) * ry) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
      if not all(clear_of(q, u(20)) for q in rim + [c]):
        continue
      if any(math.dist(c, (px, py)) < rx + prx + u(30) for px, py, prx, _ in pools):
        continue
      pools.append((c[0], c[1], rx, ry))
      m = blank(2 * rx, 2 * ry)
      ring = [(PAD + rx + math.cos(a) * rx, PAD + ry + math.sin(a) * ry) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
      ImageDraw.Draw(m).polygon(wobble(ring, rng, 4, sub=2), fill=255)
      stamp(img, m, c[0] - rx - PAD, c[1] - ry - PAD, G["water"], G["water_dk"], G["water_lt"])
      for _ in range(int(rng.integers(2, 5))):  # lily pads
        lx, ly = c[0] + rng.uniform(-rx * 0.5, rx * 0.5), c[1] + rng.uniform(-ry * 0.4, ry * 0.4)
        e = u(13)
        d.ellipse([lx - e - u(3), ly - e * 0.7 - u(3), lx + e + u(3), ly + e * 0.7 + u(3)], fill=G["ink"])
        d.pieslice([lx - e, ly - e * 0.7, lx + e, ly + e * 0.7], 40, 360, fill=G["leaf"])
    blockers.append(lambda q: any(((q[0] - px) / (prx + u(20))) ** 2 + ((q[1] - py) / (pry + u(20))) ** 2 < 1
                                  for px, py, prx, pry in pools))
  elif region["feature"] == "pit":
    pit = None
    for pr in (u(G["pit_size"][1]), u(G["pit_size"][0])):  # try big, then small
      quads = [(0.27, 0.27), (0.73, 0.27), (0.27, 0.73), (0.73, 0.73)]
      rng.shuffle(quads)
      for fx, fy in quads:
        c = (R * fx, R * fy)
        rim = [(c[0] + math.cos(a) * pr, c[1] + math.sin(a) * pr * 0.8) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
        if all(clear_of(q, u(10)) for q in rim):
          pit = (c, pr)
          break
      if pit:
        break
    if pit:
      (pcx, pcy), pr = pit
      for f, fill in ((1.0, G["rock_lt"]), (0.72, G["stone"]), (0.46, G["rock_dk"])):
        rx, ry = pr * f, pr * 0.8 * f
        m = blank(2 * rx, 2 * ry)
        ring = [(PAD + rx + math.cos(a) * rx, PAD + ry + math.sin(a) * ry) for a in np.linspace(0, 2 * math.pi, 14, endpoint=False)]
        ImageDraw.Draw(m).polygon(wobble(ring, rng, 3, sub=2), fill=255)
        stamp(img, m, pcx - rx - PAD, pcy - ry - PAD + (1 - f) * u(30), fill, shade_of(fill, 0.8))
      blockers.append(lambda q: ((q[0] - pcx) / (pr + u(25))) ** 2 + ((q[1] - pcy) / (pr * 0.8 + u(45))) ** 2 < 1)
  elif region["feature"] == "lake":
    fit = fit_corner(clear_of, u(G["lake_size"][1]), u(G["lake_size"][0]))
    if fit:
      (lcx, lcy), lr = fit
      lry = lr * 0.75
      blob(img, lcx, lcy, lr, lry, rng, G["water"], G["water_dk"], G["water_lt"], amp=6)
      for _ in range(16):  # ripples
        x, y = lcx + rng.uniform(-lr * 0.6, lr * 0.6), lcy + rng.uniform(-lry * 0.6, lry * 0.6)
        if 0 < x < R and 0 < y < R:
          d.arc([x - u(18), y - u(6), x + u(18), y + u(6)], 200, 340, fill=G["water_lt"], width=max(1, int(u(4))))
      for _ in range(int(rng.integers(4, 8))):  # lily pads
        x, y = lcx + rng.uniform(-lr * 0.55, lr * 0.55), lcy + rng.uniform(-lry * 0.55, lry * 0.55)
        e = u(14)
        d.ellipse([x - e - u(3), y - e * 0.7 - u(3), x + e + u(3), y + e * 0.7 + u(3)], fill=G["ink"])
        d.pieslice([x - e, y - e * 0.7, x + e, y + e * 0.7], 40, 360, fill=G["leaf"])
      for a in np.linspace(0, 2 * math.pi, 26, endpoint=False):  # shore reeds
        q = (lcx + math.cos(a) * (lr + u(22)), lcy + math.sin(a) * (lry + u(22)) + u(20))
        if rng.random() < 0.5 and u(60) < q[0] < R - u(40) and u(80) < q[1] < R - u(40) and clear_of(q, u(15)):
          bank_spots.append((q[0], q[1], "reeds", u(rng.uniform(*G["reed_size"]))))
      blockers.append(lambda q: ((q[0] - lcx) / (lr + u(25))) ** 2 + ((q[1] - lcy) / (lry + u(40))) ** 2 < 1)
  elif region["feature"] == "canyon":
    canyon = [(R - x, y) for x, y in river_points(rng)]  # east side, so it isn't a river's twin
    cw = u(G["canyon_width"])
    d.line(canyon, fill=G["ink"], width=int(cw + u(12)), joint="curve")
    d.line(canyon, fill=G["chasm_wall"], width=int(cw), joint="curve")
    d.line(canyon, fill=shade_of(G["chasm_wall"], 0.75), width=int(cw * 0.7), joint="curve")
    d.line(canyon, fill=G["chasm"], width=int(cw * 0.4), joint="curve")
    for i in range(2, len(canyon) - 2, 2):  # strata ticks on both walls
      (x0, y0), (x1, y1) = canyon[i - 1], canyon[i + 1]
      ln = math.hypot(x1 - x0, y1 - y0) or 1
      nx, ny = -(y1 - y0) / ln, (x1 - x0) / ln
      for side in (-1, 1):
        px, py = canyon[i][0] + side * nx * cw * 0.3, canyon[i][1] + side * ny * cw * 0.3
        d.line([(px, py), (px + side * nx * u(16), py + side * ny * u(16))], fill=G["ink"], width=max(1, int(u(3))))
    csegs = list(zip(canyon, canyon[1:]))
    blockers.append(lambda q: any(seg_dist(q, a, b) < cw / 2 + u(25) for a, b in csegs))
  elif region["feature"] == "falls":
    fit = fit_corner(clear_of, u(G["falls_size"][1]), u(G["falls_size"][0]), squash=0.9)
    if fit:
      (fcx, fcy), fr = fit
      top, base = fcy - fr * 0.85, fcy + fr * 0.25
      # cliff: grassy top lip, rock face with strata
      face = [(fcx - fr * 0.95, base), (fcx - fr * 0.9, top + fr * 0.2), (fcx - fr * 0.45, top), (fcx + fr * 0.3, top + fr * 0.05),
              (fcx + fr * 0.95, top + fr * 0.25), (fcx + fr * 0.95, base)]
      m = blank(R, R)
      ImageDraw.Draw(m).polygon(wobble(face, rng, 4, sub=3), fill=255)
      stamp(img, m, 0, 0, G["rock_dk"], shade_of(G["rock_dk"], 0.8), G["rock_lt"])
      lip = [(fcx - fr * 0.92, top + fr * 0.2), (fcx - fr * 0.45, top), (fcx + fr * 0.3, top + fr * 0.05),
             (fcx + fr * 0.95, top + fr * 0.25), (fcx + fr * 0.95, top + fr * 0.4), (fcx - fr * 0.92, top + fr * 0.35)]
      m = blank(R, R)
      ImageDraw.Draw(m).polygon(wobble(lip, rng, 3, sub=3), fill=255)
      stamp(img, m, 0, 0, G["hill"], G["hill_dk"])
      for k in range(4):
        y = top + fr * (0.5 + 0.17 * k)
        d.line([(fcx - fr * 0.85, y), (fcx - fr * 0.2, y + u(8)), (fcx + fr * 0.85, y - u(6))], fill=G["ink"],
               width=max(1, int(u(3))), joint="curve")
      # the fall, then the pool it lands in
      fw = fr * 0.22
      m = blank(R, R)
      ImageDraw.Draw(m).polygon([(fcx - fw / 2, top + fr * 0.08), (fcx + fw / 2, top + fr * 0.1),
                                 (fcx + fw * 0.6, base + u(10)), (fcx - fw * 0.6, base + u(10))], fill=255)
      stamp(img, m, 0, 0, G["water"], None, G["water_lt"])
      for k in range(4):
        x = fcx - fw * 0.35 + k * fw * 0.23
        d.line([(x, top + fr * 0.15), (x + u(3), base - u(5))], fill=G["water_lt"], width=max(1, int(u(4))))
      blob(img, fcx, base + fr * 0.28, fr * 0.7, fr * 0.3, rng, G["water"], G["water_dk"], G["water_lt"])
      for _ in range(9):  # foam where the water lands
        x, y = fcx + rng.uniform(-fw, fw), base + rng.uniform(u(5), u(30))
        e = u(rng.uniform(8, 14))
        d.ellipse([x - e, y - e * 0.6, x + e, y + e * 0.6], fill=G["foam"], outline=G["ink"], width=max(1, int(u(2.5))))
      blockers.append(lambda q: abs(q[0] - fcx) < fr + u(20) and top - u(20) < q[1] < base + fr * 0.6 + u(30))
  elif region["feature"] in ("mud", "springs"):
    mud = region["feature"] == "mud"
    holes = []
    want = G["mud_count"] if mud else G["spring_count"]
    lo, hi = G["mud_size"] if mud else G["spring_size"]
    for _ in range(300):
      if len(holes) >= want:
        break
      rx = u(rng.uniform(lo, hi))
      ry = rx * rng.uniform(0.5, 0.7)
      c = (rng.uniform(u(60) + rx, R - u(60) - rx), rng.uniform(u(60) + ry, R - u(60) - ry))
      rim = [(c[0] + math.cos(a) * rx, c[1] + math.sin(a) * ry) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
      if not all(clear_of(q, u(20)) for q in rim + [c]):
        continue
      if any(math.dist(c, (hx, hy)) < rx + hrx + u(30) for hx, hy, hrx, _ in holes):
        continue
      holes.append((c[0], c[1], rx, ry))
      if mud:
        blob(img, c[0], c[1], rx, ry, rng, G["mud"], G["mud_dk"])
        for _ in range(3):  # puddles + hoof prints
          x, y = c[0] + rng.uniform(-rx * 0.5, rx * 0.5), c[1] + rng.uniform(-ry * 0.4, ry * 0.4)
          e = u(rng.uniform(6, 12))
          d.ellipse([x - e, y - e * 0.6, x + e, y + e * 0.6], fill=G["water_dk"])
      else:
        blob(img, c[0], c[1], rx, ry, rng, G["spring"], G["spring_dk"], G["water_lt"])
        for a in np.linspace(0, 2 * math.pi, int(rng.integers(10, 15)), endpoint=False):  # ring of stones
          x, y = c[0] + math.cos(a) * (rx + u(4)), c[1] + math.sin(a) * (ry + u(4))
          e = u(rng.uniform(10, 16))
          d.ellipse([x - e, y - e * 0.65, x + e, y + e * 0.65], fill=G["rock_lt"], outline=G["ink"], width=max(1, int(u(3))))
        for k in range(3):  # steam wisps
          x0 = c[0] + (k - 1) * rx * 0.4
          wisp = [(x0 + math.sin(t * 0.9 + k) * u(10), c[1] - t * u(14)) for t in range(9)]
          d.line(wisp, fill=G["foam"], width=max(1, int(u(5))), joint="curve")
    blockers.append(lambda q: any(((q[0] - hx) / (hrx + u(20))) ** 2 + ((q[1] - hy) / (hry + u(20))) ** 2 < 1
                                  for hx, hy, hrx, hry in holes))

  fields = []
  for _ in range(400):
    if len(fields) >= region["fields"]:
      break
    fw, fh = u(rng.uniform(*G["field_width"])), u(rng.uniform(*G["field_height"]))
    x, y = rng.uniform(u(50), R - u(50) - fw), rng.uniform(u(50), R - u(50) - fh)
    pts = [(x, y), (x + fw, y), (x, y + fh), (x + fw, y + fh), (x + fw / 2, y + fh / 2)]
    if all(clear_of(p, u(30)) and not any(fx <= p[0] <= fx + fw2 and fy <= p[1] <= fy + fh2
                                         for fx, fy, fw2, fh2 in fields) for p in pts):
      paint_field(img, x, y, fw, fh, rng)
      fields.append((x, y, fw, fh))

  for _ in range(region["grass"]):
    x, y = rng.uniform(u(40), R - u(40), 2)
    if any(b((x, y)) for b in blockers):  # no grass on water, cliffs or pits
      continue
    for k in range(3):
      d.line([(x + k * u(9), y), (x + k * u(9) + (k - 1) * u(4), y - u(14) - (k == 1) * u(5))],
             fill=G["grass"], width=max(1, int(u(3))))

  for colour, count in region["speckle"]:  # petals, ash, spores
    for _ in range(count):
      x, y = rng.uniform(u(40), R - u(40), 2)
      if math.dist((x, y), (R / 2, R / 2)) < clear_r + u(10) or any(b((x, y)) for b in blockers):
        continue
      e = u(rng.uniform(4, 7))
      d.ellipse([x - e, y - e * 0.65, x + e, y + e * 0.65], fill=colour)

  for pts in paths:
    draw_path(d, pts)
  if river:
    for pts in paths:
      draw_bridge(img, pts, river, rw)
  if region["feature"] == "canyon":
    for pts in paths:
      draw_rope_bridge(img, pts, canyon, cw)

  cm = blank(2 * clear_r, 2 * clear_r)
  ring = [(PAD + clear_r + math.cos(a) * clear_r, PAD + clear_r + math.sin(a) * clear_r)
          for a in np.linspace(0, 2 * math.pi, 18, endpoint=False)]
  ImageDraw.Draw(cm).polygon(wobble(ring, rng, 3, sub=2), fill=255)
  cobble = region["clearing_style"] == "cobble"
  stamp(img, cm, R / 2 - clear_r - PAD, R / 2 - clear_r - PAD, G["cobble"] if cobble else G["clearing"])
  if cobble:
    for _ in range(60):
      a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(0, clear_r - u(18))
      x, y = R / 2 + math.cos(a) * rr, R / 2 + math.sin(a) * rr
      d.ellipse([x - u(9), y - u(6), x + u(9), y + u(6)], outline=G["cobble_line"], width=max(1, int(u(3))))

  # scatter icons; each icon's whole body must stay off paths, fields and the clearing
  field_segs = [s for fx, fy, fw, fh in fields
                for s in (((fx, fy), (fx + fw, fy + fh)), ((fx + fw, fy), (fx, fy + fh)))]
  centre = (R / 2, R / 2)
  hall = None
  if region["centerpiece"] != "none":
    hs = u(region["centerpiece_size"])
    hall = (R / 2, R / 2 - clear_r * CENTERPIECE_SETBACK[region["centerpiece"]], hs)  # base point + size
    box_w, box_h = CENTERPIECE_BOX[region["centerpiece"]]
  town_r = u(region["town_radius"])
  scale = G["density_scale"][density - 1]
  spots = []

  def scatter(icons, spacing, zone, limit=None, rows=None):
    """zone: None = whole tile, 'in' = inside town_r, 'out' = outside it.
    limit: stop after placing this many. rows: grid layout (default: region's)."""
    names = [i[0] for i in icons]
    weights = np.array([i[1] for i in icons], float)
    weights /= weights.sum()
    placed_before = len(spots)
    if rows is None:
      rows = region["layout"] == "rows"
    if rows:
      step = spacing
      cand = [(x + rng.uniform(-step * 0.08, step * 0.08), y + rng.uniform(-step * 0.08, step * 0.08))
              for y in np.arange(u(130), R - u(50), step * 0.85) for x in np.arange(u(80), R - u(50), step)]
    else:
      cand = None
    for attempt in range(len(cand) if cand else 3000):
      if limit is not None and len(spots) - placed_before >= limit:
        break
      if cand:
        p = cand[attempt]
      elif zone == "in":
        p = (rng.uniform(R / 2 - town_r, R / 2 + town_r), rng.uniform(R / 2 - town_r, R / 2 + town_r))
      else:
        p = (rng.uniform(u(70), R - u(40)), rng.uniform(u(110), R - u(50)))
      k = rng.choice(len(names), p=weights)
      _, _, lo, hi = icons[k]
      sz = u(rng.uniform(lo, hi))
      half = sz * BODY_HALF.get(names[k], 0.35)
      body = [p, (p[0], p[1] - sz * 0.6), (p[0] - half, p[1] - sz * 0.2), (p[0] + half, p[1] - sz * 0.2)]
      if names[k] in WIDE_BASE:  # wide at the ground line: check the base corners too
        body += [(p[0] + f * half, p[1] - sz * h) for f in (-1, -0.5, 0.5, 1) for h in (0.05, 0.3)]
      if zone == "in" and max(math.dist(q, centre) for q in body) > town_r - u(30):
        continue
      if zone == "out" and min(math.dist(q, centre) for q in body) < town_r + u(40):
        continue
      if hall and any(abs(q[0] - hall[0]) < hall[2] * box_w and hall[1] - hall[2] * box_h < q[1] < hall[1] + u(30)
                      for q in body):
        continue
      if any(b(q) for b in blockers for q in body):
        continue
      if not all(clear_of(q, u(18), field_segs) for q in body):
        continue
      # a grid spaces itself; it only has to avoid what was placed before it
      if any(math.dist(p, q[:2]) < spacing for q in (spots[:placed_before] if cand else spots)):
        continue
      spots.append((p[0], p[1], names[k], sz))

  if hall:
    spots.append((hall[0], hall[1], region["centerpiece"], hall[2]))
  for painter, count, lo, hi in region["required"]:  # guaranteed icons go first
    scatter([(painter, 1, lo, hi)], u(region["spacing"] * scale), "in" if town_r else None, limit=count, rows=False)
  if town_r:
    scatter(region["icons"], u(region["spacing"] * scale), "in")
    if region["outer_icons"]:
      scatter(region["outer_icons"], u(region["outer_spacing"] * scale), "out")
  else:
    scatter(region["icons"], u(region["spacing"] * scale), None)

  spots += bank_spots

  if region["wall"] == "menhirs":
    count = max(5, int(2 * math.pi * town_r / u(G["menhir_spacing"])))
    phase = rng.uniform(0, 2 * math.pi)
    for i in range(count):
      a = phase + 2 * math.pi * i / count
      p = (R / 2 + math.cos(a) * town_r, R / 2 + math.sin(a) * town_r * 0.92)
      if any(seg_dist(p, a0, b0) < half_path + u(40) for a0, b0 in segs):
        continue
      spots.append((p[0], p[1], "menhir", u(rng.uniform(*G["menhir_size"]))))

  if region["wall"] == "palisade":
    # stakes round a slightly wobbly ring; a road leaves a gate, flanked by taller posts
    phase = rng.uniform(0, 2 * math.pi)
    count = int(2 * math.pi * town_r / u(G["stake_spacing"]))
    ring = []
    for i in range(count):
      a = 2 * math.pi * i / count
      rr = town_r * (1 + 0.03 * math.sin(3 * a + phase))
      p = (R / 2 + math.cos(a) * rr, R / 2 + math.sin(a) * rr)
      gate = any(seg_dist(p, a0, b0) < half_path + u(16) for a0, b0 in segs)
      ring.append((p, gate))
    for i, (p, gate) in enumerate(ring):
      if gate:
        continue
      post = ring[i - 1][1] or ring[(i + 1) % count][1]
      spots.append((p[0], p[1], "stake", u(rng.uniform(*G["stake_size"])) * (1.35 if post else 1)))

  shadow = Image.new("L", (R, R), 0)
  ds = ImageDraw.Draw(shadow)
  for x, y, name, s in spots:
    sw = s * SHADOW_WIDTH.get(name, 0.5)
    ds.ellipse([x - sw, y - s * 0.12, x + sw * 1.1, y + s * 0.14], fill=90)
  img.paste(shade_of(region["ground"], 0.72), (0, 0, R, R), shadow.filter(ImageFilter.GaussianBlur(u(6))))
  for x, y, name, s in sorted(spots, key=lambda q: q[1]):
    PAINTERS[name](img, x, y, s, rng)
  cuts = []
  if river:
    cuts.append((river[0][0], [(G["ink"], rw + u(12)), (G["water"], rw)]))
  if region["feature"] == "canyon":
    cuts.append((canyon[0][0], [(G["ink"], cw + u(12)), (G["chasm_wall"], cw),
                                (shade_of(G["chasm_wall"], 0.75), cw * 0.7), (G["chasm"], cw * 0.4)]))
  return frame(finish(img), edges, cuts)


DECK_KEYS = ("name", "gem", "colour")


def parse_decks(groups):
  """deck_<id> groups -> {id: {"id", "name", "gem", "colour"}}. A deck is an
  event deck (plans/taxonomy.md "Event decks"); every tile back shows one."""
  decks = {}
  for group, raw in groups.items():
    did = group[len("deck_"):]
    for k in DECK_KEYS:
      if not raw.get(k):
        die("%s.%s is missing" % (group, k))
    try:
      colour = hexrgb(raw["colour"])
    except ValueError:
      die("%s.colour: bad value %r" % (group, raw["colour"]))
    decks[did] = {"id": did, "name": raw["name"], "colour": colour,
                  "gem": re.sub(r"\.png$", "", raw["gem"], flags=re.I)}
  return decks


def draw_back(deck):
  """One back per event deck: deck colour, its gem, its name on the ribbon."""
  img = Image.new("RGB", (R, R), deck["colour"])
  gem_path = os.path.join(GEM_DIR, deck["gem"] + ".png")
  if not os.path.exists(gem_path):
    die("deck_%s.gem: assets/gems/%s.png not found (run tools/build_gems.py?)"
        % (deck["id"], deck["gem"]))
  gem = Image.open(gem_path).convert("RGBA")
  side = int(u(G["back_gem_size"]))
  gem.thumbnail((side, side), Image.LANCZOS)  # keeps aspect; never upscales past the source
  if max(gem.size) < side:
    scale = side / max(gem.size)
    gem = gem.resize((int(gem.size[0] * scale), int(gem.size[1] * scale)), Image.LANCZOS)
  # centred in the space above the ribbon
  gx, gy = (R - gem.size[0]) // 2, int(R / 2 + u(10) - gem.size[1] / 2)
  img.paste(gem, (gx, gy), gem)
  d = ImageDraw.Draw(img)
  y = R / 2 + u(230)
  ribbon = [(u(170), y), (R - u(170), y), (R - u(120), y + u(50)), (R - u(170), y + u(100)),
            (u(170), y + u(100)), (u(120), y + u(50))]
  d.polygon(ribbon, fill=G["paper"])
  d.line(ribbon + ribbon[:1], fill=G["ink"], width=max(1, int(u(8))))
  text = deck["name"]  # exactly as typed in the CSV
  size = int(u(70))
  font = ImageFont.truetype(G["back_font"], size)
  while d.textlength(text, font=font) > R - u(320) and size > 10:
    size -= 4
    font = ImageFont.truetype(G["back_font"], size)
  d.text(((R - d.textlength(text, font=font)) / 2, y + u(50) - size * 0.55), text, font=font, fill=G["ink"])
  return frame(finish(img))


# ---------------------------------------------------------------- build
def tile_seed(region, shape, n):
  # crc32 rather than hash(): stable across runs, so unchanged knobs = unchanged image
  key = "%s|%s|%d" % (region["name"], shape, n)
  return (zlib.crc32(key.encode()) + G["seed"] * 7919 + region["seed_offset"] * 104729) % (2 ** 31)


def out_file(region, name, pattern):
  """Manifest `file`: path under assets/maptiles/. Backs share one folder; tiles
  go in a folder per region."""
  return "/".join(("backs" if pattern == "back" else region, name + ".png"))


def save(img, rel):
  path = os.path.join(OUT_DIR, *rel.split("/"))
  os.makedirs(os.path.dirname(path), exist_ok=True)
  if img.size[0] != G["out_size"]:
    img = img.resize((G["out_size"], G["out_size"]), Image.LANCZOS)
  img.save(path)


def read_manifest():
  if not os.path.exists(MANIFEST):
    return []
  with open(MANIFEST, newline="", encoding="utf-8") as f:
    return list(csv.DictReader(f))


def parse_shape(token):
  """'tee' -> ('tee', None); 'corner_ES' -> ('corner', ('E','S')); 'back' -> ('back', None)."""
  pattern, _, edges = token.partition("_")
  if pattern == "back" and not edges:
    return pattern, None
  if pattern not in PATTERNS:
    sys.exit("--shape: unknown %r (use back %s, or e.g. corner_ES)" % (token, " ".join(PATTERNS)))
  if not edges:
    return pattern, None
  want = tuple(e for e in EDGE_ORDER if e in edges.upper())
  if len(want) != len(edges) or want not in orientations(pattern):
    sys.exit("--shape: %r is not an orientation of %s (have: %s)" % (
      token, pattern, " ".join("%s_%s" % (pattern, "".join(o)) for o in orientations(pattern))))
  return pattern, want


def plan(regions, decks, shapes=None, densities=None, variants=None):
  """Manifest rows for every image to draw. None = take the value from the CSV.
  Tiles come per region; backs come per event deck -- one for each deck the
  chosen regions use."""
  rows = []
  want_back = shapes is None or ("back", None) in shapes
  for region in regions:
    wanted = [(p, None) for p in region["patterns"]] if shapes is None else shapes
    for pattern, only_edges in wanted:
      if pattern == "back":
        continue
      for edges in orientations(pattern):
        if only_edges is not None and edges != only_edges:
          continue
        shape = "%s_%s" % (pattern, "".join(edges)) if edges else pattern
        for n in range(1, (variants or region["variants"]) + 1):
          for density in densities or region["densities"]:
            name = "%s_%s%d_d%d" % (region["name"], shape, n, density)
            rows.append({"name": name, "region": region["name"], "pattern": pattern,
                         "edges": "|".join(edges), "density": density,
                         "seed": tile_seed(region, shape, n), "file": out_file(region["name"], name, pattern),
                         "_region": region, "_edges": edges})
  if want_back:
    for did in dict.fromkeys(r["deck"] for r in regions):  # first-use order, no repeats
      name = "%s_back" % did
      rows.append({"name": name, "region": did, "pattern": "back", "edges": "", "density": "",
                   "seed": "", "file": out_file(did, name, "back"), "_deck": decks[did]})
  return rows


def main():
  ap = argparse.ArgumentParser(description="Draw storybook map tiles from data/asset_variables.csv.")
  ap.add_argument("--region", nargs="+", help="regions to draw (default: all)")
  ap.add_argument("--shape", nargs="+", help="back, none, deadend, corner, straight, tee, cross, or e.g. corner_ES")
  ap.add_argument("--density", help="stages: 3, 1-4 or 1|3|5 (default: CSV)")
  ap.add_argument("--variants", type=int, help="looks per orientation (default: CSV)")
  ap.add_argument("--prune", action="store_true", help="delete images the CSV no longer describes")
  args = ap.parse_args()

  glob, raw_regions = load_config(ASSET_VARS)
  setup(parse_global(glob))
  if not raw_regions:
    die("no regions defined")
  decks = parse_decks({g: v for g, v in raw_regions.items() if g.startswith("deck_")})
  raw_regions = {g: v for g, v in raw_regions.items() if not g.startswith("deck_")}
  regions = [parse_region(name, raw) for name, raw in raw_regions.items()]
  for r in regions:
    if r["deck"] not in decks:
      die("%s.deck: unknown %r (have: %s)" % (r["name"], r["deck"], " ".join(decks)))
  if args.region:
    for name in args.region:
      if name not in raw_regions:
        sys.exit("--region: unknown %r (have: %s)" % (name, " ".join(raw_regions)))
    chosen = [r for r in regions if r["name"] in args.region]
  else:
    chosen = regions
  shapes = [parse_shape(t) for t in args.shape] if args.shape else None
  densities = parse_stages("--density", args.density) if args.density else None
  if args.variants is not None and args.variants < 1:
    sys.exit("--variants must be 1 or more")
  todo = plan(chosen, decks, shapes, densities, args.variants)
  os.makedirs(OUT_DIR, exist_ok=True)

  for row in todo:
    if row["pattern"] == "back":
      img = draw_back(row["_deck"])
    else:
      img = draw_tile(row["_region"], row["seed"], row["_edges"], row["density"])
    save(img, row["file"])
    print("  " + row["name"])

  # Upsert: drawn rows replace their manifest entries, everything else stays.
  fields = ["name", "region", "pattern", "edges", "density", "seed", "file"]
  by_name = {r["name"]: r for r in read_manifest()}
  for r in todo:
    by_name[r["name"]] = {k: r[k] for k in fields}

  if args.prune:
    described = {r["name"] for r in plan(regions, decks)}
    for name in sorted(set(by_name) - described):
      del by_name[name]
    for folder, _, files in os.walk(OUT_DIR):
      for f in sorted(files):
        if f.endswith(".png") and f[:-4] not in described:
          os.remove(os.path.join(folder, f))
          print("  pruned " + os.path.relpath(os.path.join(folder, f), OUT_DIR).replace(os.sep, "/"))

  order = [r["name"] for r in regions]
  rows = sorted(by_name.values(),
                key=lambda r: (order.index(r["region"]) if r["region"] in order else len(order), r["name"]))
  with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields, restval="", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
  print("%d images -> %s" % (len(todo), os.path.relpath(OUT_DIR, WORKSPACE)))

if __name__ == "__main__":
  main()
