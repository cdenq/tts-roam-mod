#!/usr/bin/env python3
"""Draw storybook landmarks (Guildhall, buildings, caves, gathering nodes,
faction strongholds) as transparent PNG standees.

One image per landmark per size 1-4. The SIZE picks how much is drawn (a
size-4 building has more shapes than a size 1). How TALL it comes out is its
CLASS, the same idea as meeple size classes: every landmark in a class is the
same height in pixels, on one shared 1536 canvas (the meeples' canvas), base on
the bottom row, so one TTS import scale fits meeples and landmarks alike.

  class     height px   matches            used for
  small        525      short meeples      gathering nodes
  base         656      base meeples       tier-0 buildings
  big          820      big meeples        tier-1 buildings
  special     1000      (houses a big one) tier-2 buildings
  capitol     1200                         tier-3 buildings

(`landmark_class` rows give the heights; `landmark_tier` rows say which class
each landmark size is.) The height is reached by RE-DRAWING at a fitted width,
not by resizing the image, so the ink line is the same weight on every
landmark. Something too wide to reach its height inside the canvas is drawn
as tall as fits, and the build says so.

  data/asset_variables.csv            ->  assets/landmarks/<landmark>_s<size>.png
  (landmark, landmark_size,               assets/landmarks/manifest.csv
   landmark_colour rows + globals)

Every knob is a CSV row: canvas size, margin, seed, colours, the starting
width of each landmark at each size (its proportions; the fit rescales it),
the class heights and each landmark size's class. A landmark is drawn at a
size only if its `landmark_size` row has a width in that slot (`|||760` = size
4 only), and every drawn size needs a class in its `landmark_tier` row.
Shapes live in the painters below; a new landmark = a painter registered in
PAINTERS + a `landmark_size` row.

Painters are shared with build_map_tiles.py where they overlap: the Guildhall
at size 3 is the same drawing as the old tile centerpiece.

Same CSV + same seed = byte-identical output.

Not part of master_sync.cmd: art is rebuilt by hand, then uploaded by hand.

Run: python tools/build/build_landmarks.py                         every landmark, every size
     python tools/build/build_landmarks.py building                one landmark, all its sizes
     python tools/build/build_landmarks.py building cave --size 4  just those sizes
     python tools/build/build_landmarks.py --prune                 also delete images the CSV no longer describes
"""
import argparse, csv, math, os, sys, zlib

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/: datasets, spawn_cells, lua_inline
from datasets import ROOT, ASSET_VARS
import build_map_tiles as bm
from build_gems import finish_alpha

import numpy as np
from PIL import Image, ImageChops, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(ROOT), "assets", "landmarks")
MANIFEST = os.path.join(OUT_DIR, "manifest.csv")
LANDMARK_KEYS = ("out_size", "seed_offset", "margin")
LANDMARK_COLOURS = ("brick", "brick_dk", "brick_line", "marble", "marble_dk", "lm_cave", "ore", "ore_dk",
                    "ore_lt", "vein", "fish", "fish_dk", "earth", "earth_dk", "flame", "flame_lt", "fey", "fey_dk", "fey_lt",
                    "wisp", "shadow", "otter_banner", "knave_banner",
                    "alliance_banner", "lizard_banner", "lm_smoke")
SIZES = 4
# A landmark is a TTS stand-up token, extruded from its alpha outline: anything
# thinner than this (design units = px at 1024) becomes a sliver or breaks off.
# Every part that stands on its own and shapes the outline (poles, stems,
# stalks, ropes, handles, smoke) is drawn at least this wide via Sketch.pole().
MIN_STAND = 16
# Detached pieces smaller than this (px at out_size 1024, ~30 x 30) are dropped
# by solid_alpha: stray specks and floating motes would each become a sliver.
MIN_PIECE = 900
# Enclosed holes smaller than this are filled with ink (a narrow slot triangulates
# into stray walls); bigger ones stay open, which TTS cuts cleanly.
MAX_HOLE = 2000
# Fitting the height: stop within this fraction of the target, after at most FIT_TRIES draws.
FIT_TOLERANCE = 0.01
FIT_TRIES = 5
SIDE_MARGIN = 16  # design units kept clear at the canvas sides when a wide landmark is capped


# ---------------------------------------------------------------- drawing kit
class Sketch:
  """One painter's mask box. Coordinates are fractions of s: x across from the
  base centre, y UP from the ground line (same convention as paint_guildhall).
  Every filled shape goes through put() = bm.stamp()."""

  def __init__(self, canvas, ax, ay, s, rng, w=1.4, h=1.4):
    self.c, self.s, self.rng = canvas, s, rng
    self.bw, self.bh = s * w, s * h
    self.cx, self.by = bm.PAD + self.bw / 2, bm.PAD + self.bh
    self.ox, self.oy = int(ax - self.cx), int(ay - self.by)
    self.d = ImageDraw.Draw(canvas)

  def X(self, f):
    return self.cx + f * self.s

  def Y(self, f):
    return self.by - f * self.s

  def at(self, x, y):
    """Canvas point, for calling the map-tile painters."""
    return self.X(x) + self.ox, self.Y(y) + self.oy

  def mask(self):
    return bm.blank(self.bw, self.bh)

  def poly(self, pts, amp=1.5, sub=3):
    m = self.mask()
    pts = [(self.X(x), self.Y(y)) for x, y in pts]
    ImageDraw.Draw(m).polygon(bm.wobble(pts, self.rng, amp, sub=sub) if amp else pts, fill=255)
    return m

  def box(self, x0, y0, x1, y1, amp=1.5):
    return self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], amp)

  def oval(self, x, y, rx, ry, amp=1, a0=0.0, a1=2 * math.pi, n=20):
    closed = a1 - a0 >= 2 * math.pi
    pts = [(x + math.cos(a0 + (a1 - a0) * i / n) * rx, y + math.sin(a0 + (a1 - a0) * i / n) * ry)
           for i in range(n if closed else n + 1)]
    return self.poly(pts, amp, sub=2)

  def arch(self, x0, x1, y0, y1, amp=1):
    r = (x1 - x0) / 2
    mx, my = (x0 + x1) / 2, y1 - r
    pts = [(x0, y0), (x1, y0)] + [(mx + math.cos(math.pi * i / 12) * r, my + math.sin(math.pi * i / 12) * r)
                                  for i in range(13)]
    return self.poly(pts, amp, sub=2)

  def lines(self, segs, width):
    m = self.mask()
    dm = ImageDraw.Draw(m)
    for seg in segs:
      dm.line([(self.X(x), self.Y(y)) for x, y in seg], fill=255, width=max(1, int(bm.u(width))))
    return m

  def put(self, m, fill, shade=None, light=None):
    bm.stamp(self.c, m, self.ox, self.oy, fill, shade, light)

  def fill(self, m, colour):
    """Flat paste, no ink: patterns and lit faces inside an already-stamped shape."""
    self.c.paste(colour, (self.ox, self.oy, self.ox + m.size[0], self.oy + m.size[1]), m)

  def line(self, pts, colour=None, width=4):
    self.d.line([self.at(x, y) for x, y in pts], fill=colour or bm.G["ink"], width=max(1, int(bm.u(width))),
                joint="curve")

  def pole(self, pts, colour=None, width=MIN_STAND):
    """A standing stick (pole, stem, stalk, rope, handle) thick enough to survive
    token extrusion: `colour` core with the house ink edge, `width` overall."""
    bm._ink_line(self.c, [self.at(x, y) for x, y in pts], colour or bm.G["timber"], bm.u(width - 6))

  def window(self, x0, y0, x1, y1, arched=False):
    m = self.arch(x0, x1, y0, y1) if arched else self.box(x0, y0, x1, y1, amp=0.8)
    self.put(m, bm.G["window"])
    mx = (x0 + x1) / 2
    self.line([(mx, y0), (mx, y1 - (x1 - x0) / 2 if arched else y1)], width=3)
    if not arched:
      self.line([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)], width=3)


def clip(m, within):
  return ImageChops.multiply(m, within)


def lighten(c, t=0.3):
  return tuple(int(v + (255 - v) * t) for v in c)


def rotate(pts, deg, x0, y0):
  a = math.radians(deg)
  ca, sa = math.cos(a), math.sin(a)
  return [(x0 + x * ca - y * sa, y0 + x * sa + y * ca) for x, y in pts]


def rocky(k, pts, amp=3):
  """Rock mass in the mountain style: dark body, lit left face, ink ridge."""
  g = bm.G
  m = k.poly(pts, amp=amp)
  k.put(m, g["rock_dk"])
  px, py = max(pts, key=lambda p: p[1])
  lit = k.poly([(-1, -0.1), (-1, 1.5), (px, 1.5), (px - 0.06, py * 0.5), (px + 0.05, -0.1)], amp=0)
  k.fill(clip(lit, m), g["rock_lt"])
  k.line([(px, py), (px - 0.03, py * 0.75), (px - 0.06, py * 0.5)], width=4)
  return m


# ---------------------------------------------------------------- buildings
def paint_building(canvas, ax, ay, s, rng, tier):
  """1 straw hut, 2 log cabin, 3 stone town house, 4 capital hall in stone
  and brick."""
  (_straw_hut, _cabin, _townhouse, _manor)[tier - 1](canvas, ax, ay, s, rng)


def _cabin(canvas, ax, ay, s, rng):
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.1)
  body = k.box(-0.36, 0, 0.36, 0.42)
  k.put(body, g["palisade"], g["palisade_dk"])
  k.fill(clip(k.lines([[(-0.4, y), (0.4, y)] for y in (0.085, 0.17, 0.255, 0.34)], 4), body), g["palisade_dk"])
  for y in (0.0425, 0.1275, 0.2125, 0.2975):  # log ends at the corners
    for x in (-0.36, 0.36):
      k.put(k.oval(x, y, 0.036, 0.036, amp=0.6), g["stump_top"])
  k.put(k.box(-0.22, 0, -0.07, 0.27, amp=1), g["timber"])
  k.line([(-0.145, 0.01), (-0.145, 0.26)], width=3)
  k.put(k.box(0.0, 0.14, 0.05, 0.3, amp=0.8), g["palisade_dk"])
  k.put(k.box(0.21, 0.14, 0.26, 0.3, amp=0.8), g["palisade_dk"])
  k.window(0.05, 0.15, 0.21, 0.29)
  roof = k.poly([(-0.49, 0.36), (-0.25, 0.73), (0.25, 0.73), (0.49, 0.36)], amp=2.5)
  k.put(roof, g["hay"], g["hay_dk"])
  for i in range(9):  # thatch strokes
    x = -0.38 + i * 0.095
    k.line([(x, 0.385), (x * 0.92, 0.47)], g["hay_dk"], 3)
    if i % 2:
      k.line([(x * 0.7, 0.55), (x * 0.65, 0.63)], g["hay_dk"], 3)
  k.put(k.box(0.38, 0, 0.5, 0.15, amp=1), g["palisade"], g["palisade_dk"])  # rain barrel
  for y in (0.035, 0.115):
    k.line([(0.38, y), (0.5, y)], width=3)


