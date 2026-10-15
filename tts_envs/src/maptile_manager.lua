--[[ Maptile Manager: draw overworld map tiles from the generated art.

Source for the in-game bag nicknamed "Maptile Manager" (GUID b77050). Staged
by tools/sync/sync_maptile_manager.py, which also inlines MAPTILE from
data/maptile.xlsx.

THE PANEL

  [ Draw ]  [ Draw specific ]  [ Spawn guildhall ]
               [ Advanced ]                         toggles the grid below
  [ Region: Random ]↺  [ Biome: Random     ]↺     left-click = next, right-click = back, ↺ = Random
  [ Pattern: Random  ]  [ Orientation: Random ]     Biome / Orientation depend on the left one
  [ Density: Random  ]  [ Force: Off          ]
  [ Force: N ] [ Force: E ] [ Force: S ] [ Force: W ]      edge toggles

Draw ignores the settings and rolls everything; Draw specific rolls only what
is still Random. Force: On overrides Pattern and Orientation: Draw specific
picks evenly among every pattern+rotation that fits the edges, then rolls the
rest as usual. Each edge is one of three states:

  green  left-click   the tile MUST have a road on this edge
  red    right-click  the tile must NOT have a road on this edge
  blue   (default)    either way

Clicking the same button again clears it; the other button switches it
(green -> red). Red N, E, S + green W = only the dead end open to the W. No
shape fitting = nothing is drawn. The edges can be set while Force is Off and
take effect when it goes On. The guildhall is the starter tile: neither Draw offers it.
Spawn guildhall rolls one from the guildhall:* pools in MAPTILE.weights. Every
roll goes deck -> biome -> pattern -> orientation -> density, each from its
pool in MAPTILE.weights, so a deck with more biomes is not drawn more often.
Rolls are free: a tile can come up twice.

A DRAWN TILE

A copy of the bag's template tile (GMNotes "maptile_template", tagged
Template), stamped with:

  name         the biome name, e.g. "Deepwood"
  description  biome_descriptions sheet
  GMNotes      the biome id -- the key everything else reads
  memo         "d=<density>|explore=<left>|rendered=<0/1>"
  images       front = the rolled image, back = its deck's back
  tags         Maptile, Region:<deck>, Biome:<biome>  (ids: Region:settlement, Biome:city)

Its buttons belong to THIS script (function_owner = self), so a tile only
works while the manager is on the table. TTS does not save buttons, so onLoad
re-renders every Maptile from its GMNotes + memo.

Render hands the biome's maptile_table spawn table to Global's spawnFrom, so
landmarks, items and gold come out of the same bags as every other spawn and
drop onto the tile's centre.

Explore swaps itself for four choices (EXPLORE_CHOICES); picking one spends
the explore. Resources / Points of interest roll the biome's weights for that
category and clone the landmark onto the tile's centre, stamped with the
outcome's GMNotes + memo. Experiences takes the top card of the region's
EVENT_BAGS bag. Wander picks one of the three for you. Every outcome is
announced with its flavor (explore_outcomes sheet).
]]

--[[ BEGIN GENERATED MAPTILE DATA -- do not edit ]]
MAPTILE = {decks = {}, biomes = {}, patterns = {}, orientations = {}, densities = {},
           images = {}, explore = {}, weights = {}, table = {}, outcomes = {}, exploration = {}}
--[[ END GENERATED MAPTILE DATA ]]

TEMPLATE_GM = "maptile_template"
TEMPLATE_TAG = "Template"
TILE_TAG = "Maptile"
RANDOM = "random"
EDGES = {"N", "E", "S", "W"}
MAX_REROLLS = 40

PATTERN_NAMES = {deadend = "Dead End", corner = "Corner", straight = "Straight", tee = "Tee", cross = "Cross"}

--[[ Box-drawing glyph per orientation: each draws a line toward every edge
with a road. Literal characters, not escapes: "\u{...}" is Lua 5.3, and byte
escapes would reach MoonSharp's UTF-16 strings as separate characters. If the
button font lacks a glyph it shows an empty box -- swap that entry for text
(e.g. "N") and nothing else changes. ]]
ORIENTATION_GLYPHS = {
  N = "╵", E = "╶", S = "╷", W = "╴",
  NE = "└", ES = "┌", SW = "┐", NW = "┘",
  NS = "│", EW = "─",
  NES = "├", ESW = "┬", NSW = "┤", NEW = "┴",
  NESW = "┼",
}

