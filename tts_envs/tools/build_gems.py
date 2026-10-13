#!/usr/bin/env python3
"""Draw storybook gems on transparent PNGs, for card art.

Same style as the map tiles: every shape goes through build_map_tiles'
stamp() / wobble() / finish(), so the two generators cannot drift apart.

  data/asset_variables.csv  ->  assets/gems/<colour>_<cut><n>.png
  (gem + gem_colour rows)       assets/gems/manifest.csv

A faceted gem = wobbled outline (ink ring + base fill) -> a ring of facets
around a central table, each facet one flat tone picked by which way it faces
a top-left light -> ink facet lines -> cream glint on the table. Flat tones
replace the shade/light crescents; `cabochon` is a smooth dome and uses the
crescents instead.

Every colour gets every cut. Same CSV + same seed = byte-identical output.

Not part of master_sync.cmd: art is rebuilt by hand, then uploaded by hand.

Run: python tools/build_gems.py            every colour
     python tools/build_gems.py ruby       one colour (others untouched)
"""
import csv, math, os, sys, zlib

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasets import ROOT, ASSET_VARS
import build_map_tiles as bm

import numpy as np
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(ROOT), "assets", "gems")
MANIFEST = os.path.join(OUT_DIR, "manifest.csv")
GEM_KEYS = ("out_size", "variants", "cuts", "size", "seed_offset", "wobble",
            "facet_jitter", "facet_line", "glint")
# A gem canvas is this many design units wide, so 1 unit = 1 output px and the
# ink ring weighs the same as on a 1024 px tile.
GEM_UNITS = 512.0


def die(msg):
  sys.exit("asset_variables.csv: " + msg)


# ---------------------------------------------------------------- config
def parse_gem(raw):
  for k in GEM_KEYS:
    if k not in raw:
      die("gem.%s is missing" % k)
  g = {}
  try:
    g["out_size"] = int(raw["out_size"])
    g["variants"] = int(raw["variants"])
    g["seed_offset"] = int(raw["seed_offset"])
    g["wobble"] = float(raw["wobble"])
    g["facet_jitter"] = float(raw["facet_jitter"])
    g["facet_line"] = float(raw["facet_line"])
    g["glint"] = bm.hexrgb(raw["glint"])
    lo, hi = (float(v) for v in raw["size"].split("-"))
  except ValueError as e:
    die("gem: bad value %s" % e)
  if not 10 <= lo <= hi <= 90:
    die("gem.size must be lo-hi with 10 <= lo <= hi <= 90 (else the ink ring is clipped)")
  g["size"] = (lo, hi)
  g["cuts"] = [c.strip() for c in raw["cuts"].split("|") if c.strip()]
  if not g["cuts"]:
    die("gem.cuts is empty")
  for c in g["cuts"]:
    if c not in CUTS:
      die("gem.cuts: unknown %r (use %s)" % (c, " ".join(CUTS)))
  return g


def parse_colours(raw):
  if not raw:
    die("no gem_colour rows")
  out = {}
  for name, value in raw.items():
    if not name.replace("_", "").isalnum():
      die("gem_colour.%s: name must be letters/digits/_ (it becomes a filename)" % name)
    try:
      out[name] = bm.hexrgb(value)
    except ValueError:
      die("gem_colour.%s: bad colour %r" % (name, value))
  return out


# ---------------------------------------------------------------- cuts
# Each returns (outline, table, aspect): point lists in units of the gem's
# half-size around (0, 0), same length, so facet i spans outline[i..i+1] and
# table[i..i+1]. aspect = width / height.
def ring(n, fx, fy, start=-math.pi / 2):
  return [(fx(start + 2 * math.pi * k / n), fy(start + 2 * math.pi * k / n)) for k in range(n)]


def scaled(pts, f, dy=0.0):
  return [(x * f, y * f + dy) for x, y in pts]


def cut_round():
  pts = ring(8, math.cos, math.sin, -math.pi / 2 + math.pi / 8)
  return pts, scaled(pts, 0.55), 1.0


def cut_oval():
  pts = ring(10, math.cos, math.sin)
  return pts, scaled(pts, 0.52), 0.76


def cut_cushion():
  # superellipse: a square with soft corners
  sq = lambda v: math.copysign(abs(v) ** 0.5, v)
  pts = ring(12, lambda a: sq(math.cos(a)), lambda a: sq(math.sin(a)), -math.pi / 2 + math.pi / 12)
  return pts, scaled(pts, 0.55), 0.95