def _townhouse(canvas, ax, ay, s, rng):
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.3)
  k.put(k.box(0.17, 0.72, 0.26, 0.98), g["stone"], g["stone_dk"])
  body = k.box(-0.36, 0, 0.36, 0.6)
  k.put(body, g["stone"], g["stone_dk"])
  segs = []
  for y in [0.08 * i for i in range(1, 8)]:  # rough coursed stonework
    segs.append([(-0.36, y), (0.36, y)])
    x = -0.36 + rng.uniform(0.04, 0.1)
    while x < 0.34:
      segs.append([(x, y - 0.08), (x, y)])
      x += rng.uniform(0.1, 0.16)
  k.fill(clip(k.lines(segs, 3), body), g["stone_dk"])
  for i in range(6):  # quoins
    y, w = i * 0.1, (0.09 if i % 2 else 0.06)
    for side in (-1, 1):
      k.put(k.box(side * 0.36, y, side * (0.36 - w), y + 0.1, amp=0.6), g["wall"], g["wall_dk"])
  roofc = g["roofs"][0]
  roof = k.poly([(-0.43, 0.58), (-0.26, 0.86), (0.26, 0.86), (0.43, 0.58)])
  k.put(roof, roofc, bm.shade_of(roofc, 0.78))
  k.fill(clip(k.lines([[(-0.5, y), (0.5, y)] for y in (0.66, 0.74, 0.81)], 3), roof), bm.shade_of(roofc, 0.78))
  k.put(k.box(-0.11, -0.02, 0.11, 0.015, amp=0.8), g["stone"], g["stone_dk"])
  k.put(k.arch(-0.07, 0.07, 0.015, 0.25), g["timber"])
  k.line([(0, 0.02), (0, 0.24)], width=3)
  for x in (-0.22, 0.22):
    k.window(x - 0.055, 0.1, x + 0.055, 0.22)
  for x in (-0.24, 0, 0.24):
    k.window(x - 0.055, 0.36, x + 0.055, 0.5)
  k.put(k.box(-0.31, 0.32, -0.17, 0.36, amp=0.6), g["timber"])  # flower box
  for x in (-0.29, -0.255, -0.22, -0.19):
    k.put(k.oval(x, 0.375, 0.02, 0.018, amp=0.4), g["blossom"])


def _straw_hut(canvas, ax, ay, s, rng):
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.2)
  body = k.poly([(-0.3, 0), (0.3, 0), (0.32, 0.17), (0.3, 0.3), (-0.3, 0.3), (-0.32, 0.17)], amp=2)
  k.put(body, g["hay"], g["hay_dk"])
  bundles = [[(x, 0.0), (x + 0.008, 0.3)] for x in [-0.27 + i * 0.06 for i in range(10)]]
  k.fill(clip(k.lines(bundles, 3), body), g["hay_dk"])
  k.fill(clip(k.lines([[(-0.4, 0.15), (0.4, 0.15)]], 6), body), g["palisade_dk"])  # binding cord
  k.put(k.arch(-0.085, 0.085, 0, 0.24), g["lm_cave"])
  k.put(k.poly([(-0.085, 0.17), (-0.01, 0.17), (-0.03, 0.08), (-0.085, 0.02)], amp=0.6, sub=1), g["banner"])  # curtain
  roof = k.poly([(-0.43, 0.25), (-0.3, 0.42), (-0.13, 0.57), (0, 0.63), (0.13, 0.57), (0.3, 0.42), (0.43, 0.25)], amp=3)
  k.put(roof, g["hay"], g["hay_dk"], lighten(g["hay"], 0.3))
  for i in range(11):  # shaggy fringe + a few strokes up the roof
    x = -0.39 + i * 0.078
    k.line([(x, 0.28), (x - 0.008, 0.235)], g["hay_dk"], 3)
    if i % 3 == 1:
      k.line([(x * 0.75, 0.36), (x * 0.55, 0.47)], g["hay_dk"], 3)
  k.line([(-0.025, 0.61), (-0.045, 0.69)], g["hay_dk"], 4)  # tuft tied off at the top
  k.line([(0.0, 0.62), (0.0, 0.71)], g["hay_dk"], 4)
  k.line([(0.025, 0.61), (0.045, 0.69)], g["hay_dk"], 4)
  k.line([(-0.04, 0.615), (0.04, 0.615)], g["palisade_dk"], 5)
  sheaf = k.poly([(0.36, 0), (0.46, 0), (0.44, 0.1), (0.48, 0.17), (0.34, 0.17), (0.38, 0.1)], amp=1)
  k.put(sheaf, g["hay"], g["hay_dk"])
  k.line([(0.37, 0.09), (0.45, 0.09)], g["palisade_dk"], 4)


def _manor(canvas, ax, ay, s, rng):
  """Capital hall: dressed stone with brick chimneys, brick window arches and
  a brick string course; pale stone columns and pediment; patina dome."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.5, 1.2)
  stone, stone_dk, trim, trim_dk = g["stone"], g["stone_dk"], g["marble"], g["marble_dk"]

  def masonry(m, x0, x1, y0, y1):
    segs = []
    for row, y in enumerate([y0 + 0.06 * i for i in range(1, int((y1 - y0) / 0.06) + 1)]):
      segs.append([(x0, y), (x1, y)])
      x = x0 + (0.04 if row % 2 else 0.09)
      while x < x1:
        segs.append([(x, y - 0.06), (x, y)])
        x += 0.12
    k.fill(clip(k.lines(segs, 2), m), stone_dk)

  def arched_window(x0, y0, x1, y1):
    k.put(k.arch(x0 - 0.016, x1 + 0.016, y0, y1 + 0.016, amp=0.6), g["brick"], g["brick_dk"])
    k.window(x0, y0, x1, y1, arched=True)

  for side in (-1, 1):
    k.put(k.box(side * 0.43, 0.46, side * 0.36, 0.62), g["brick"], g["brick_dk"])  # chimney stacks
    k.put(k.box(side * 0.445, 0.6, side * 0.345, 0.63, amp=0.5), stone, stone_dk)
    wing = k.box(side * 0.5, 0.04, side * 0.22, 0.42)
    k.put(wing, stone, stone_dk)
    masonry(wing, -0.5, 0.5, 0.04, 0.42)
    k.put(k.poly([(side * 0.53, 0.41), (side * 0.47, 0.52), (side * 0.22, 0.52), (side * 0.22, 0.41)]),
          g["guild_roof"], g["guild_roof_dk"])
    k.put(k.box(side * 0.51, 0.375, side * 0.22, 0.405, amp=0.5), g["brick"], g["brick_dk"])  # string course
    for x in (0.29, 0.39):
      for y0 in (0.09, 0.235):
        arched_window(side * x - 0.03, y0, side * x + 0.03, y0 + 0.105)
    for i in range(4):  # pale quoins on the wing corners
      y = 0.04 + i * 0.085
      k.put(k.box(side * 0.5, y, side * (0.5 - (0.04 if i % 2 else 0.028)), y + 0.085, amp=0.5), trim, trim_dk)
  block = k.box(-0.24, 0.04, 0.24, 0.62)
  k.put(block, stone, stone_dk)
  masonry(block, -0.24, 0.24, 0.04, 0.62)
  drum = k.box(-0.13, 0.6, 0.13, 0.7)
  k.put(drum, stone, stone_dk)
  for x in (-0.07, 0, 0.07):
    arched_window(x - 0.018, 0.62, x + 0.018, 0.675)
  dome = k.oval(0, 0.695, 0.145, 0.16, amp=0.8, a1=math.pi)
  k.put(dome, g["banner"], bm.shade_of(g["banner"], 0.72), lighten(g["banner"], 0.3))
  k.line([(-0.07, 0.83), (-0.1, 0.71)], bm.shade_of(g["banner"], 0.72), 3)
  k.line([(0.07, 0.83), (0.1, 0.71)], bm.shade_of(g["banner"], 0.72), 3)
  k.line([(0, 0.85), (0, 0.95)], width=5)
  k.put(k.oval(0, 0.88, 0.022, 0.022, amp=0.3), g["banner_lt"])
  k.put(k.box(-0.25, 0.555, 0.25, 0.585, amp=0.5), g["brick"], g["brick_dk"])  # string course under the drum
  k.put(k.poly([(-0.25, 0.47), (0, 0.6), (0.25, 0.47)], amp=1), trim, trim_dk)  # pediment
  k.line([(-0.18, 0.49), (0, 0.565), (0.18, 0.49), (-0.18, 0.49)], trim_dk, 3)
  k.put(k.oval(0, 0.515, 0.022, 0.022, amp=0.3), g["banner_lt"])
  k.put(k.box(-0.25, 0.43, 0.25, 0.48, amp=0.6), trim, trim_dk)
  k.put(k.arch(-0.072, 0.072, 0.05, 0.285, amp=0.6), g["brick"], g["brick_dk"])
  k.put(k.arch(-0.055, 0.055, 0.05, 0.27), g["timber"])
  k.line([(0, 0.06), (0, 0.26)], width=3)
  for x in (-0.19, -0.1, 0.1, 0.19):  # portico columns
    k.put(k.box(x - 0.022, 0.06, x + 0.022, 0.42, amp=0.6), trim, trim_dk)
    k.put(k.box(x - 0.034, 0.41, x + 0.034, 0.44, amp=0.4), trim)
    k.put(k.box(x - 0.034, 0.045, x + 0.034, 0.07, amp=0.4), trim)
  k.put(k.box(-0.52, 0, 0.52, 0.045, amp=1), stone, stone_dk)
  k.put(k.box(-0.27, 0, 0.27, 0.025, amp=0.6), trim, trim_dk)
  for side in (-1, 1):  # topiaries in pots
    x = side * 0.6
    k.put(k.oval(x, 0.15, 0.065, 0.075, amp=1.2), g["bush"], g["leaf_dk"], g["leaf_lt"])
    k.put(k.poly([(x - 0.05, 0.08), (x + 0.05, 0.08), (x + 0.035, 0), (x - 0.035, 0)], amp=0.6),
          g["roofs"][2], bm.shade_of(g["roofs"][2], 0.78))


# ---------------------------------------------------------------- cave
CAVE_SHAPES = (
  [(-0.46, 0), (-0.4, 0.16), (-0.26, 0.32), (-0.06, 0.4), (0.16, 0.37), (0.34, 0.26), (0.45, 0.1), (0.48, 0)],
  [(-0.48, 0), (-0.44, 0.2), (-0.32, 0.4), (-0.14, 0.52), (0.04, 0.5), (0.2, 0.56), (0.36, 0.42), (0.46, 0.22),
   (0.5, 0)],
  [(-0.5, 0), (-0.46, 0.3), (-0.38, 0.5), (-0.28, 0.58), (-0.2, 0.72), (-0.08, 0.66), (0.04, 0.78), (0.16, 0.64),
   (0.3, 0.68), (0.4, 0.48), (0.47, 0.26), (0.5, 0)],
  [(-0.5, 0), (-0.48, 0.3), (-0.4, 0.46), (-0.34, 0.62), (-0.22, 0.74), (-0.14, 0.88), (-0.04, 0.8), (0.06, 0.92),
   (0.18, 0.76), (0.3, 0.7), (0.38, 0.54), (0.46, 0.34), (0.5, 0)],
)
CAVE_MOUTHS = ((0.13, 0.21), (0.16, 0.28), (0.19, 0.36), (0.22, 0.44))  # half-width, height


def paint_cave(canvas, ax, ay, s, rng, tier):
  """1 burrow in a rock mound, 2 rocky outcrop + boulders, 3 crag with fangs,
  vines and a pine, 4 cliff with torches and glowing eyes."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.3)
  pts = CAVE_SHAPES[tier - 1]
  rocky(k, pts)
  mw, mh = CAVE_MOUTHS[tier - 1]
  dx = 0.04
  k.put(k.arch(dx - mw, dx + mw, 0, mh), g["lm_cave"])
  k.fill(k.arch(dx - mw * 0.6, dx + mw * 0.6, 0, mh * 0.72, amp=0.5), bm.shade_of(g["lm_cave"], 0.6))
  if tier >= 3:  # fangs hanging from the mouth, two rising from the floor
    for f in (-0.6, -0.25, 0.1, 0.45):
      x = f * mw
      y = mh - mw + math.sqrt(max(0.0, mw * mw - x * x)) - 0.01
      k.put(k.poly([(dx + x - 0.022, y), (dx + x, y - 0.07), (dx + x + 0.022, y)], amp=0.4, sub=1), g["rock_lt"])
    for f in (-0.75, 0.7):
      k.put(k.poly([(dx + f * mw - 0.02, 0), (dx + f * mw, 0.06), (dx + f * mw + 0.02, 0)], amp=0.4, sub=1),
            g["rock_lt"])
  if tier >= 4:  # something lives in there
    for x in (dx - 0.045, dx + 0.045):
      k.put(k.oval(x, mh * 0.45, 0.022, 0.014, amp=0.2), g["flame_lt"])
  if tier >= 3:  # vine down the left of the mouth
    x0 = dx - mw - 0.03
    vine = [(x0 + 0.02 * math.sin(i * 1.3), mh + 0.1 - i * 0.05) for i in range(6)]
    k.line(vine, g["leaf_dk"], 5)
    for i, (x, y) in enumerate(vine[1:]):
      k.put(k.oval(x + (0.02 if i % 2 else -0.02), y, 0.022, 0.014, amp=0.3), g["leaf"])
  if tier >= 2:
    bm.paint_rock(canvas, *k.at(-0.36, 0), s * 0.14, rng)
    bm.paint_rock(canvas, *k.at(0.42, 0), s * 0.1, rng)
    bm.paint_bush(canvas, *k.at(pts[3][0] + 0.03, pts[3][1] - 0.03), s * 0.13, rng)
  if tier >= 3:
    bm.paint_pine(canvas, *k.at(pts[-4][0], pts[-4][1] - 0.04), s * 0.16, rng)
  if tier >= 4:
    bm.paint_pine(canvas, *k.at(pts[3][0] - 0.04, pts[3][1] - 0.04), s * 0.14, rng)
    for side in (-1, 1):  # torches, clear of the vine
      x = dx + side * (mw + 0.12)
      bm._ink_line(canvas, [k.at(x, 0), k.at(x, 0.25)], g["timber"], bm.u(7))
      flame = [(x - 0.03, 0.265), (x - 0.038, 0.3), (x - 0.02, 0.335), (x - 0.008, 0.322), (x, 0.375),
               (x + 0.012, 0.335), (x + 0.03, 0.348), (x + 0.036, 0.3), (x + 0.028, 0.262), (x, 0.252)]
      k.put(k.poly(flame, amp=0.5, sub=1), g["flame"])
      k.fill(k.poly([(x - 0.016, 0.27), (x - 0.012, 0.3), (x, 0.33), (x + 0.014, 0.3), (x + 0.014, 0.27)], amp=0),
             g["flame_lt"])
      k.put(k.box(x - 0.026, 0.235, x + 0.026, 0.265, amp=0.4), g["timber"])