--[[ Manager panel in WORLD units from the bag's centre, along its own axes;
+z is the bag's front. Buttons inherit the object's scale, and this bag is
scaled unevenly, so addButton divides it back out per axis: text stays
unstretched and positions stay put whatever the bag's scale. Same SHARPNESS
trick as the importers: big font, small scale. ]]
PANEL = {
  SHARPNESS = 4,
  LIFT = 0.1,           -- above the bag's base, so buttons sit on the table
  TOP_Z = 3.2,          -- Draw / Draw specific / Spawn guildhall
  TOP_X = {-5.6, 0, 5.6},
  ADVANCED_Z = 4.6,
  GRID_Z = 6.0,         -- first config row
  GRID_X = {-3.9, 3.9},
  ROW_STEP = 1.4,
  BTN_W = 2400, BTN_H = 540, BTN_FONT = 260,
  CONFIG_W = 3000,
  RESET_W = 420,        -- the ↺ beside each setting
  RESET_DX = 3.55,      -- its x offset from the setting's centre
  EDGE_X = {-5.85, -1.95, 1.95, 5.85},  -- Force: N E S W, one row under the grid
  EDGE_W = 1650,
  BTN_SCALE = 1,
  DRAW_COLOR = {0.25, 0.45, 0.3},
  ADVANCED_COLOR = {0.25, 0.25, 0.25},
  GUILDHALL_COLOR = {0.5, 0.36, 0.18},
  CONFIG_COLOR = {0.3, 0.34, 0.5},
  LOCKED_COLOR = {0.32, 0.32, 0.32},
  FORCE_ON_COLOR = {0.62, 0.36, 0.18},
  MUST_COLOR = {0.22, 0.55, 0.25},     -- edge: must have a road
  MUST_NOT_COLOR = {0.65, 0.2, 0.18},  -- edge: must not have a road
  TEXT_COLOR = {1, 1, 1},
}