def cut_emerald():
  c = 0.3
  pts = [(-1 + c, -1), (1 - c, -1), (1, -1 + c), (1, 1 - c), (1 - c, 1), (-1 + c, 1), (-1, 1 - c), (-1, -1 + c)]
  return pts, scaled(pts, 0.62), 0.72


def cut_pear():
  pts = []
  for x, y in ring(10, math.cos, math.sin):
    top = max(0.0, -y)  # 0 at the belly, 1 at the point
    pts.append((x * (1 - 0.75 * top ** 2), y - 0.16 * top))
  return pts, scaled(pts, 0.5, 0.1), 0.7


def cut_marquise():
  # lens: pointed at top and bottom
  pts = ring(10, lambda a: math.copysign(math.cos(a) ** 2, math.cos(a)), math.sin)
  return pts, scaled(pts, 0.5), 0.5


def cut_heart():
  pts = []
  for k in range(14):
    t = 2 * math.pi * k / 14
    pts.append((16 * math.sin(t) ** 3 / 16,
                -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 15))
  cy = (max(y for _, y in pts) + min(y for _, y in pts)) / 2
  pts = [(x, y - cy) for x, y in pts]
  return pts, scaled(pts, 0.5, -0.08), 1.05


def cut_trillion():
  corners = [(0, -1), (1, 0.75), (-1, 0.75)]
  pts = []
  for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    ln = math.hypot(mx, my - 0.15) or 1
    pts += [(x0, y0), (mx + mx / ln * 0.12, my + (my - 0.15) / ln * 0.12)]  # sides bow outward
  return pts, scaled(pts, 0.5, 0.06), 1.1


def cut_cabochon():
  pts = ring(16, math.cos, math.sin)
  return pts, None, 0.8


CUTS = {
  "round": cut_round, "oval": cut_oval, "cushion": cut_cushion, "emerald": cut_emerald,
  "pear": cut_pear, "marquise": cut_marquise, "heart": cut_heart, "trillion": cut_trillion,
  "cabochon": cut_cabochon,
}
STEP_CUTS = ("emerald",)  # plain bands instead of split triangles


# ---------------------------------------------------------------- painter
def mix(a, b, t):
  return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def centroid(pts):
  return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def draw_gem(gem, cut, colour, seed):
  rng = np.random.default_rng(seed)
  R = bm.R
  canvas = Image.new("RGBA", (R, R), (0, 0, 0, 0))
  outline, table, aspect = CUTS[cut]()
  aspect *= rng.uniform(0.95, 1.05)
  long_side = GEM_UNITS * rng.uniform(*gem["size"]) / 100
  hw, hh = (long_side / 2, long_side / 2 / aspect) if aspect >= 1 else (long_side / 2 * aspect, long_side / 2)
  cx = cy = R / 2
  place = lambda p: (cx + bm.u(p[0] * hw), cy + bm.u(p[1] * hh))
  outline = [place(p) for p in outline]

  mask = Image.new("L", (R, R), 0)
  ImageDraw.Draw(mask).polygon(bm.wobble(outline, rng, gem["wobble"]), fill=255)
  glint = gem["glint"]
  if table is None:
    bm.stamp(canvas, mask, 0, 0, colour, bm.shade_of(colour, 0.72), mix(colour, glint, 0.4))
    gx, gy, gr = cx - bm.u(hw * 0.38), cy - bm.u(hh * 0.4), bm.u(min(hw, hh) * 0.2)
    paint_glint(canvas, gx, gy, gr, glint)
    return canvas

  bm.stamp(canvas, mask, 0, 0, colour)
  j = gem["facet_jitter"]
  table = [(x + rng.normal(0, bm.u(j)), y + rng.normal(0, bm.u(j))) for x, y in (place(p) for p in table)]
  tones = [mix(colour, glint, 0.45), mix(colour, glint, 0.18), colour,
           bm.shade_of(colour, 0.8), bm.shade_of(colour, 0.62)]
  tcx, tcy = centroid(table)

  def tone(pts, bias):
    mx, my = centroid(pts)
    dx, dy = mx - tcx, my - tcy
    ln = math.hypot(dx, dy) or 1
    lit = -(dx + dy) / ln * 0.7071  # +1 facing the top-left light, -1 away
    k = int(round((1 - lit) / 2 * (len(tones) - 1))) + bias
    return tones[max(0, min(len(tones) - 1, k))]

  n = len(outline)
  facets = []
  for i in range(n):
    o0, o1, t0, t1 = outline[i], outline[(i + 1) % n], table[i], table[(i + 1) % n]
    if cut in STEP_CUTS:
      facets.append(([o0, o1, t1, t0], 0))
    else:  # split the quad so neighbouring facets alternate light/dark
      facets.append(([o0, o1, t0], 0))
      facets.append(([o1, t1, t0], 1))
  # facets follow the un-wobbled outline: draw them on a copy, then paste back
  # through the wobbled mask so nothing pokes past the ink ring
  layer = canvas.copy()
  d = ImageDraw.Draw(layer)
  for pts, bias in facets:
    d.polygon(pts, fill=tone(pts, bias))
  d.polygon(table, fill=tones[1])
  lw = max(1, int(bm.u(gem["facet_line"])))
  for pts, _ in facets:
    d.line(pts + pts[:1], fill=bm.G["ink"], width=lw, joint="curve")
  d.line(table + table[:1], fill=bm.G["ink"], width=lw, joint="curve")
  canvas.paste(layer, (0, 0), mask)

  tw = max(p[0] for p in table) - min(p[0] for p in table)
  paint_glint(canvas, tcx - tw * 0.18, tcy - tw * 0.18, tw * 0.13, glint)
  return canvas