# ---------------------------------------------------------------- gathering nodes
def paint_mineral(canvas, ax, ay, s, rng, tier):
  """Mining: a boulder split open by ore crystals, with copper flecks."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.3)
  for x, y, w, h, deg in ((-0.13, 0.18, 0.065, 0.3, 18), (0.05, 0.2, 0.085, 0.42, -4), (0.21, 0.16, 0.06, 0.24, -24),
                          (-0.27, 0.1, 0.04, 0.15, 35)):
    tip = h + w * 0.9
    prism = rotate([(-w, 0), (-w, h), (0, tip), (w, h), (w, 0)], deg, x, y)
    m = k.poly(prism, amp=0.6, sub=2)
    k.put(m, g["ore"])
    left = rotate([(-w, 0), (-w, h), (0, tip), (-w / 3, h), (-w / 3, 0)], deg, x, y)
    right = rotate([(w / 3, 0), (w / 3, h), (0, tip), (w, h), (w, 0)], deg, x, y)
    k.fill(clip(k.poly(left, amp=0), m), g["ore_lt"])
    k.fill(clip(k.poly(right, amp=0), m), g["ore_dk"])
    for side in (-1, 1):
      k.line(rotate([(side * w / 3, 0), (side * w / 3, h), (0, tip)], deg, x, y), width=3)
  rocky(k, [(-0.42, 0), (-0.4, 0.13), (-0.3, 0.24), (-0.15, 0.27), (0.0, 0.25), (0.15, 0.29), (0.3, 0.22),
            (0.4, 0.11), (0.43, 0)])
  for x, y in ((-0.25, 0.08), (-0.1, 0.14), (0.18, 0.07), (0.28, 0.15), (0.04, 0.05)):
    k.put(k.oval(x, y, 0.028, 0.02, amp=0.6), g["vein"], bm.shade_of(g["vein"], 0.75))
  shard = rotate([(-0.025, 0), (-0.025, 0.06), (0, 0.09), (0.025, 0.06), (0.025, 0)], -40, 0.47, 0)
  k.put(k.poly(shard, amp=0.4, sub=1), g["ore"], g["ore_dk"])


def paint_fishing(canvas, ax, ay, s, rng, tier):
  """Fishing: a pool with a fish leaping out, reeds, a bobber and a mooring post."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.2)
  k.put(k.box(0.37, 0.02, 0.43, 0.28, amp=0.8), g["palisade"], g["palisade_dk"])
  k.line([(0.37, 0.2), (0.43, 0.2)], g["hay"], 6)
  k.put(k.oval(0, 0.1, 0.46, 0.095, amp=1.5, n=28), g["water"], g["water_dk"], g["water_lt"])
  for x, y, w in ((-0.25, 0.12, 0.07), (0.05, 0.06, 0.09), (0.28, 0.13, 0.05)):
    k.line([(x - w, y), (x + w, y)], g["water_lt"], 3)
  x0, y0 = k.at(0.2, 0.12)  # splash ring where the fish left the water
  rx, ry = 0.085 * s, 0.022 * s
  k.d.ellipse([x0 - rx, y0 - ry, x0 + rx, y0 + ry], outline=g["water_lt"], width=max(1, int(bm.u(4))))
  fx, fy, deg = 0.04, 0.36, -35
  body = [(math.cos(a) * 0.12, math.sin(a) * 0.05) for a in (2 * math.pi * i / 16 for i in range(16))]
  k.put(k.poly(rotate([(0.1, 0), (0.19, 0.06), (0.17, 0), (0.19, -0.06)], deg, fx, fy), amp=0.5, sub=2),
        g["fish"], g["fish_dk"])
  k.put(k.poly(rotate(body, deg, fx, fy), amp=0.5, sub=2), g["fish"], g["fish_dk"], lighten(g["fish"], 0.35))
  k.put(k.poly(rotate([(-0.02, 0.04), (0.03, 0.085), (0.05, 0.04)], deg, fx, fy), amp=0.4, sub=1), g["fish_dk"])
  ex, ey = rotate([(-0.08, 0.012)], deg, fx, fy)[0]
  k.put(k.oval(ex, ey, 0.012, 0.012, amp=0), g["ink"])
  for x, y, r in ((0.16, 0.2, 0.018), (0.23, 0.24, 0.014), (0.11, 0.26, 0.012)):
    k.put(k.oval(x, y, r, r, amp=0.2), g["water_lt"])
  bob = k.oval(-0.12, 0.13, 0.028, 0.028, amp=0.3)
  k.put(bob, g["stem"])
  k.fill(clip(k.box(-0.2, 0.0, -0.04, 0.13, amp=0), bob), g["cap"])
  bm.paint_reeds(canvas, *k.at(-0.38, 0.06), s * 0.33, rng)


def glow(k, x, y, r, colour, halo=2.4, alpha=0.35, ink=True):
  """Magic light, still flat: a see-through halo disc behind a solid core."""
  k.fill(k.oval(x, y, r * halo, r * halo, amp=0).point(lambda v: int(v * alpha)), colour)
  core = k.oval(x, y, r, r, amp=0.2)
  if ink:
    k.put(core, colour)
  else:
    k.fill(core, lighten(colour, 0.5))


def motes(k, rng, x0, x1, y0, y1, colour, n=7):
  for _ in range(n):
    glow(k, rng.uniform(x0, x1), rng.uniform(y0, y1), rng.uniform(0.008, 0.013), colour, halo=2.6, ink=False)