--[[ Explore: one bag of single event cards per region deck (never decked, so
each can be searched). DROP = world units above the tile's centre. ]]
EVENT_BAGS = {woodland = "570544", waterside = "524231", opencountry = "3546e2", settlement = "8bce91",
              scarred = "f608d7"}
EXPLORE = {DROP = 1.5, CHOICE_TIMEOUT = 5}  -- seconds the four choices wait before Explore returns

EXPLORE_CHOICES = {
  {fn = "exploreWander", label = "Wander", tooltip = "Randomly picks one of the other three options."},
  {fn = "exploreResources", label = "Resources",
   tooltip = "Focus on finding resources. Chance to find a Mining, Fishing, Herbalism, Hunting, or Forestry node "
             .. "for this biome."},
  {fn = "explorePoi", label = "Points of interest",
   tooltip = "Focus on finding points of interests. Chance to find various Landmarks with long-lasting impact on "
             .. "the map for this biome."},
  {fn = "exploreExperiences", label = "Experiences",
   tooltip = "Focus on interacting with the local people (though no guarantee you'll find them). Draw the next "
             .. "event card for this region."},
}

-- How each choice is announced: player, tile name, explores left.
EXPLORE_HEADS = {
  resource = "%s searches the %s for resources (%d left): ",
  poi = "%s searches the %s for points of interest (%d left): ",
  event = "%s looks for the locals in the %s (%d left): ",
}

-- Where a drawn tile lands, in the bag's local units, and how it is turned.
-- z = 180 lands it face down: the deck back shows until someone flips it.
SPAWN = {OFFSET = {-5.5, 1, 0}, ROTATION = {0, 180, 180}}

-- Buttons on a drawn tile, in the TILE's local units. Tune to the template's scale.
TILE_UI = {
  SHARPNESS = 4,
  LIFT = 0.25,
  EXPLORE_POS = {0, 0, -0.8},
  RENDER_POS = {0, 0, 0},
  HELP_POS = {0.8, 0, 0.8},
  -- the four explore choices, 2x2 where the Explore button was: Wander, Resources, Points of interest, Experiences
  CHOICE_POS = {{-0.5, 0, -0.95}, {0.5, 0, -0.95}, {-0.5, 0, -0.65}, {0.5, 0, -0.65}},
  CHOICE_W = 640,
  BTN_W = 520, BTN_H = 160, BTN_FONT = 95, BTN_SCALE = 0.5,
  HELP_W = 160,
  HELP_COLOR = {0.9, 0.87, 0.78},
  HELP_ON_TEXT = {0, 0, 0},
  HELP_OFF_TEXT = {0.55, 0.55, 0.55},
  EXPLORE_COLOR = {0.2, 0.42, 0.5},
  RENDER_COLOR = {0.55, 0.38, 0.2},
  TEXT_COLOR = {1, 1, 1},
}

CONFIG_KEYS = {"deck", "biome", "pattern", "orientation", "density"}
CONFIG_TITLES = {deck = "Region", biome = "Biome", pattern = "Pattern", orientation = "Orientation",
                 density = "Density"}

-- force = "on"/"off"; edges = edges that must have a road, noedges = edges that must
-- not, each in NESW order ("NE"). Strings, so they save as-is.
SETTINGS = {deck = RANDOM, biome = RANDOM, pattern = RANDOM, orientation = RANDOM, density = RANDOM,
            force = "off", edges = "", noedges = ""}
ADVANCED = false          -- config grid shown; saved
local configButton = {}   -- key -> button index on self; empty while the grid is hidden
local forceButton = {}    -- "toggle" / "N" / "E" / "S" / "W" -> button index; empty while hidden
local templateData = nil  -- cached getData() of the template; refreshed each load
local choosing = {}       -- tile GUID -> Wait id of its timeout while the explore choices show; not saved
local renderTile          -- defined with the tile buttons; spawning needs it first

-- ---------------------------------------------------------------- helpers

local function isGone(o)
  return o == nil or (o.isDestroyed ~= nil and o.isDestroyed())
end

local function copy(t)
  if type(t) ~= "table" then return t end
  local out = {}
  for k, v in pairs(t) do out[k] = copy(v) end
  return out
end

local function pick(pool)
  return pool[math.random(#pool)]
end

local function sharp(font, width, height, extra, k)
  local s = (extra or 1) / k
  return font * k, width * k, height * k, {s, s, s}
end

local function deckById(id)
  for _, d in ipairs(MAPTILE.decks) do
    if d.id == id then return d end
  end
  return nil
end

-- ---------------------------------------------------------------- settings

--[[ The values one config button cycles through, its default first.
Dependent buttons collapse to {Random} while what they depend on is Random. ]]
local function options(key)
  local list = {RANDOM}
  if key == "deck" then
    for _, d in ipairs(MAPTILE.decks) do table.insert(list, d.id) end
  elseif key == "biome" then
    local deck = deckById(SETTINGS.deck)
    if deck then
      for _, b in ipairs(deck.biomes) do table.insert(list, b) end
    end
  elseif key == "pattern" then
    for _, p in ipairs(MAPTILE.patterns) do table.insert(list, p) end
  elseif key == "orientation" then
    for _, o in ipairs(MAPTILE.orientations[SETTINGS.pattern] or {}) do table.insert(list, o) end
  elseif key == "density" then
    for _, d in ipairs(MAPTILE.densities) do table.insert(list, d) end
  end
  return list
end

local function display(key, value)
  if value == RANDOM then return "Random" end
  if key == "deck" then
    local d = deckById(value)
    return d and d.name or value
  elseif key == "biome" then
    local b = MAPTILE.biomes[value]
    return b and b.name or value
  elseif key == "pattern" then
    return PATTERN_NAMES[value] or value
  elseif key == "orientation" then
    return ORIENTATION_GLYPHS[value] or value
  end
  return value
end

local function forced(spec)
  return spec.force == "on"
end

-- "must", "not" or "" (either way) for one edge
local function edgeState(edge)
  if SETTINGS.edges:find(edge, 1, true) then return "must" end
  if SETTINGS.noedges:find(edge, 1, true) then return "not" end
  return ""
end

-- Pattern and Orientation do nothing while Force is on.
local function overridden(key)
  return (key == "pattern" or key == "orientation") and forced(SETTINGS)
end

local LOCKED_HINT = {biome = "Pick a Region first", orientation = "Pick a Pattern first"}

-- Hover text: every value the button can take, or why it cannot change.
local function configTooltip(key)
  if overridden(key) then return "Overridden by Force (turn it Off)" end
  local list = options(key)
  if #list == 1 and LOCKED_HINT[key] then return LOCKED_HINT[key] end
  local names = {}
  for _, v in ipairs(list) do table.insert(names, display(key, v)) end
  return "Options: " .. table.concat(names, ", ")
end

local function refreshConfigLabels()
  for _, key in ipairs(CONFIG_KEYS) do
    local idx = configButton[key]
    if idx ~= nil then
      local locked = #options(key) == 1 or overridden(key)
      self.editButton({index = idx, label = CONFIG_TITLES[key] .. ": " .. display(key, SETTINGS[key]),
                       tooltip = configTooltip(key), color = locked and PANEL.LOCKED_COLOR or PANEL.CONFIG_COLOR})
    end
  end
  local on = forced(SETTINGS)
  if forceButton.toggle ~= nil then
    self.editButton({index = forceButton.toggle, label = on and "Force: On" or "Force: Off",
                     color = on and PANEL.FORCE_ON_COLOR or PANEL.CONFIG_COLOR})
  end
  for _, edge in ipairs(EDGES) do
    if forceButton[edge] ~= nil then
      -- green = must, red = must not, blue = either; all grey while Force is off
      local state = edgeState(edge)
      local color = PANEL.CONFIG_COLOR
      if not on then
        color = PANEL.LOCKED_COLOR
      elseif state == "must" then
        color = PANEL.MUST_COLOR
      elseif state == "not" then
        color = PANEL.MUST_NOT_COLOR
      end
      self.editButton({index = forceButton[edge], label = "Force: " .. edge, color = color})
    end
  end
end

--[[ The one cycling rule every config button shares: step forward on a
left-click, back on a right-click (alt_click), wrapping round. Changing a
deck or pattern resets the setting that depends on it. ]]
local function cycle(key, back)
  if overridden(key) then return end
  local list = options(key)
  local at = 1
  for i, v in ipairs(list) do
    if v == SETTINGS[key] then at = i end
  end
  at = ((at - 1 + (back and -1 or 1)) % #list) + 1
  SETTINGS[key] = list[at]
  if key == "deck" then SETTINGS.biome = RANDOM end
  if key == "pattern" then SETTINGS.orientation = RANDOM end
  refreshConfigLabels()
end

--[[ ↺: straight back to Random, clearing what depends on it like a cycle does.
Pattern / Orientation stay put while Force overrides them. ]]
local function reset(key)
  if overridden(key) then return end
  SETTINGS[key] = RANDOM
  if key == "deck" then SETTINGS.biome = RANDOM end
  if key == "pattern" then SETTINGS.orientation = RANDOM end
  refreshConfigLabels()
end

function resetDeck() reset("deck") end
function resetBiome() reset("biome") end
function resetPattern() reset("pattern") end
function resetOrientation() reset("orientation") end
function resetDensity() reset("density") end
RESET_FN = {deck = "resetDeck", biome = "resetBiome", pattern = "resetPattern",
            orientation = "resetOrientation", density = "resetDensity"}

-- Button callbacks must be global functions named by string.
function cycleDeck(_, _, alt) cycle("deck", alt) end
function cycleBiome(_, _, alt) cycle("biome", alt) end
function cyclePattern(_, _, alt) cycle("pattern", alt) end
function cycleOrientation(_, _, alt) cycle("orientation", alt) end
function cycleDensity(_, _, alt) cycle("density", alt) end
CYCLE_FN = {deck = "cycleDeck", biome = "cycleBiome", pattern = "cyclePattern",
            orientation = "cycleOrientation", density = "cycleDensity"}

function toggleForce()
  SETTINGS.force = forced(SETTINGS) and "off" or "on"
  refreshConfigLabels()
end

--[[ Left-click asks for "must", right-click for "not". Asking for the state the
edge already has clears it; asking for the other one switches straight to it.
Both strings are rebuilt in NESW order. ]]
local function setEdge(edge, want)
  local now = edgeState(edge)
  local new = now == want and "" or want
  local must, mustNot = "", ""
  for _, e in ipairs(EDGES) do
    local st = e == edge and new or edgeState(e)
    if st == "must" then must = must .. e end
    if st == "not" then mustNot = mustNot .. e end
  end
  SETTINGS.edges, SETTINGS.noedges = must, mustNot
  refreshConfigLabels()
end

function toggleForceN(_, _, alt) setEdge("N", alt and "not" or "must") end
function toggleForceE(_, _, alt) setEdge("E", alt and "not" or "must") end
function toggleForceS(_, _, alt) setEdge("S", alt and "not" or "must") end
function toggleForceW(_, _, alt) setEdge("W", alt and "not" or "must") end

-- ---------------------------------------------------------------- panel

--[[ x/z are world units along the bag's axes. Dividing by the bag's scale per
axis undoes what createButton multiplies in, so a 3.7 x 4.9 x 2.2 bag still
gets square text. y is measured from the bag's base, not its centre, because a
tall bag would otherwise float the panel in mid-air. Assumes the bag stands
upright. ]]
local function addButton(fn, label, tooltip, x, z, width, color)
  local k = PANEL.SHARPNESS
  local sc = self.getScale()
  local pos = self.getPosition()
  local b = self.getBounds()
  local baseY = b.center.y - b.size.y / 2
  local s = PANEL.BTN_SCALE / k
  self.createButton({
    click_function = fn, function_owner = self, label = label, tooltip = tooltip,
    position = {x / sc.x, (baseY + PANEL.LIFT - pos.y) / sc.y, z / sc.z}, rotation = {0, 0, 0},
    scale = {s / sc.x, s / sc.y, s / sc.z},
    width = width * k, height = PANEL.BTN_H * k, font_size = PANEL.BTN_FONT * k,
    color = color, font_color = PANEL.TEXT_COLOR
  })
  return #self.getButtons() - 1
end

-- Advanced shows / hides the config grid by rebuilding: TTS shifts every later
-- index on removeButton, so a full rebuild is simpler than tracking them.
local function buildPanel()
  self.clearButtons()
  configButton = {}
  forceButton = {}
  addButton("drawRandom", "Draw", "Draw a fully random map tile", PANEL.TOP_X[1], PANEL.TOP_Z,
            PANEL.BTN_W, PANEL.DRAW_COLOR)
  addButton("drawSpecific", "Draw specific", "Draw a tile using the Advanced settings (Random = roll it)",
            PANEL.TOP_X[2], PANEL.TOP_Z, PANEL.BTN_W, PANEL.DRAW_COLOR)
  addButton("spawnGuildhall", "Spawn guildhall", "Spawn the starter tile (random guildhall image)",
            PANEL.TOP_X[3], PANEL.TOP_Z, PANEL.BTN_W, PANEL.GUILDHALL_COLOR)
  addButton("toggleAdvanced", ADVANCED and "Advanced  -" or "Advanced  +", "Show / hide the Draw specific settings",
            0, PANEL.ADVANCED_Z, PANEL.BTN_W, PANEL.ADVANCED_COLOR)
  if ADVANCED then
    for i, key in ipairs(CONFIG_KEYS) do
      local col, row = (i - 1) % 2, math.floor((i - 1) / 2)
      configButton[key] = addButton(CYCLE_FN[key], "", "",
                                    PANEL.GRID_X[col + 1], PANEL.GRID_Z + row * PANEL.ROW_STEP,
                                    PANEL.CONFIG_W, PANEL.CONFIG_COLOR)
    end
    -- Force: On/Off takes the grid's next free cell; the four edges get a row of their own
    local n = #CONFIG_KEYS
    local row = math.floor(n / 2)
    forceButton.toggle = addButton("toggleForce", "", "Force: only draw shapes that fit the edges below",
                                   PANEL.GRID_X[n % 2 + 1], PANEL.GRID_Z + row * PANEL.ROW_STEP,
                                   PANEL.CONFIG_W, PANEL.CONFIG_COLOR)
    local edgeName = {N = "north", E = "east", S = "south", W = "west"}
    for i, edge in ipairs(EDGES) do
      forceButton[edge] = addButton("toggleForce" .. edge, "",
                                    "Left-click: must have a road " .. edgeName[edge] .. " (green)\n" ..
                                    "Right-click: must NOT have one (red)\nSame click again: either way",
                                    PANEL.EDGE_X[i], PANEL.GRID_Z + (row + 1) * PANEL.ROW_STEP,
                                    PANEL.EDGE_W, PANEL.CONFIG_COLOR)
    end
    -- last, so adding them shifts no other button's index. Literal glyph: if the
    -- button font lacks it, it shows an empty box -- swap in "R"
    for i, key in ipairs(CONFIG_KEYS) do
      local col, r = (i - 1) % 2, math.floor((i - 1) / 2)
      addButton(RESET_FN[key], "↺", "Reset " .. CONFIG_TITLES[key] .. " to Random",
                PANEL.GRID_X[col + 1] + PANEL.RESET_DX, PANEL.GRID_Z + r * PANEL.ROW_STEP,
                PANEL.RESET_W, PANEL.ADVANCED_COLOR)
    end
    refreshConfigLabels()
  end
end

function toggleAdvanced()
  ADVANCED = not ADVANCED
  buildPanel()
end

-- ---------------------------------------------------------------- rolling

--[[ A biome on the tiers sheet rolls a tier (weights tier:<biome>). The tier
is never stored or shown: it swaps the biome for its gmnotes biome (a drawn
city becomes settlement / town / city) and picks the TILESET whose images the
tile uses (today each tier has its own: settlement, town, city). Any other biome
is its own tileset. The image key is always tileset|pattern|orientation|density. ]]
local function finish(t)
  local tiers = MAPTILE.tiers[t.biome]
  if tiers ~= nil then
    local tier = tiers[pick(MAPTILE.weights["tier:" .. t.biome])]
    t.biome = tier.gmnotes
    t.tileset = tier.tileset
  else
    t.tileset = t.biome
  end
  t.key = table.concat({t.tileset, t.pattern, t.orientation, t.density}, "|")
  return t
end

--[[ Every pattern+rotation with a road on ALL of `must` ("NE") and on none of
`mustNot`, one entry each, so the pick is even across shapes rather than
patterns. Both "" = every shape. ]]
local function shapesWith(must, mustNot)
  local shapes = {}
  for _, p in ipairs(MAPTILE.patterns) do
    for _, o in ipairs(MAPTILE.orientations[p] or {}) do
      local fits = true
      for e in must:gmatch(".") do
        if not o:find(e, 1, true) then fits = false end
      end
      for e in (mustNot or ""):gmatch(".") do
        if o:find(e, 1, true) then fits = false end
      end
      if fits then table.insert(shapes, {pattern = p, orientation = o}) end
    end
  end
  return shapes
end

--[[ Fill every Random in spec from the weight pools, in dependency order.
Force replaces the pattern + orientation rolls. ]]
local function roll(spec)
  local t = {}
  local w = MAPTILE.weights
  t.deck = spec.deck ~= RANDOM and spec.deck or pick(w.deck)
  t.biome = spec.biome ~= RANDOM and spec.biome or pick(w["biome:" .. t.deck])
  local shapes = forced(spec) and shapesWith(spec.edges or "", spec.noedges or "") or {}
  if #shapes > 0 then
    local shape = pick(shapes)
    t.pattern, t.orientation = shape.pattern, shape.orientation
  else
    t.pattern = spec.pattern ~= RANDOM and spec.pattern or pick(w.pattern)
    t.orientation = spec.orientation ~= RANDOM and spec.orientation or pick(w["orientation:" .. t.pattern])
  end
  t.density = spec.density ~= RANDOM and spec.density or pick(w.density)
  return finish(t)
end

--[[ The starter tile. A pattern with no guildhall:orientation:<pattern> pool
falls back to the ordinary orientation:<pattern> one. ]]
local function rollGuildhall()
  local w = MAPTILE.weights
  local t = {biome = MAPTILE.guildhall}
  t.deck = MAPTILE.biomes[t.biome].deck
  t.pattern = pick(w["guildhall:pattern"])
  t.orientation = pick(w["guildhall:orientation:" .. t.pattern] or w["orientation:" .. t.pattern])
  t.density = pick(w["guildhall:density"])
  return finish(t)
end

-- Every setting chosen AND nothing left to roll (a tiered biome still rolls its tier).
local function fullySpecified(spec)
  if forced(spec) then return false end
  for _, key in ipairs(CONFIG_KEYS) do
    if spec[key] == RANDOM then return false end
  end
  return MAPTILE.tiers[spec.biome] == nil
end

-- ---------------------------------------------------------------- spawning

local function encodeMemo(m)
  return "d=" .. tostring(m.d) .. "|explore=" .. tostring(m.explore) .. "|rendered=" .. tostring(m.rendered)
end

local function parseMemo(memo)
  local m = {}
  for k, v in string.gmatch(memo or "", "([%w_]+)=([^|]*)") do m[k] = v end
  m.explore = tonumber(m.explore) or 0
  m.rendered = tonumber(m.rendered) or 0
  return m
end

--[[ Calls fn(data) with the template's saved object data, taking the
template out of the bag (and straight back in) the first time only. ]]
local function withTemplate(fn)
  if templateData ~= nil then return fn(templateData) end
  local entry = nil
  for _, e in ipairs(self.getObjects()) do
    if (e.gm_notes or e.gmNotes or "") == TEMPLATE_GM then entry = e end
  end
  if entry == nil then
    broadcastToAll('Maptile Manager: no template in the bag -- add a Custom Tile with GMNotes "' ..
                   TEMPLATE_GM .. '".', {1, 0.3, 0.3})
    return
  end
  local b = self.getBounds()
  self.takeObject({
    guid = entry.guid, smooth = false,
    position = {b.center.x, b.center.y + b.size.y / 2 + 2.5, b.center.z},
    callback_function = function(obj)
      templateData = obj.getData()
      obj.setLock(false)
      self.putObject(obj)
      fn(templateData)
    end
  })
end

local function spawnTile(t, url)
  local deck = deckById(t.deck)
  local biome = MAPTILE.biomes[t.biome]
  withTemplate(function(template)
    local data = copy(template)
    data.GUID = nil  -- let TTS assign a fresh one
    data.Nickname = biome.name
    data.Description = biome.description or ""
    data.GMNotes = t.biome
    data.Memo = encodeMemo({d = t.density, explore = MAPTILE.explore[t.density] or 0, rendered = 0})
    data.LuaScript = ""
    data.Tooltip = false  -- the tile's "?" button turns hover name + description on
    data.CustomImage = data.CustomImage or {}
    data.CustomImage.ImageURL = url
    if deck and deck.back ~= "" then data.CustomImage.ImageSecondaryURL = deck.back end
    local tags = {TILE_TAG, "Region:" .. t.deck, "Biome:" .. t.biome}
    for _, tag in ipairs(data.Tags or {}) do
      if tag ~= TEMPLATE_TAG and tag ~= TILE_TAG then table.insert(tags, tag) end
    end
    data.Tags = tags
    spawnObjectData({
      data = data,
      position = self.positionToWorld(SPAWN.OFFSET),
      rotation = SPAWN.ROTATION,
      callback_function = function(obj) renderTile(obj) end
    })
  end)
end

--[[ Roll until a tile with an image URL comes up. `exact` = the roll cannot
change, so one miss is final. ]]
local function drawWith(rollFn, exact, who)
  if #MAPTILE.decks == 0 then
    broadcastToAll("Maptile Manager: no tile data -- run tools/sync/sync_maptile_manager.py and push.", {1, 0.3, 0.3})
    return
  end
  for _ = 1, (exact and 1 or MAX_REROLLS) do
    local t = rollFn()
    local url = MAPTILE.images[t.key]
    if url ~= nil then
      spawnTile(t, url)
      return
    end
    if exact then
      broadcastToColor("No image URL for " .. t.key .. " -- fill it in data/maptile.xlsx and sync.",
                       who, {1, 0.6, 0.3})
      return
    end
  end
  broadcastToColor("No drawable tile matches these settings yet (missing URLs in data/maptile.xlsx).",
                   who, {1, 0.6, 0.3})
end

local function draw(spec, who)
  drawWith(function() return roll(spec) end, fullySpecified(spec), who)
end

function drawRandom(_, color)
  draw({deck = RANDOM, biome = RANDOM, pattern = RANDOM, orientation = RANDOM, density = RANDOM}, color)
end

function drawSpecific(_, color)
  if forced(SETTINGS) and #shapesWith(SETTINGS.edges, SETTINGS.noedges) == 0 then
    broadcastToColor("No tile shape fits those Force edges.", color, {1, 0.6, 0.3})
    return
  end
  draw(SETTINGS, color)
end

function spawnGuildhall(_, color)
  drawWith(rollGuildhall, false, color)
end

-- ---------------------------------------------------------------- tile buttons

local function tileButton(obj, fn, label, tooltip, pos, color, width, textColor)
  local f, w, h, sc = sharp(TILE_UI.BTN_FONT, width or TILE_UI.BTN_W, TILE_UI.BTN_H, TILE_UI.BTN_SCALE,
                            TILE_UI.SHARPNESS)
  obj.createButton({
    click_function = fn, function_owner = self, label = label, tooltip = tooltip,
    position = {pos[1], TILE_UI.LIFT, pos[3]}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, color = color, font_color = textColor or TILE_UI.TEXT_COLOR
  })
end

--[[ Draw a tile's buttons from its GMNotes (biome) and memo. Anything that is
not a known biome is left alone. ]]
renderTile = function(obj)
  if isGone(obj) or MAPTILE.biomes[obj.getGMNotes()] == nil then return end
  obj.clearButtons()
  local m = parseMemo(obj.memo)
  if m.explore > 0 and choosing[obj.getGUID()] then
    for i, c in ipairs(EXPLORE_CHOICES) do
      tileButton(obj, c.fn, c.label, c.tooltip, TILE_UI.CHOICE_POS[i], TILE_UI.EXPLORE_COLOR, TILE_UI.CHOICE_W)
    end
  elseif m.explore > 0 then
    tileButton(obj, "tileExplore", "Explore: " .. m.explore, "Explore this tile (" .. m.explore .. " left)",
               TILE_UI.EXPLORE_POS, TILE_UI.EXPLORE_COLOR)
  end
  if m.rendered == 0 then
    tileButton(obj, "tileRender", "Render", "Spawn what this tile holds (once)", TILE_UI.RENDER_POS,
               TILE_UI.RENDER_COLOR)
  end
  tileButton(obj, "tileHelp", "?", "Toggle show-effects; hover over the tile to see its effects.",
             TILE_UI.HELP_POS, TILE_UI.HELP_COLOR, TILE_UI.HELP_W,
             obj.tooltip and TILE_UI.HELP_ON_TEXT or TILE_UI.HELP_OFF_TEXT)
end

-- {{outcome, weight}, ...} -> one outcome id, or nil when every weight is 0.
local function rollWeighted(list)
  local total = 0
  for _, e in ipairs(list or {}) do total = total + e[2] end
  if total <= 0 then return nil end
  local r = math.random(total)
  for _, e in ipairs(list) do
    r = r - e[2]
    if r <= 0 then return e[1] end
  end
end

-- Just above the tile's centre, so what lands drops flat onto it.
local function abovePosition(obj)
  local p = obj.getPosition()
  return {p.x, p.y + EXPLORE.DROP, p.z}
end

--[[ The top card of the tile's region bag, face up on the tile. TAKEN, not
cloned: an event drawn is gone from its bag until someone puts it back. No
shuffle, so anything that sets the bag's order is respected. Global renders the
card as it leaves the bag (onObjectLeaveContainer). ]]
local function drawEvent(obj, deck)
  local bag = getObjectFromGUID(EVENT_BAGS[deck] or "")
  if isGone(bag) then return "no event bag for " .. deck end
  if #bag.getObjects() == 0 then return "the " .. deck .. " event bag is empty" end
  bag.takeObject({position = abovePosition(obj), rotation = {0, obj.getRotation().y, 0}, smooth = false})
  return nil
end

-- One line of an outcome's flavor, or its bare name when none is written.
local function flavorOf(outcome)
  if #outcome.flavor > 0 then return pick(outcome.flavor) end
  return outcome.name .. "."
end

-- "{biome}" in a stamp becomes the tile's biome, so a node knows where it was found.
local function fillStamp(text, biome)
  return (string.gsub(text or "", "{biome}", biome))
end

local function exploreHead(obj, color, category, left)
  return string.format(EXPLORE_HEADS[category], Player[color].steam_name, obj.getName(), left)
end

--[[ Resources / Points of interest: roll the biome's weights for the category,
clone the landmark (if any) onto the tile through Global, stamped with the
outcome's GMNotes + memo, and announce the flavor. ]]
local function findLandmark(obj, color, left, category)
  local biome = obj.getGMNotes()
  local head = exploreHead(obj, color, category, left)
  local id = rollWeighted((MAPTILE.exploration[biome] or {})[category])
  local outcome = MAPTILE.outcomes[id or ""]
  if outcome == nil then
    broadcastToAll(head .. "nothing to find (no " .. category .. " weights for " .. biome .. ").", {1, 0.6, 0.3})
    return
  end
  local said = flavorOf(outcome)
  if outcome.kind == "landmark" then
    local landmark = pick(outcome.landmarks)
    Global.call("spawnCopyFromBagFor", {
      category = "landmark", name = landmark, position = abovePosition(obj),
      stamp = {gm_notes = fillStamp(outcome.gmnotes, biome), memo = fillStamp(outcome.memo, biome)}
    })
    said = said .. " (" .. landmark .. ")"
  end
  broadcastToAll(head .. said, {0.7, 0.9, 1})
end

local function findExperience(obj, color, left)
  local said = MAPTILE.outcomes.event and flavorOf(MAPTILE.outcomes.event) or "An event."
  local err = drawEvent(obj, MAPTILE.biomes[obj.getGMNotes()].deck)
  if err then said = said .. " (" .. err .. ")" end
  broadcastToAll(exploreHead(obj, color, "event", left) .. said, {0.7, 0.9, 1})
end

--[[ Global owns the spawn pipeline (bags, unique takes, gold). Global.call
passes one table, and the tile goes by GUID because spawnFrom needs the object. ]]
local function renderEffect(obj)
  local spawn = MAPTILE.table[obj.getGMNotes()]
  if spawn == nil then
    printToAll(obj.getName() .. ": nothing to render.", {0.8, 0.8, 0.8})
    return
  end
  Global.call("spawnFromFor", {guid = obj.getGUID(), spawn = spawn})
end

-- Close a tile's choices: stop its timeout so a late tick cannot re-render a newer menu.
local function closeChoices(guid)
  if choosing[guid] ~= nil then Wait.stop(choosing[guid]) end
  choosing[guid] = nil
end

--[[ Explore: swap the button for the four choices. Nothing is spent until one
is picked; left alone for CHOICE_TIMEOUT seconds, Explore comes back. ]]
function tileExplore(obj, color)
  if parseMemo(obj.memo).explore <= 0 then
    broadcastToColor("Nothing left to explore here.", color, {1, 0.6, 0.3})
    return
  end
  local guid = obj.getGUID()
  closeChoices(guid)
  choosing[guid] = Wait.time(function()
    choosing[guid] = nil
    renderTile(obj)
  end, EXPLORE.CHOICE_TIMEOUT)
  renderTile(obj)
end

-- Picking a choice spends one explore and puts the Explore button back. nil = none left.
local function spendExplore(obj, color)
  closeChoices(obj.getGUID())
  local m = parseMemo(obj.memo)
  if m.explore <= 0 then
    broadcastToColor("Nothing left to explore here.", color, {1, 0.6, 0.3})
    renderTile(obj)
    return nil
  end
  m.explore = m.explore - 1
  obj.memo = encodeMemo(m)
  renderTile(obj)
  return m.explore
end

function exploreResources(obj, color)
  local left = spendExplore(obj, color)
  if left then findLandmark(obj, color, left, "resource") end
end

function explorePoi(obj, color)
  local left = spendExplore(obj, color)
  if left then findLandmark(obj, color, left, "poi") end
end

function exploreExperiences(obj, color)
  local left = spendExplore(obj, color)
  if left then findExperience(obj, color, left) end
end

-- No announcement of its own: the choice it lands on announces itself.
function exploreWander(obj, color, alt)
  local choices = {exploreResources, explorePoi, exploreExperiences}
  choices[math.random(#choices)](obj, color, alt)
end

-- obj.tooltip is saved with the object, so the state needs no memo field.
function tileHelp(obj)
  obj.tooltip = not obj.tooltip
  renderTile(obj)
end

function tileRender(obj)
  local m = parseMemo(obj.memo)
  if m.rendered ~= 0 then return end
  m.rendered = 1
  obj.memo = encodeMemo(m)
  renderTile(obj)
  renderEffect(obj)
end

-- ---------------------------------------------------------------- lifecycle

function onSave()
  local state = copy(SETTINGS)
  state.advanced = ADVANCED and "1" or "0"
  return JSON.encode(state)
end

function onLoad(state)
  if state and state ~= "" then
    local saved = JSON.decode(state)
    for _, key in ipairs(CONFIG_KEYS) do
      if saved and saved[key] ~= nil then SETTINGS[key] = tostring(saved[key]) end
    end
    ADVANCED = saved ~= nil and saved.advanced == "1"
    SETTINGS.force = saved ~= nil and saved.force == "on" and "on" or "off"
    -- rebuilt in NESW order; an edge saved as both keeps "must"
    local must, mustNot = "", ""
    for _, e in ipairs(EDGES) do
      if saved ~= nil and tostring(saved.edges or ""):find(e, 1, true) then
        must = must .. e
      elseif saved ~= nil and tostring(saved.noedges or ""):find(e, 1, true) then
        mustNot = mustNot .. e
      end
    end
    SETTINGS.edges, SETTINGS.noedges = must, mustNot
  end
  -- a saved value the data no longer has falls back to Random
  for _, key in ipairs(CONFIG_KEYS) do
    local ok = false
    for _, v in ipairs(options(key)) do
      if v == SETTINGS[key] then ok = true end
    end
    if not ok then SETTINGS[key] = options(key)[1] end
  end
  buildPanel()
  for _, obj in ipairs(getObjectsWithTag(TILE_TAG)) do
    renderTile(obj)
  end
end