def paint_glint(canvas, x, y, r, colour):
  m = Image.new("L", canvas.size, 0)
  ImageDraw.Draw(m).ellipse([x - r, y - r * 0.6, x + r, y + r * 0.6], fill=255)
  canvas.paste(colour, (0, 0), m)


def finish_alpha(img):
  """Paper grain + tint on the colour only; transparent pixels stay clear."""
  a = img.getchannel("A")
  return Image.merge("RGBA", (*bm.finish(img.convert("RGB")).split(), a))


# ---------------------------------------------------------------- build
def gem_seed(gem, colour, cut, n):
  # crc32 rather than hash(): stable across runs, so unchanged knobs = unchanged image
  key = "gem|%s|%s|%d" % (colour, cut, n)
  return (zlib.crc32(key.encode()) + bm.G["seed"] * 7919 + gem["seed_offset"] * 104729) % (2 ** 31)


def read_manifest():
  if not os.path.exists(MANIFEST):
    return []
  with open(MANIFEST, newline="", encoding="utf-8") as f:
    return list(csv.DictReader(f))


def main():
  glob, groups = bm.load_config(ASSET_VARS, skip=())
  bm.setup(bm.parse_global(glob))
  gem = parse_gem(groups.get("gem", {}))
  colours = parse_colours(groups.get("gem_colour", {}))
  bm.R = gem["out_size"] * bm.G["supersample"]
  bm.U = bm.R / GEM_UNITS
  only = sys.argv[1:]
  for name in only:
    if name not in colours:
      sys.exit("unknown gem colour %r (have: %s)" % (name, " ".join(colours)))
  todo = [c for c in colours if not only or c in only]
  os.makedirs(OUT_DIR, exist_ok=True)

  rows = []
  for colour in todo:
    for cut in gem["cuts"]:
      for n in range(1, gem["variants"] + 1):
        name = "%s_%s%d" % (colour, cut, n)
        seed = gem_seed(gem, colour, cut, n)
        img = finish_alpha(draw_gem(gem, cut, colours[colour], seed))
        img.resize((gem["out_size"], gem["out_size"]), Image.LANCZOS).save(os.path.join(OUT_DIR, name + ".png"))
        rows.append({"name": name, "colour": colour, "cut": cut, "seed": seed, "file": name + ".png"})
        print("  " + name)

  # Merge with the previous manifest: untouched colours keep their rows; a
  # rebuilt colour's files that are no longer produced are deleted.
  rebuilt = set(todo)
  new_names = {r["name"] for r in rows}
  kept = []
  for old in read_manifest():
    if old["colour"] not in rebuilt and old["colour"] in colours:
      kept.append(old)
    elif old["name"] not in new_names:
      stale = os.path.join(OUT_DIR, old["file"])
      if os.path.exists(stale):
        os.remove(stale)
        print("  removed stale " + old["file"])
  order = list(colours)
  rows = sorted(kept + rows, key=lambda r: (order.index(r["colour"]), r["name"]))
  with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "colour", "cut", "seed", "file"])
    w.writeheader()
    w.writerows(rows)
  print("%d images -> %s" % (len(new_names), os.path.relpath(OUT_DIR, os.path.dirname(ROOT))))


if __name__ == "__main__":
  main()