def paint_treenode(canvas, ax, ay, s, rng, tier):
  """Forestry: a fey tree hung with glowing fruit, a rune on the trunk, a
  chopping stump with an axe bitten into it."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.4)
  tx, ts = -0.06, 0.62
  bm._tree(canvas, *k.at(tx, 0), s * ts, rng, g["fey"], g["fey_dk"], g["fey_lt"], trunk=0.09)
  rune = [[(tx, 0.07), (tx, 0.21)], [(tx, 0.15), (tx - 0.03, 0.19)], [(tx, 0.15), (tx + 0.03, 0.19)],
          [(tx - 0.025, 0.09), (tx + 0.025, 0.09)]]
  k.fill(k.oval(tx, 0.14, 0.05, 0.09, amp=0).point(lambda v: int(v * 0.3)), g["glow"])
  for seg in rune:
    k.line(seg, g["glow"], 4)
  cy = ts * 0.9
  for dx, dy in ((-0.21, -0.14), (-0.06, -0.24), (0.11, -0.19), (0.2, -0.04), (-0.1, -0.02)):
    x, y = tx + dx, cy + dy
    k.line([(x, y + 0.05), (x, y + 0.02)], width=3)
    glow(k, x, y, 0.024, g["glow"])
  motes(k, rng, tx - 0.4, tx + 0.45, 0.15, 0.95, g["glow"])
  bm.paint_stump(canvas, *k.at(0.17, 0), s * 0.24, rng)
  hx, hy = 0.17, 0.1
  k.pole([(hx, hy), (hx + 0.15, hy + 0.22)], g["palisade"])
  k.put(k.poly([(hx - 0.07, hy + 0.035), (hx + 0.02, hy + 0.06), (hx + 0.035, hy - 0.005), (hx - 0.06, hy - 0.035)],
               amp=0.6), g["rock_lt"], g["rock_dk"])


def paint_herb(canvas, ax, ay, s, rng, tier):
  """Herbalism: lantern-flowers drooping glowing bulbs over a fey leaf clump,
  fiddlehead curls, glowing toadstools and drifting pollen."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.4)
  stalks = (((-0.02, 0.05), (-0.12, 0.5), (-0.2, 0.62), (-0.27, 0.56)),
            ((0.01, 0.05), (0.03, 0.62), (0.1, 0.74), (0.17, 0.68)),
            ((0.03, 0.05), (0.16, 0.4), (0.26, 0.47), (0.31, 0.4)))
  for st in stalks:
    k.pole(list(st), g["fey_dk"])
  for side in (-1, 1):  # fiddlehead curls
    cx0, cy0 = side * 0.2, 0.3
    spiral = [(cx0 + side * math.cos(t) * 0.012 * t, cy0 + math.sin(t) * 0.012 * t) for t in [i * 0.5 for i in range(14)]]
    k.pole([(side * 0.06, 0.03), (side * 0.16, 0.18), (cx0 + side * 0.08, cy0 - 0.02)] + spiral[::-1], g["fey_dk"])
  for i in range(7):
    deg = -66 + i * 22 + rng.uniform(-6, 6)
    ln, w = rng.uniform(0.3, 0.4) * (1 - abs(deg) / 200), 0.075
    side = [(w * math.sin(math.pi * t / 8), ln * t / 8) for t in range(9)]
    leaf = rotate(side + [(-x, y) for x, y in reversed(side[1:-1])], deg, (i - 3) * 0.03, 0)
    k.put(k.poly(leaf, amp=0.6, sub=1), g["fey"], g["fey_dk"], g["fey_lt"])
    k.line(rotate([(0, 0.02), (0, ln * 0.8)], deg, (i - 3) * 0.03, 0), g["fey_dk"], 3)
  for st in stalks:  # bulbs hang from each stalk tip, capped by a sepal
    x, y = st[-1]
    by = y - 0.065
    k.fill(k.oval(x, by, 0.09, 0.09, amp=0).point(lambda v: int(v * 0.3)), g["wisp"])
    bulb = [(x + math.sin(a) * 0.036 * (1 - 0.35 * math.cos(a)), by + math.cos(a) * 0.045) for a in
            (2 * math.pi * i / 16 for i in range(16))]
    k.put(k.poly(bulb, amp=0.4, sub=1), g["wisp"], None, lighten(g["wisp"], 0.6))
    k.put(k.poly([(x - 0.03, y - 0.03), (x, y + 0.005), (x + 0.03, y - 0.03), (x, y - 0.045)], amp=0.3, sub=1),
          g["fey_dk"])
  for x, h, r in ((-0.36, 0.11, 0.06), (-0.25, 0.07, 0.042), (0.36, 0.09, 0.052)):  # glowing toadstools
    k.put(k.box(x - r * 0.3, 0, x + r * 0.3, h, amp=0.3), g["stem"])
    k.fill(k.oval(x, h, r * 2.2, r * 2.2, amp=0).point(lambda v: int(v * 0.25)), g["wisp"])
    k.put(k.oval(x, h, r, r * 0.8, amp=0.3, a1=math.pi), g["wisp"], None, lighten(g["wisp"], 0.6))
  motes(k, rng, -0.42, 0.42, 0.2, 0.9, g["wisp"], n=9)


def paint_tracks(canvas, ax, ay, s, rng, tier):
  """Hunting: a fallen tree, its root plate torn up, lying against a dark
  bush. Insect eyes peer out of the shadow between them, antennae poke over
  the leaves."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.3)
  bush = k.oval(-0.07, 0, 0.34, 0.4, amp=0, a1=math.pi)
  for i in range(9):
    a = math.pi * i / 8
    r = rng.uniform(0.1, 0.13)
    y = max(r, 0.05 + math.sin(a) * 0.38)  # never below the ground line, or the canvas clips it
    bush = ImageChops.lighter(bush, k.oval(-0.07 + math.cos(a) * 0.34, y, r, r, amp=1))
  for side in (-1, 1):  # antennae over the leaves
    x0 = 0.02 + side * 0.03
    k.line([(x0, 0.44), (x0 + side * 0.03, 0.55), (x0 + side * 0.09, 0.62), (x0 + side * 0.13, 0.6)], width=5)
  k.put(bush, g["oak"], g["oak_dk"], g["oak_lt"])
  peek = k.oval(-0.27, 0.42, 0.06, 0.035, amp=0.6)  # a gap in the leaves, watching
  k.put(peek, g["lm_cave"])
  for x in (-0.29, -0.25):
    glow(k, x, 0.42, 0.009, g["flame_lt"], halo=2.2, ink=False)
  hollow = k.poly([(-0.36, 0.04), (-0.33, 0.2), (-0.2, 0.33), (-0.02, 0.35), (0.14, 0.29), (0.22, 0.15),
                   (0.24, 0.04)], amp=2)
  k.put(hollow, g["lm_cave"])
  for x, y, r, deg in ((-0.04, 0.25, 0.026, 12), (0.1, 0.21, 0.018, 8), (-0.21, 0.22, 0.015, -10)):
    for side in (-1, 1):
      ex = x + side * r * 1.6
      eye = rotate([(math.cos(a) * r, math.sin(a) * r * 0.55) for a in (2 * math.pi * i / 12 for i in range(12))],
                   -side * deg, ex, y)
      k.fill(k.oval(ex, y, r * 1.5, r * 1.1, amp=0).point(lambda v: int(v * 0.22)), g["flame_lt"])
      k.fill(k.poly(eye, amp=0), g["flame_lt"])
      if r > 0.02:  # the big one has slit pupils
        k.line([(ex, y - r * 0.45), (ex, y + r * 0.45)], width=3)
  lumps = [(0.36 + math.cos(a) * 0.12 * f, 0.17 + math.sin(a) * 0.17 * f)
           for a, f in ((2 * math.pi * i / 14, rng.uniform(0.82, 1.1)) for i in range(14))]
  k.put(k.poly(lumps, amp=3), g["earth"], g["earth_dk"])  # torn-up root plate, clods and all
  for x, y in ((0.3, 0.27), (0.42, 0.08), (0.43, 0.24)):
    k.put(k.oval(x, y, 0.018, 0.014, amp=0.3), g["rock_lt"], g["rock_dk"])
  for a in (0.5, 1.6, 2.5, 3.9, 5.0):  # roots curling across the clod
    pts = [(0.36 + math.cos(a + 0.35 * f) * 0.1 * f, 0.17 + math.sin(a + 0.35 * f) * 0.14 * f) for f in (0.2, 0.6, 1.0)]
    bm._ink_line(canvas, [k.at(*p) for p in pts], g["trunk"], bm.u(5))
  for a in (-0.4, 0.3, 1.0, 2.4, 3.3):  # roots dangling past the plate
    x0, y0 = 0.36 + math.cos(a) * 0.11, 0.17 + math.sin(a) * 0.16
    bm._ink_line(canvas, [k.at(x0, y0), k.at(x0 + math.cos(a) * 0.07, y0 + math.sin(a) * 0.05 - 0.02)],
                 g["trunk"], bm.u(5))
  a, b, t = (-0.44, 0.065), (0.33, 0.13), 0.065
  ln = math.hypot(b[0] - a[0], b[1] - a[1])
  nx, ny = -(b[1] - a[1]) / ln * t, (b[0] - a[0]) / ln * t
  log = k.poly([(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)])
  k.put(k.poly([(-0.3, 0.12), (-0.36, 0.24), (-0.33, 0.255), (-0.26, 0.13)], amp=0.6, sub=1), g["trunk"])  # snag
  k.put(log, g["trunk"], bm.shade_of(g["trunk"], 0.72))
  for f, off in ((0.15, 0.3), (0.35, -0.35), (0.55, 0.2), (0.75, -0.25)):  # bark grain
    x = a[0] + (b[0] - a[0]) * f
    y = a[1] + (b[1] - a[1]) * f + off * t
    k.line([(x - 0.06, y - 0.004), (x + 0.06, y + 0.006)], bm.shade_of(g["trunk"], 0.72), 3)
  k.put(k.poly([(a[0] - nx * 1.05, a[1] - ny * 1.05), (a[0] - 0.035, a[1] - 0.02), (a[0] - 0.012, a[1] + 0.01),
                (a[0] - 0.04, a[1] + 0.035), (a[0] + nx * 1.05, a[1] + ny * 1.05), (a[0] + 0.02, a[1])],
               amp=0.5, sub=1), g["stump_top"])  # snapped end
  for f in (0.25, 0.6):  # moss on top of the log
    x = a[0] + (b[0] - a[0]) * f
    y = a[1] + (b[1] - a[1]) * f + t * 0.85
    k.put(k.oval(x, y, 0.06, 0.022, amp=0.6), g["bush"], g["leaf_dk"])
  for x in (-0.47, -0.43, 0.2, 0.25, 0.49):  # grass tufts
    k.line([(x, 0.0), (x + rng.uniform(-0.03, 0.03), rng.uniform(0.07, 0.12))], g["reed"], 4)


# ---------------------------------------------------------------- faction strongholds
def merlons(k, x0, x1, y, colour, shade, w=0.045, h=0.05, gap=0.03):
  """Crenellations along a wall top, sat on y."""
  x = x0
  while x + w <= x1 + 1e-6:
    k.put(k.box(x, y - 0.005, x + w, y + h, amp=0.5), colour, shade)
    x += w + gap


def masonry(k, m, x0, x1, y0, y1, colour, course=0.06):
  segs = []
  for row in range(1, int((y1 - y0) / course) + 1):
    y = y0 + course * row
    segs.append([(x0, y), (x1, y)])
    x = x0 + (0.04 if row % 2 else 0.09)
    while x < x1:
      segs.append([(x, y - course), (x, y)])
      x += 0.12
  k.fill(clip(k.lines(segs, 2), m), colour)


def hanging_banner(k, x, y_top, w, h, colour, emblem):
  k.put(k.poly([(x - w, y_top), (x + w, y_top), (x + w, y_top - h), (x, y_top - h + w * 0.8), (x - w, y_top - h)],
               amp=0.6), colour, bm.shade_of(colour, 0.78))
  k.line([(x - w - 0.01, y_top), (x + w + 0.01, y_top)], bm.G["timber"], 5)
  emblem(k, x, y_top - h * 0.42, w * 0.6)


def cat_emblem(k, x, y, r):
  m = k.oval(x, y, r, r * 0.85, amp=0)
  for side in (-1, 1):
    m = ImageChops.lighter(m, k.poly([(x + side * r * 0.95, y + r * 0.2), (x + side * r * 0.85, y + r * 1.25),
                                      (x + side * r * 0.25, y + r * 0.7)], amp=0))
  k.fill(m, bm.G["stem"])


def feather_emblem(k, x, y, r):
  side = [(r * 0.45 * math.sin(math.pi * t / 6), r * 2.2 * t / 6 - r * 1.1) for t in range(7)]
  pts = rotate(side + [(-px, py) for px, py in reversed(side[1:-1])], -25, x, y)
  k.fill(k.poly(pts, amp=0), bm.G["stem"])
  k.line(rotate([(0, -r * 1.3), (0, r * 1.0)], -25, x, y), bm.shade_of(bm.G["stem"], 0.7), 3)


def paint_marquise_keep(canvas, ax, ay, s, rng, tier):
  """Marquisate keep: square stone keep behind a crenellated curtain wall,
  round towers with cat-orange cones, a gatehouse with a raised portcullis,
  cat banners."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.25)
  orange = g["cat_banner"]
  stone, stone_dk = g["stone"], g["stone_dk"]
  roof, roof_dk = bm.shade_of(orange, 0.9), bm.shade_of(orange, 0.68)
  keep = k.box(-0.15, 0.3, 0.15, 0.84)
  k.put(keep, stone, stone_dk)
  masonry(k, keep, -0.15, 0.15, 0.3, 0.84, stone_dk)
  merlons(k, -0.15, 0.15, 0.84, stone, stone_dk)
  k.pole([(0.1, 0.89), (0.1, 1.0)])
  k.put(k.poly([(0.1, 1.0), (0.21, 0.97), (0.1, 0.94)], amp=0.4, sub=1), orange)
  for x in (-0.07, 0.07):
    k.window(x - 0.018, 0.73, x + 0.018, 0.81, arched=True)
  hanging_banner(k, 0, 0.71, 0.06, 0.18, orange, cat_emblem)
  for side in (-1, 1):  # round towers
    x0, x1 = side * 0.44, side * 0.29
    tower = k.box(x0, 0, x1, 0.6)
    k.put(tower, stone, stone_dk)
    masonry(k, tower, -0.44 if side < 0 else 0.29, -0.29 if side < 0 else 0.44, 0, 0.6, stone_dk)
    xm = side * 0.365
    k.put(k.poly([(xm - 0.095, 0.585), (xm, 0.83), (xm + 0.095, 0.585)], amp=1), roof, roof_dk)
    k.pole([(xm, 0.83), (xm, 0.92)])
    k.put(k.poly([(xm, 0.92), (xm + 0.09, 0.895), (xm, 0.87)], amp=0.4, sub=1), orange)
    for y in (0.2, 0.4):  # arrow slits
      k.put(k.box(xm - 0.012, y, xm + 0.012, y + 0.07, amp=0.3), g["lm_cave"])
  wall = k.box(-0.29, 0, 0.29, 0.38)
  k.put(wall, stone, stone_dk)
  masonry(k, wall, -0.29, 0.29, 0, 0.38, stone_dk)
  merlons(k, -0.29, -0.11, 0.38, stone, stone_dk)
  merlons(k, 0.13, 0.29, 0.38, stone, stone_dk)
  for x in (-0.2, 0.2):
    hanging_banner(k, x, 0.35, 0.045, 0.18, orange, cat_emblem)
  gate = k.box(-0.11, 0, 0.11, 0.47)
  k.put(gate, stone, stone_dk)
  masonry(k, gate, -0.11, 0.11, 0, 0.47, stone_dk)
  merlons(k, -0.11, 0.11, 0.47, stone, stone_dk, w=0.04, gap=0.02)
  door = k.arch(-0.07, 0.07, 0, 0.27)
  k.put(door, g["lm_cave"])
  grid = [[(x, 0), (x, 0.3)] for x in (-0.045, -0.015, 0.015, 0.045)] + [[(-0.08, y), (0.08, y)] for y in (0.15, 0.2, 0.25)]
  k.fill(clip(k.lines(grid, 4), door), g["rock_dk"])
  k.put(k.box(-0.12, 0.33, 0.12, 0.36, amp=0.4), orange, roof_dk)  # gate lintel stripe
  k.put(k.box(-0.47, 0, 0.47, 0.035, amp=1), stone_dk)


def paint_eyrie_roost(canvas, ax, ay, s, rng, tier):
  """Eyrie castle-roost: a great tree carrying a timber deck, a hall and two
  towers under bird-blue roofs, perches, and a woven nest crowning the top."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.3, 1.3)
  blue = g["bird_banner"]
  blue_dk, blue_lt = bm.shade_of(blue, 0.72), lighten(blue, 0.3)
  bark, bark_dk = g["trunk"], bm.shade_of(g["trunk"], 0.72)
  for side in (-1, 1):  # perch branches under the deck, with leaf tufts
    x = side * 0.09
    bm._ink_line(canvas, [k.at(x, 0.3), k.at(side * 0.3, 0.37), k.at(side * 0.46, 0.34)], bark, bm.u(10))
    k.put(k.oval(side * 0.48, 0.35, 0.065, 0.045, amp=1), g["oak"], g["oak_dk"], g["oak_lt"])
  trunk = k.poly([(-0.24, 0), (-0.13, 0.05), (-0.09, 0.25), (-0.1, 0.5), (0.1, 0.5), (0.09, 0.25), (0.13, 0.05),
                  (0.24, 0), (0.08, 0.02), (0, 0.0), (-0.08, 0.02)], amp=2)
  k.put(trunk, bark, bark_dk)
  k.fill(clip(k.lines([[(-0.05, 0.05), (-0.03, 0.45)], [(0.03, 0.1), (0.05, 0.44)], [(-0.01, 0.2), (0.0, 0.35)]], 3),
              trunk), bark_dk)
  k.put(k.oval(0.0, 0.16, 0.04, 0.05, amp=0.5), g["lm_cave"])  # knot hole
  for side in (-1, 1):  # braces under the deck
    bm._ink_line(canvas, [k.at(side * 0.08, 0.3), k.at(side * 0.38, 0.47)], g["timber"], bm.u(7))
  deck = k.box(-0.44, 0.46, 0.44, 0.52, amp=1)
  k.put(deck, g["palisade"], g["palisade_dk"])
  k.fill(clip(k.lines([[(x, 0.46), (x, 0.52)] for x in [-0.4 + 0.08 * i for i in range(11)]], 3), deck), g["palisade_dk"])
  for side in (-1, 1):  # side towers
    xm = side * 0.33
    tower = k.box(xm - 0.07, 0.52, xm + 0.07, 0.8)
    k.put(tower, g["wall"], g["wall_dk"])
    for f in (-0.04, 0.04):
      k.line([(xm + f, 0.53), (xm + f, 0.79)], g["timber"], 6)
    k.window(xm - 0.025, 0.62, xm + 0.025, 0.71, arched=True)
    k.put(k.poly([(xm - 0.1, 0.785), (xm, 0.98), (xm + 0.1, 0.785)], amp=1), blue, blue_dk, blue_lt)
    k.line([(xm, 0.98), (xm, 1.06)], width=5)
    k.put(k.poly([(xm, 1.06), (xm + side * 0.09, 1.035), (xm, 1.01)], amp=0.4, sub=1), blue)
  k.put(k.box(-0.045, 0.82, 0.045, 0.98), g["wall"], g["wall_dk"])  # spire under the nest
  hall = k.box(-0.19, 0.52, 0.19, 0.74)
  k.put(hall, g["wall"], g["wall_dk"])
  for f in (-0.12, 0.12):
    k.line([(f, 0.53), (f, 0.73)], g["timber"], 6)
  k.line([(-0.19, 0.64), (-0.12, 0.64)], g["timber"], 6)
  k.line([(0.12, 0.64), (0.19, 0.64)], g["timber"], 6)
  k.put(k.arch(-0.055, 0.055, 0.52, 0.66), g["timber"])
  k.line([(0, 0.53), (0, 0.65)], width=3)
  for x in (-0.155, 0.155):
    k.window(x - 0.02, 0.58, x + 0.02, 0.68, arched=True)
  k.put(k.poly([(-0.25, 0.72), (-0.1, 0.88), (0.1, 0.88), (0.25, 0.72)]), blue, blue_dk, blue_lt)
  nest = k.oval(0, 1.0, 0.15, 0.075, amp=2, a0=math.pi, a1=2 * math.pi)
  nest = ImageChops.lighter(nest, k.box(-0.15, 0.995, 0.15, 1.025, amp=1.5))
  k.put(nest, g["hay_dk"], bm.shade_of(g["hay_dk"], 0.75))
  twigs = [[(-0.14 + 0.05 * i, 1.02), (-0.1 + 0.05 * i, 0.95)] for i in range(6)] + \
          [[(-0.12 + 0.05 * i, 0.95), (-0.15 + 0.05 * i, 1.01)] for i in range(6)]
  k.fill(clip(k.lines(twigs, 3), nest), g["palisade_dk"])
  for x in (-0.12, 0.12):  # stray twigs poking out of the rim
    k.line([(x, 1.0), (x + (0.07 if x > 0 else -0.07), 1.06)], g["palisade_dk"], 4)
  for x in (-0.33, 0.33):  # bird banners on the deck front
    hanging_banner(k, x, 0.5, 0.045, 0.17, blue, feather_emblem)
  hanging_banner(k, 0, 0.5, 0.05, 0.15, blue, feather_emblem)


def flame(k, x, y, r):
  """Campfire / brazier flame sitting on (x, y), r = half-width."""
  g = bm.G
  k.fill(k.oval(x, y + r * 1.2, r * 2.6, r * 2.4, amp=0).point(lambda v: int(v * 0.22)), g["flame_lt"])
  pts = [(x - r, y), (x - r * 1.2, y + r * 1.1), (x - r * 0.6, y + r * 2.0), (x - r * 0.25, y + r * 1.6), (x, y + r * 2.9),
         (x + r * 0.4, y + r * 1.9), (x + r * 0.9, y + r * 2.3), (x + r * 1.2, y + r * 1.1), (x + r, y)]
  k.put(k.poly(pts, amp=0.5, sub=1), g["flame"])
  k.fill(k.poly([(x - r * 0.5, y + r * 0.2), (x - r * 0.4, y + r * 1.1), (x, y + r * 1.8), (x + r * 0.45, y + r * 1.1),
                 (x + r * 0.5, y + r * 0.2)], amp=0), g["flame_lt"])


def pennant(k, x, y0, y1, colour, side=1):
  k.pole([(x, y0), (x, y1)])
  k.put(k.poly([(x, y1), (x + side * 0.09, y1 - 0.025), (x, y1 - 0.05)], amp=0.4, sub=1), colour)


def crate(k, x0, y0, x1, y1):
  g = bm.G
  k.put(k.box(x0, y0, x1, y1, amp=0.6), g["palisade"], g["palisade_dk"])
  k.line([(x0 + 0.01, y0 + 0.01), (x1 - 0.01, y1 - 0.01)], g["palisade_dk"], 4)
  k.line([(x0 + 0.01, y1 - 0.01), (x1 - 0.01, y0 + 0.01)], g["palisade_dk"], 4)


# ---------------------------------------------------------------- faction outposts
def paint_otter_tradepost(canvas, ax, ay, s, rng, tier):
  """Riverfolk trading post: a stall on stilts over the water, striped
  awning, crates of goods, a coin sign, a rowboat tied up alongside."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.3)
  otter = g["otter_banner"]
  k.put(k.oval(0, 0.07, 0.5, 0.07, amp=1.5, n=28), g["water"], g["water_dk"], g["water_lt"])
  for x, y, w in ((-0.36, 0.08, 0.06), (0.0, 0.05, 0.08), (0.2, 0.09, 0.04)):
    k.line([(x - w, y), (x + w, y)], g["water_lt"], 3)
  for x in (-0.32, -0.12, 0.08, 0.28):  # stilts
    k.put(k.box(x - 0.018, 0.04, x + 0.018, 0.2, amp=0.5), g["timber"])
  deck = k.box(-0.38, 0.18, 0.38, 0.23, amp=0.8)
  k.put(deck, g["palisade"], g["palisade_dk"])
  k.fill(clip(k.lines([[(x, 0.18), (x, 0.23)] for x in [-0.34 + 0.07 * i for i in range(11)]], 3), deck),
         g["palisade_dk"])
  hut = k.box(-0.3, 0.23, 0.1, 0.5)
  k.put(hut, g["palisade"], g["palisade_dk"])
  k.fill(clip(k.lines([[(x, 0.23), (x, 0.5)] for x in [-0.25 + 0.05 * i for i in range(7)]], 3), hut), g["palisade_dk"])
  k.put(k.box(-0.24, 0.3, 0.04, 0.42, amp=0.6), g["lm_cave"])  # serving hatch
  k.line([(-0.24, 0.39), (0.04, 0.39)], g["timber"], 4)  # shelf with jars
  for i, x in enumerate((-0.2, -0.13, -0.06, 0.0)):
    c = g["roofs"][i % len(g["roofs"])]
    k.put(k.box(x - 0.018, 0.39, x + 0.018, 0.425, amp=0.3), c)
  k.put(k.box(-0.26, 0.29, 0.06, 0.315, amp=0.5), g["timber"])  # counter
  for x, c in ((-0.18, g["fish"]), (-0.04, g["banner_lt"])):  # goods on the counter
    k.put(k.oval(x, 0.33, 0.035, 0.018, amp=0.3), c)
  awning = k.poly([(-0.28, 0.465), (0.08, 0.465), (0.13, 0.395), (-0.33, 0.395)], amp=0.6)
  k.put(awning, g["stem"])
  k.fill(clip(k.lines([[(x, 0.38), (x + 0.02, 0.48)] for x in (-0.3, -0.18, -0.06, 0.06)], 22), awning), otter)
  k.put(k.poly([(-0.36, 0.48), (-0.1, 0.68), (0.16, 0.48)]), otter, bm.shade_of(otter, 0.75), lighten(otter, 0.3))
  pennant(k, -0.1, 0.68, 0.79, otter)
  k.line([(-0.3, 0.46), (-0.42, 0.46)], width=5)  # coin sign
  k.line([(-0.36, 0.46), (-0.36, 0.44)], width=3)
  k.put(k.box(-0.44, 0.35, -0.33, 0.44, amp=0.5), g["timber"])
  k.put(k.oval(-0.385, 0.395, 0.03, 0.03, amp=0.3), g["banner_lt"], bm.shade_of(g["banner_lt"], 0.8))
  crate(k, 0.13, 0.23, 0.23, 0.32)
  crate(k, 0.24, 0.23, 0.34, 0.31)
  crate(k, 0.17, 0.32, 0.27, 0.4)
  hull = k.poly([(0.2, 0.12), (0.56, 0.12), (0.5, 0.03), (0.25, 0.03)], amp=0.8)  # rowboat
  k.put(hull, g["palisade"], g["palisade_dk"])
  k.line([(0.22, 0.1), (0.54, 0.1)], g["palisade_dk"], 3)
  k.line([(0.3, 0.12), (0.28, 0.18)], g["hay_dk"], 3)  # mooring rope


def tent(k, x, w, h, patches):
  g = bm.G
  body = k.poly([(x - w, 0), (x, h), (x + w, 0)], amp=2, sub=3)
  k.put(body, g["wall"], g["wall_dk"])
  for px, py, pw, c in patches:
    k.put(clip(k.box(x + px * w, py * h, x + (px + pw) * w, py * h + pw * w, amp=0.6), body), c)
  k.put(k.poly([(x - w * 0.28, 0), (x, h * 0.55), (x + w * 0.28, 0)], amp=0.8, sub=2), g["lm_cave"])
  k.pole([(x, h - 0.02), (x, h + 0.05)])
  for side in (-1, 1):
    k.pole([(x + side * w * 0.55, h * 0.45), (x + side * w * 1.25, 0)], g["hay_dk"])


def campfire(k, x):
  g = bm.G
  for dx in (-0.06, -0.03, 0.0, 0.03, 0.06):
    k.put(k.oval(x + dx, 0.018, 0.02, 0.016, amp=0.3), g["rock_lt"], g["rock_dk"])
  bm._ink_line(k.c, [k.at(x - 0.05, 0.02), k.at(x + 0.04, 0.06)], g["palisade"], bm.u(9))
  bm._ink_line(k.c, [k.at(x + 0.05, 0.02), k.at(x - 0.04, 0.06)], g["palisade"], bm.u(9))
  flame(k, x, 0.045, 0.035)


def loot_sack(k, x):
  g = bm.G
  k.put(k.poly([(x - 0.06, 0), (x + 0.06, 0), (x + 0.07, 0.06), (x + 0.03, 0.11), (x + 0.015, 0.125), (x - 0.015, 0.125),
                (x - 0.03, 0.11), (x - 0.07, 0.06)], amp=1), g["hay_dk"], bm.shade_of(g["hay_dk"], 0.75))
  k.line([(x - 0.025, 0.105), (x + 0.025, 0.105)], g["timber"], 4)
  for dx, dy in ((0.08, 0.012), (0.1, 0.03), (0.115, 0.012)):
    k.put(k.oval(x + dx, dy, 0.014, 0.011, amp=0.2), g["banner_lt"])


def paint_knave_camp(canvas, ax, ay, s, rng, tier):
  """Knaves of the Deepwood bandit camp. 1 a patched tent, campfire and a
  sack of loot under a tattered flag. 2 + a second tent, stake fence,
  roasting spit and an open strongbox."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.2)
  knave = g["knave_banner"]
  if tier >= 2:
    for x in (-0.5, -0.44, -0.38, -0.32):
      bm.paint_stake(canvas, *k.at(x, 0), s * rng.uniform(0.2, 0.25), rng)
    tent(k, 0.38, 0.17, 0.32, [(-0.5, 0.25, 0.4, g["hay"])])
  flag_x = -0.22 if tier == 1 else -0.1
  k.pole([(flag_x, 0.3), (flag_x, 0.72)])
  rag = k.poly([(flag_x, 0.72), (flag_x + 0.16, 0.7), (flag_x + 0.13, 0.66), (flag_x + 0.17, 0.62),
                (flag_x + 0.11, 0.6), (flag_x + 0.12, 0.56), (flag_x, 0.58)], amp=0.8, sub=1)
  k.put(rag, knave, bm.shade_of(knave, 0.75))
  k.put(k.oval(flag_x + 0.07, 0.645, 0.022, 0.022, amp=0.3), g["stem"])  # a cut purse, the knaves' mark
  tx = -0.05 if tier == 1 else -0.12
  tent(k, tx, 0.24, 0.46, [(-0.75, 0.2, 0.32, knave), (0.25, 0.35, 0.3, g["roofs"][3]), (-0.35, 0.55, 0.25, g["hay"])])
  if tier >= 2:  # roasting spit over the fire
    fx = 0.12
    for x in (fx - 0.08, fx + 0.08):
      k.pole([(x, 0), (x, 0.13)])
    k.line([(fx - 0.1, 0.125), (fx + 0.1, 0.125)], width=4)
    campfire(k, fx)
    k.put(k.oval(fx, 0.125, 0.05, 0.025, amp=0.4), g["fish"], g["fish_dk"])
    chest = k.box(-0.47, 0, -0.33, 0.08, amp=0.6)
    k.put(chest, g["timber"], bm.shade_of(g["timber"], 0.75))
    k.put(k.poly([(-0.47, 0.08), (-0.33, 0.08), (-0.35, 0.15), (-0.49, 0.13)], amp=0.4, sub=1), g["timber"])
    k.fill(k.box(-0.46, 0.065, -0.34, 0.09, amp=0), g["banner_lt"])
    k.line([(-0.4, 0.0), (-0.4, 0.08)], g["banner_lt"], 4)
    loot_sack(k, 0.52)
  else:
    campfire(k, 0.27)
    loot_sack(k, -0.38)


def paint_alliance_burrow(canvas, ax, ay, s, rng, tier):
  """Woodland Alliance burrow: a hill with a round green door, round windows,
  a chimney puffing smoke, a lantern, flowers and a little fence."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.2)
  green = g["alliance_banner"]
  k.put(k.box(0.15, 0.3, 0.21, 0.5, amp=0.6), g["stone"], g["stone_dk"])  # chimney
  for i, (x, y, r) in enumerate(((0.19, 0.56, 0.035), (0.23, 0.63, 0.045), (0.2, 0.72, 0.055))):
    k.put(k.oval(x, y, r, r * 0.85, amp=0.8), g["lm_smoke"], bm.shade_of(g["lm_smoke"], 0.85))
  hill = k.oval(0, 0, 0.47, 0.4, amp=2.5, a1=math.pi, n=18)
  k.put(hill, g["hill"], g["hill_dk"], g["hill_lt"])
  for x, y in ((-0.33, 0.27), (-0.12, 0.36), (0.32, 0.25), (0.05, 0.37), (-0.38, 0.12)):
    for d in (-1, 0, 1):
      k.line([(x + d * 0.012, y), (x + d * 0.018, y + 0.03)], g["hill_dk"], 3)
  k.put(k.oval(0, 0.135, 0.14, 0.14, amp=0.8), g["stone"], g["stone_dk"])  # door ring
  door = k.oval(0, 0.125, 0.11, 0.11, amp=0.5)
  k.put(door, green, bm.shade_of(green, 0.75))
  k.fill(clip(k.lines([[(x, 0), (x, 0.25)] for x in (-0.055, 0, 0.055)], 3), door), bm.shade_of(green, 0.7))
  k.put(k.oval(0.0, 0.125, 0.018, 0.018, amp=0.2), g["banner_lt"])
  k.put(k.box(-0.16, -0.005, 0.16, 0.02, amp=0.6), g["stone"], g["stone_dk"])  # doorstep
  for x in (-0.27, 0.27):  # round windows
    k.put(k.oval(x, 0.17, 0.06, 0.06, amp=0.4), g["timber"])
    k.put(k.oval(x, 0.17, 0.042, 0.042, amp=0.3), g["window"])
    k.line([(x - 0.042, 0.17), (x + 0.042, 0.17)], width=3)
    k.line([(x, 0.128), (x, 0.212)], width=3)
  for x, c in ((-0.36, g["blossom"]), (-0.31, g["heather"]), (-0.19, g["blossom"]), (0.19, g["heather"]),
               (0.35, g["blossom"]), (0.4, g["heather"])):
    k.put(k.oval(x, 0.03, 0.018, 0.016, amp=0.3), c)
  k.line([(0.2, 0), (0.2, 0.17)], width=5)  # lantern post
  glow(k, 0.2, 0.185, 0.02, g["glow"], halo=2.6)
  for x in (-0.56, -0.5, -0.44):  # fence
    k.put(k.box(x - 0.012, 0, x + 0.012, 0.11, amp=0.4), g["palisade"])
  k.line([(-0.58, 0.075), (-0.42, 0.075)], g["palisade_dk"], 5)
  pennant(k, -0.2, 0.36, 0.47, green, side=-1)


def sunflower(k, x, h, r):
  g = bm.G
  k.pole([(x, 0.05), (x + 0.01, h)], g["leaf_dk"])
  k.put(k.oval(x + 0.025, h * 0.5, 0.03, 0.014, amp=0.3), g["leaf"])
  m = k.mask()
  for a in range(10):
    ang = 2 * math.pi * a / 10
    m = ImageChops.lighter(m, k.oval(x + 0.01 + math.cos(ang) * r, h + math.sin(ang) * r, r * 0.55, r * 0.55, amp=0))
  k.put(m, g["lizard_banner"], bm.shade_of(g["lizard_banner"], 0.8))
  k.put(k.oval(x + 0.01, h, r * 0.75, r * 0.75, amp=0.3), g["timber"])


def paint_lizard_garden(canvas, ax, ay, s, rng, tier):
  """Lizard Cult garden: a walled plot of sun-flowers and ferns around a
  standing stone carved with a glowing sun-eye, smoking braziers, yellow
  pennants."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.4, 1.3)
  gold = g["lizard_banner"]
  for x, h in ((-0.4, 0.42), (-0.3, 0.52), (0.29, 0.5), (0.39, 0.4)):
    sunflower(k, x, h, 0.035)
  for x in (-0.18, 0.18):
    bm.paint_bush(canvas, *k.at(x, 0.08), s * 0.16, rng)
  k.put(k.box(-0.15, 0.06, 0.15, 0.13, amp=0.6), g["stone"], g["stone_dk"])  # altar steps
  k.put(k.box(-0.1, 0.13, 0.1, 0.19, amp=0.6), g["stone"], g["stone_dk"])
  k.put(k.poly([(-0.055, 0.19), (0.055, 0.19), (0.038, 0.52), (0, 0.58), (-0.038, 0.52)], amp=0.8), g["stone"],
        g["stone_dk"], g["rock_lt"])
  glow(k, 0, 0.4, 0.024, gold, halo=2.8, alpha=0.3)
  for a in range(8):  # carved sun rays
    ang = 2 * math.pi * a / 8
    k.line([(math.cos(ang) * 0.034, 0.4 + math.sin(ang) * 0.034), (math.cos(ang) * 0.046, 0.4 + math.sin(ang) * 0.046)],
           gold, 3)
  k.put(k.oval(0, 0.4, 0.008, 0.012, amp=0), g["ink"])
  for side in (-1, 1):  # braziers
    x = side * 0.11
    k.pole([(x, 0.13), (x, 0.24)], g["rock_dk"])
    k.put(k.oval(x, 0.25, 0.04, 0.025, amp=0.4, a0=math.pi, a1=2 * math.pi), g["rock_dk"])
    flame(k, x, 0.25, 0.018)
    k.pole([(x, 0.3), (x + side * 0.02, 0.36), (x - side * 0.01, 0.42), (x + side * 0.015, 0.47)], g["lm_smoke"])
  wall = k.box(-0.47, 0, 0.47, 0.085, amp=1)
  k.put(wall, g["stone"], g["stone_dk"])
  masonry(k, wall, -0.47, 0.47, 0, 0.085, g["stone_dk"], course=0.042)
  k.put(k.arch(-0.07, 0.07, 0, 0.12, amp=0.6), g["stone"], g["stone_dk"])  # gate gap in the wall
  k.put(k.arch(-0.045, 0.045, 0, 0.09, amp=0.4), g["lm_cave"])
  for x, c in ((-0.33, g["cat_banner"]), (0.36, g["hay"])):  # gourds by the wall
    k.put(k.oval(x, 0.12, 0.04, 0.032, amp=0.6), c, bm.shade_of(c, 0.75))
    k.line([(x, 0.15), (x + 0.01, 0.17)], g["leaf_dk"], 4)
  for x in (-0.47, 0.47):
    pennant(k, x, 0.08, 0.32, gold, side=1 if x < 0 else -1)


# ---------------------------------------------------------------- stone tower
def paint_stone_tower(canvas, ax, ay, s, rng, tier):
  """1 stubby lookout under a timber cone, 2 crenellated tower with a flag,
  3 tall tower with a corbelled parapet, slate spire, balcony and ivy,
  4 + a side turret, buttresses and more lit windows."""
  g, k = bm.G, Sketch(canvas, ax, ay, s, rng, 1.5, 2.3)
  stone, stone_dk = g["stone"], g["stone_dk"]
  w, H = 0.28, (0.6, 0.95, 1.2, 1.35)[tier - 1]

  def body(x, hw, top):
    m = k.poly([(x - hw, 0), (x + hw, 0), (x + hw * 0.92, top), (x - hw * 0.92, top)], amp=1.5)
    k.put(m, stone, stone_dk)
    masonry(k, m, x - hw, x + hw, 0, top, stone_dk)
    return m

  def cone(x, hw, base, h, colour):
    k.put(k.poly([(x - hw, base), (x, base + h), (x + hw, base)], amp=1), colour, bm.shade_of(colour, 0.75),
          lighten(colour, 0.25))

  if tier >= 4:  # side turret behind the main tower
    tx = 0.43
    body(tx, 0.14, 0.95)
    k.put(k.box(tx - 0.16, 0.93, tx + 0.16, 0.99, amp=0.5), stone, stone_dk)
    cone(tx, 0.18, 0.98, 0.32, g["guild_roof"])
    pennant(k, tx, 1.3, 1.4, g["banner"])
    k.window(tx - 0.01, 0.45, tx + 0.05, 0.56, arched=True)
    k.window(tx - 0.01, 0.7, tx + 0.05, 0.81, arched=True)
  body(0, w, H)
  if tier >= 4:  # buttresses
    for side in (-1, 1):
      k.put(k.poly([(side * w, 0), (side * (w + 0.1), 0), (side * w, 0.3)], amp=0.6), stone, stone_dk)
  k.put(k.arch(-0.075, 0.075, 0, 0.21), g["timber"])
  k.line([(0, 0.01), (0, 0.2)], width=3)
  if tier >= 2:
    k.put(k.box(-0.11, -0.01, 0.11, 0.02, amp=0.5), stone, stone_dk)
  slits = {1: [0.35], 2: [0.42, 0.68], 3: [0.42, 0.7], 4: [0.42, 0.7, 0.98]}[tier]
  for y in slits:
    if tier >= 3:
      k.window(-0.04, y, 0.04, y + 0.12, arched=True)
    else:
      k.put(k.box(-0.016, y, 0.016, y + 0.09, amp=0.3), g["lm_cave"])
  if tier == 1:
    k.put(k.box(-w - 0.02, H - 0.02, w + 0.02, H + 0.03, amp=0.6), g["timber"])
    cone(0, w + 0.06, H + 0.02, 0.36, g["roofs"][2])
    return
  if tier == 2:
    merlons(k, -w, w, H, stone, stone_dk, w=0.07, h=0.07, gap=0.05)
    pennant(k, 0.1, H + 0.07, H + 0.3, g["banner"])
    return
  # corbelled parapet, then a slate spire
  par = k.box(-w - 0.04, H - 0.02, w + 0.04, H + 0.08, amp=0.8)
  k.put(par, stone, stone_dk)
  for x in [-w - 0.02 + 0.08 * i for i in range(int((2 * w + 0.04) / 0.08) + 1)]:
    k.put(k.poly([(x - 0.025, H - 0.02), (x + 0.025, H - 0.02), (x, H - 0.06)], amp=0.3, sub=1), stone, stone_dk)
  cone(0, w + 0.02, H + 0.07, 0.55 if tier == 3 else 0.65, g["guild_roof"])
  top = H + 0.07 + (0.55 if tier == 3 else 0.65)
  pennant(k, 0, top, top + 0.12, g["banner"])
  by = 0.68 if tier == 3 else 0.68  # balcony
  k.put(k.box(-0.12, by - 0.03, 0.12, by, amp=0.5), stone, stone_dk)
  for x in (-0.1, -0.05, 0.0, 0.05, 0.1):
    k.line([(x, by), (x, by + 0.06)], width=3)
  k.line([(-0.12, by + 0.06), (0.12, by + 0.06)], width=4)
  vine = [(-w + 0.03 + 0.02 * math.sin(i * 1.4), 0.05 + i * 0.07) for i in range(8 if tier == 3 else 11)]
  k.line(vine, g["leaf_dk"], 5)
  for i, (x, y) in enumerate(vine[1:]):
    k.put(k.oval(x + (0.022 if i % 2 else -0.022), y, 0.024, 0.016, amp=0.3), g["leaf"])


# name -> painter(canvas, ax, ay, width_px, rng, tier); (ax, ay) = base centre
PAINTERS = {"guildhall": bm.paint_guildhall, "building": paint_building, "cave": paint_cave,
            "tree": paint_treenode, "mineral_node": paint_mineral, "fishing_spot": paint_fishing,
            "herb": paint_herb, "tracks": paint_tracks, "marquise_keep": paint_marquise_keep,
            "eyrie_roost": paint_eyrie_roost, "otter_tradepost": paint_otter_tradepost,
            "knave_camp": paint_knave_camp, "alliance_burrow": paint_alliance_burrow,
            "lizard_garden": paint_lizard_garden, "stone_tower": paint_stone_tower}


def die(msg):
  sys.exit("asset_variables.csv: " + msg)


def parse_landmark(raw):
  for k in LANDMARK_KEYS:
    if k not in raw:
      die("landmark.%s is missing" % k)
  try:
    return {"out_size": int(raw["out_size"]), "seed_offset": int(raw["seed_offset"]),
            "margin": float(raw["margin"])}
  except ValueError as e:
    die("landmark: bad value %s" % e)


def parse_colours(raw):
  for k in LANDMARK_COLOURS:
    if k not in raw:
      die("landmark_colour.%s is missing" % k)
  out = {}
  for k, v in raw.items():
    if k in bm.G:
      die("landmark_colour.%s clashes with global.%s" % (k, k))
    try:
      out[k] = bm.hexrgb(v)
    except ValueError:
      die("landmark_colour.%s: bad colour %r" % (k, v))
  return out


def parse_widths(raw):
  if not raw:
    die("no landmark_size rows")
  out = {}
  for name, value in raw.items():
    if name not in PAINTERS:
      die("landmark_size.%s: no painter (have: %s)" % (name, " ".join(PAINTERS)))
    try:  # a blank slot skips that size: |||760 = size 4 only
      widths = [float(v) if v.strip() else None for v in value.split("|")]
    except ValueError:
      die("landmark_size.%s: %r is not w1|w2|w3|w4" % (name, value))
    if not 1 <= len(widths) <= SIZES or not any(widths):
      die("landmark_size.%s: one width per size (blank = skip), 1 to %d slots, at least one width" % (name, SIZES))
    out[name] = widths
  return out


def parse_classes(raw):
  """landmark_class rows -> {class: height px on the out_size canvas}."""
  if not raw:
    die("no landmark_class rows (class name -> height px)")
  try:
    return {k: float(v) for k, v in raw.items()}
  except ValueError as e:
    die("landmark_class: bad height %s" % e)


def parse_tiers(raw, widths, classes):
  """landmark_tier rows -> {landmark: [class per size slot]}; every drawn size needs one."""
  out = {}
  for name, value in raw.items():
    if name not in widths:
      die("landmark_tier.%s: no landmark_size row for it" % name)
    out[name] = [v.strip() or None for v in value.split("|")]
    for c in out[name]:
      if c is not None and c not in classes:
        die("landmark_tier.%s: unknown class %r (have: %s)" % (name, c, " ".join(classes)))
  for name, ws in widths.items():
    have = out.get(name, [])
    for n, w in enumerate(ws):
      if w and (n >= len(have) or not have[n]):
        die("landmark_tier.%s: size %d is drawn but has no class" % (name, n + 1))
  return out


def opaque_box(img):
  """(left, top, right, bottom) of the non-transparent pixels, or None."""
  return img.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()


def fit_width(lm, name, size, width, target_px):
  """The drawing width that makes this landmark `target_px` tall on the final
  canvas, found by drawing it at 1x and rescaling the width (a drawing grows
  about linearly with its width, so this converges in two or three tries).
  Returns (width, capped): capped = it could not reach the height without
  running off the sides."""
  keep = bm.R, bm.U
  bm.R, bm.U = 1024, 1.0  # measure in design units: fast, and the geometry is the same
  target = target_px * 1024.0 / lm["out_size"]
  max_w = 1024 - 2 * SIDE_MARGIN
  capped = False
  try:
    for _ in range(FIT_TRIES):
      # measure the cleaned cut-out: a mote solid_alpha will drop must not count
      box = opaque_box(solid_alpha(draw_landmark(lm, name, size, width), MIN_PIECE, MAX_HOLE))
      if box is None:
        die("%s size %d draws nothing" % (name, size))
      w, h = box[2] - box[0], box[3] - box[1]
      if h > 0.9 * 1024 or w > max_w:  # running off the canvas: measure again smaller
        width *= 0.7
        continue
      f = target / h
      capped = w * f > max_w
      if capped:
        f = max_w / w
      if abs(f - 1) <= FIT_TOLERANCE:
        break
      width *= f
  finally:
    bm.R, bm.U = keep
  return width, capped


def ground_on_bottom(img):
  """Shift the drawing so its lowest opaque row is the canvas's bottom row and
  it is centred left-right -- the same placement as every meeple."""
  box = opaque_box(img)
  if box is None:
    return img
  out = Image.new("RGBA", img.size, (0, 0, 0, 0))
  dx = (img.size[0] - (box[0] + box[2])) // 2
  dy = img.size[1] - box[3]
  out.paste(img, (dx, dy))
  return out


def landmark_seed(lm, name, size):
  # crc32 rather than hash(): stable across runs, so unchanged knobs = unchanged image
  key = "landmark|%s|%d" % (name, size)
  return (zlib.crc32(key.encode()) + bm.G["seed"] * 7919 + lm["seed_offset"] * 104729) % (2 ** 31)


def label_pieces(mask):
  """[(bool array, pixel count)] for each 4-connected True region of `mask`."""
  lab = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).copy()
  pieces = []
  for k in range(1, 255):
    left = np.argwhere(np.asarray(lab) == 255)
    if len(left) == 0:
      break
    y, x = left[0]
    ImageDraw.floodfill(lab, (int(x), int(y)), k)
    piece = np.asarray(lab) == k
    pieces.append((piece, int(piece.sum())))
  return pieces


def solid_alpha(img, min_piece, max_hole):
  """Make the standee's alpha a clean cut-out for a TTS Custom Token.

  TTS extrudes the token from the alpha outline. The downscale leaves a soft
  fringe that breaks into hundreds of near-transparent specks and pinholes,
  and each one is traced into a stray wall (dark slabs sticking out of the
  outline in game). So: cut at 50% alpha, fill enclosed holes smaller than
  `max_hole` pixels with ink, and drop detached pieces smaller than
  `min_piece` -- real separate parts and big openings stay. Works on flood
  fills, so it needs nothing beyond Pillow."""
  w, h = img.size
  solid = (np.asarray(img.getchannel("A")) >= 128).astype(np.uint8) * 255
  # outside = transparent and reachable from the border; anything else is shape or a hole
  # .copy(): an image made by fromarray shares numpy's read-only buffer, and floodfill
  # on it silently changes nothing
  pad = Image.fromarray(np.pad(solid, 1)).copy()
  ImageDraw.floodfill(pad, (0, 0), 100)
  outside = np.asarray(pad)[1:-1, 1:-1] == 100
  holes = np.zeros((h, w), bool)
  for hole, size in label_pieces(~outside & (solid == 0)):
    if size < max_hole:
      holes |= hole
  keep = np.zeros((h, w), bool)
  for piece, size in label_pieces((solid > 0) | holes):
    if size >= min_piece:
      keep |= piece
  rgba = np.array(img)
  rgba[holes] = (*bm.G["ink"], 255)
  rgba[..., 3] = np.where(keep, 255, 0)
  return Image.fromarray(rgba, "RGBA")


def draw_landmark(lm, name, size, width):
  img = Image.new("RGBA", (bm.R, bm.R), (0, 0, 0, 0))
  rng = np.random.default_rng(landmark_seed(lm, name, size))
  PAINTERS[name](img, bm.R / 2, bm.R - bm.u(lm["margin"]), bm.u(width), rng, size)
  return finish_alpha(img)


def main():
  ap = argparse.ArgumentParser(description="Draw storybook landmark standees from data/asset_variables.csv.")
  ap.add_argument("landmark", nargs="*", help="landmark types to draw (default: all)")
  ap.add_argument("--size", nargs="+", type=int, help="sizes to draw, 1-%d (default: every size the CSV gives)" % SIZES)
  ap.add_argument("--prune", action="store_true", help="delete images the CSV no longer describes")
  args = ap.parse_args()

  glob, groups = bm.load_config(ASSET_VARS, skip=())
  bm.setup(bm.parse_global(glob))
  lm = parse_landmark(groups.get("landmark", {}))
  bm.G.update(parse_colours(groups.get("landmark_colour", {})))
  widths = parse_widths(groups.get("landmark_size", {}))
  classes = parse_classes(groups.get("landmark_class", {}))
  tiers = parse_tiers(groups.get("landmark_tier", {}), widths, classes)
  # same 1024-unit design space as a tile, so ink weighs the same at out_size 1024
  bm.R = lm["out_size"] * bm.G["supersample"]
  bm.U = bm.R / 1024.0
  for name in args.landmark:
    if name not in widths:
      sys.exit("unknown landmark %r (have: %s)" % (name, " ".join(widths)))
  for size in args.size or ():
    if not 1 <= size <= SIZES:
      sys.exit("--size must be 1-%d" % SIZES)
  os.makedirs(OUT_DIR, exist_ok=True)

  def described(name):
    return [n + 1 for n, w in enumerate(widths[name]) if w]

  rows = []
  for name in args.landmark or list(widths):
    sizes = [z for z in described(name) if not args.size or z in args.size]
    if args.size and not sizes:
      print("  %s: no width for size %s in landmark_size, skipped" % (name, " ".join(map(str, args.size))))
    for size in sizes:
      file = "%s_s%d.png" % (name, size)
      cls = tiers[name][size - 1]
      width, capped = fit_width(lm, name, size, widths[name][size - 1], classes[cls])
      img = draw_landmark(lm, name, size, width).resize((lm["out_size"], lm["out_size"]), Image.LANCZOS)
      area = (lm["out_size"] / 1024) ** 2
      # place AFTER the clean-up, so a dropped mote cannot pull it off centre
      ground_on_bottom(solid_alpha(img, MIN_PIECE * area, MAX_HOLE * area)).save(os.path.join(OUT_DIR, file))
      rows.append({"name": file[:-4], "landmark": name, "size": size, "class": cls, "width": "%.1f" % width,
                   "seed": landmark_seed(lm, name, size), "file": file})
      box = opaque_box(Image.open(os.path.join(OUT_DIR, file)))
      note = "  <-- too wide for its height: capped" if capped else ""
      print("  %-22s %-8s %4d px tall%s" % (file[:-4], cls, box[3] - box[1], note))

  # Upsert: drawn rows replace their manifest entries, everything else stays.
  by_name = {}
  if os.path.exists(MANIFEST):
    with open(MANIFEST, newline="", encoding="utf-8") as f:
      by_name = {r["name"]: r for r in csv.DictReader(f)}
  by_name.update({r["name"]: r for r in rows})
  if args.prune:
    keep = {"%s_s%d" % (n, z) for n in widths for z in described(n)}
    for name in sorted(set(by_name) - keep):
      del by_name[name]
    for f in sorted(os.listdir(OUT_DIR)):
      if f.endswith(".png") and f[:-4] not in keep:
        os.remove(os.path.join(OUT_DIR, f))
        print("  pruned " + f)
  with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "landmark", "size", "class", "width", "seed", "file"], restval="")
    w.writeheader()
    w.writerows(sorted(by_name.values(), key=lambda r: (r["landmark"], int(r["size"]))))
  print("%d images -> %s" % (len(rows), os.path.relpath(OUT_DIR, os.path.dirname(ROOT))))


if __name__ == "__main__":
  main()
