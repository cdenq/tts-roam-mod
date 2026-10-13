--[[ Maptile Manager: draw overworld map tiles from the generated art.

Source for the in-game bag nicknamed "Maptile Manager" (GUID b77050). Staged
by tools/sync_maptile_manager.py, which also inlines MAPTILE from
data/maptile.xlsx.

THE PANEL

  [ Draw ]            [ Draw specific ]
  [ Deck: Random                      ]   left-click = next, right-click = back
  [ Biome: Random                     ]   only the chosen deck's biomes
  [ Pattern: Random                   ]
  [ Orientation: Random               ]   only the chosen pattern's rotations
  [ Density: Random                   ]

Draw ignores the settings and rolls everything; Draw specific rolls only what
is still Random. Every roll goes deck -> biome -> pattern -> orientation ->
density, each from its pool in MAPTILE.weights, so a deck with more biomes is
not drawn more often. Rolls are free: a tile can come up twice.

A DRAWN TILE

A copy of the bag's template tile (GMNotes "maptile_template", tagged
Template), stamped with:

  name         "<Biome> <Pattern> Tile"
  description  biome_descriptions sheet
  GMNotes      the biome id -- the key everything else reads
  memo         "d=<density>|explore=<left>|rendered=<0/1>"
  images       front = the rolled image, back = its deck's back
  tag          MapTile

Its buttons belong to THIS script (function_owner = self), so a tile only
works while the manager is on the table. TTS does not save buttons, so onLoad
re-renders every MapTile from its GMNotes + memo.
]]

--[[ BEGIN GENERATED MAPTILE DATA -- do not edit ]]
MAPTILE = {decks = {}, biomes = {}, patterns = {}, orientations = {}, densities = {},
           images = {}, explore = {}, weights = {}, table = {}}
--[[ END GENERATED MAPTILE DATA ]]

TEMPLATE_GM = "maptile_template"
TEMPLATE_TAG = "Template"
TILE_TAG = "MapTile"
RANDOM = "random"
MAX_REROLLS = 40

PATTERN_NAMES = {deadend = "Dead End", corner = "Corner", straight = "Straight", tee = "Tee", cross = "Cross"}

--[[ Manager panel, object-local units x the bag's scale; +z is the bag's
front. Same SHARPNESS trick as the importers: big font, small scale. ]]
PANEL = {
  SHARPNESS = 4,
  TOP_Z = 2.2,          -- Draw / Draw specific row
  TOP_X = {-1.9, 1.9},
  ROW_START_Z = 3.1,    -- first config row
  ROW_STEP = 0.8,
  LIFT = 0.25,
  BTN_W = 900, BTN_H = 330, BTN_FONT = 160,
  WIDE_W = 1900,
  BTN_SCALE = 0.75,
  DRAW_COLOR = {0.25, 0.45, 0.3},
  CONFIG_COLOR = {0.3, 0.34, 0.5},
  LOCKED_COLOR = {0.32, 0.32, 0.32},
  TEXT_COLOR = {1, 1, 1},
}

-- Where a drawn tile lands, in the bag's local units, and how it is turned.
SPAWN = {OFFSET = {-5.5, 1, 0}, ROTATION = {0, 180, 0}}

-- Buttons on a drawn tile, in the TILE's local units. Tune to the template's scale.
TILE_UI = {
  SHARPNESS = 4,
  LIFT = 0.25,
  EXPLORE_POS = {0, 0, 0.62},
  RENDER_POS = {0, 0, -0.62},
  BTN_W = 520, BTN_H = 160, BTN_FONT = 95, BTN_SCALE = 0.5,
  EXPLORE_COLOR = {0.2, 0.42, 0.5},
  EMPTY_COLOR = {0.35, 0.35, 0.35},
  RENDER_COLOR = {0.55, 0.38, 0.2},
  TEXT_COLOR = {1, 1, 1},
}

CONFIG_KEYS = {"deck", "biome", "pattern", "orientation", "density"}
CONFIG_TITLES = {deck = "Deck", biome = "Biome", pattern = "Pattern", orientation = "Orientation",
                 density = "Density"}

SETTINGS = {deck = RANDOM, biome = RANDOM, pattern = RANDOM, orientation = RANDOM, density = RANDOM}
local configButton = {}   -- key -> button index on self
local templateData = nil  -- cached getData() of the template; refreshed each load
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

--[[ The values one config button cycles through, Random first. Dependent
buttons collapse to {Random} while what they depend on is Random. ]]
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
  end
  return value
end

local function refreshConfigLabels()
  for _, key in ipairs(CONFIG_KEYS) do
    local idx = configButton[key]
    if idx ~= nil then
      local locked = #options(key) == 1
      self.editButton({index = idx, label = CONFIG_TITLES[key] .. ": " .. display(key, SETTINGS[key]),
                       color = locked and PANEL.LOCKED_COLOR or PANEL.CONFIG_COLOR})
    end
  end
end

--[[ The one cycling rule every config button shares: step forward on a
left-click, back on a right-click (alt_click), wrapping round. Changing a
deck or pattern resets the setting that depends on it. ]]
local function cycle(key, back)
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

-- Button callbacks must be global functions named by string.
function cycleDeck(_, _, alt) cycle("deck", alt) end
function cycleBiome(_, _, alt) cycle("biome", alt) end
function cyclePattern(_, _, alt) cycle("pattern", alt) end
function cycleOrientation(_, _, alt) cycle("orientation", alt) end
function cycleDensity(_, _, alt) cycle("density", alt) end
CYCLE_FN = {deck = "cycleDeck", biome = "cycleBiome", pattern = "cyclePattern",
            orientation = "cycleOrientation", density = "cycleDensity"}

-- ---------------------------------------------------------------- panel

local function addButton(fn, label, tooltip, x, z, width, color)
  local f, w, h, sc = sharp(PANEL.BTN_FONT, width, PANEL.BTN_H, PANEL.BTN_SCALE, PANEL.SHARPNESS)
  self.createButton({
    click_function = fn, function_owner = self, label = label, tooltip = tooltip,
    position = {x, PANEL.LIFT, z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, color = color, font_color = PANEL.TEXT_COLOR
  })
  return #self.getButtons() - 1
end

local function buildPanel()
  self.clearButtons()
  addButton("drawRandom", "Draw", "Draw a fully random map tile", PANEL.TOP_X[1], PANEL.TOP_Z,
            PANEL.BTN_W, PANEL.DRAW_COLOR)
  addButton("drawSpecific", "Draw specific", "Draw a tile using the settings below (Random = roll it)",
            PANEL.TOP_X[2], PANEL.TOP_Z, PANEL.BTN_W, PANEL.DRAW_COLOR)
  for i, key in ipairs(CONFIG_KEYS) do
    configButton[key] = addButton(CYCLE_FN[key], "", "Left-click: next   Right-click: back",
                                  0, PANEL.ROW_START_Z + (i - 1) * PANEL.ROW_STEP, PANEL.WIDE_W,
                                  PANEL.CONFIG_COLOR)
  end
  refreshConfigLabels()
end

-- ---------------------------------------------------------------- rolling

--[[ Fill every Random in spec from the weight pools, in dependency order. ]]
local function roll(spec)
  local t = {}
  local w = MAPTILE.weights
  t.deck = spec.deck ~= RANDOM and spec.deck or pick(w.deck)
  t.biome = spec.biome ~= RANDOM and spec.biome or pick(w["biome:" .. t.deck])
  t.pattern = spec.pattern ~= RANDOM and spec.pattern or pick(w.pattern)
  t.orientation = spec.orientation ~= RANDOM and spec.orientation or pick(w["orientation:" .. t.pattern])
  t.density = spec.density ~= RANDOM and spec.density or pick(w.density)
  t.key = table.concat({t.biome, t.pattern, t.orientation, t.density}, "|")
  return t
end

local function fullySpecified(spec)
  for _, key in ipairs(CONFIG_KEYS) do
    if spec[key] == RANDOM then return false end
  end
  return true
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
    data.Nickname = biome.name .. " " .. (PATTERN_NAMES[t.pattern] or t.pattern) .. " Tile"
    data.Description = biome.description or ""
    data.GMNotes = t.biome
    data.Memo = encodeMemo({d = t.density, explore = MAPTILE.explore[t.density] or 0, rendered = 0})
    data.LuaScript = ""
    data.CustomImage = data.CustomImage or {}
    data.CustomImage.ImageURL = url
    if deck and deck.back ~= "" then data.CustomImage.ImageSecondaryURL = deck.back end
    local tags = {TILE_TAG}
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

local function draw(spec, who)
  if #MAPTILE.decks == 0 then
    broadcastToAll("Maptile Manager: no tile data -- run tools/sync_maptile_manager.py and push.", {1, 0.3, 0.3})
    return
  end
  for _ = 1, (fullySpecified(spec) and 1 or MAX_REROLLS) do
    local t = roll(spec)
    local url = MAPTILE.images[t.key]
    if url ~= nil then
      spawnTile(t, url)
      return
    end
    if fullySpecified(spec) then
      broadcastToColor("No image URL for " .. t.key .. " -- fill it in data/maptile.xlsx and sync.",
                       who, {1, 0.6, 0.3})
      return
    end
  end
  broadcastToColor("No drawable tile matches these settings yet (missing URLs in data/maptile.xlsx).",
                   who, {1, 0.6, 0.3})
end

function drawRandom(_, color)
  draw({deck = RANDOM, biome = RANDOM, pattern = RANDOM, orientation = RANDOM, density = RANDOM}, color)
end

function drawSpecific(_, color)
  draw(SETTINGS, color)
end

-- ---------------------------------------------------------------- tile buttons

local function tileButton(obj, fn, label, tooltip, pos, color)
  local f, w, h, sc = sharp(TILE_UI.BTN_FONT, TILE_UI.BTN_W, TILE_UI.BTN_H, TILE_UI.BTN_SCALE, TILE_UI.SHARPNESS)
  obj.createButton({
    click_function = fn, function_owner = self, label = label, tooltip = tooltip,
    position = {pos[1], TILE_UI.LIFT, pos[3]}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, color = color, font_color = TILE_UI.TEXT_COLOR
  })
end

--[[ Draw a tile's buttons from its GMNotes (biome) and memo. Anything that is
not a known biome is left alone. ]]
renderTile = function(obj)
  if isGone(obj) or MAPTILE.biomes[obj.getGMNotes()] == nil then return end
  obj.clearButtons()
  local m = parseMemo(obj.memo)
  tileButton(obj, "tileExplore", "Explore: " .. m.explore, "Explore this tile (" .. m.explore .. " left)",
             TILE_UI.EXPLORE_POS, m.explore > 0 and TILE_UI.EXPLORE_COLOR or TILE_UI.EMPTY_COLOR)
  if m.rendered == 0 then
    tileButton(obj, "tileRender", "Render", "Spawn what this tile holds (once)", TILE_UI.RENDER_POS,
               TILE_UI.RENDER_COLOR)
  end
end

-- TODO(plans/auto_TODO.md "Maptile Explore action"): the exploration itself.
local function exploreEffect(obj, color, left)
  broadcastToAll(Player[color].steam_name .. " explores the " .. obj.getName() .. " (" .. left .. " left).",
                 {0.7, 0.9, 1})
end

-- TODO(plans/auto_TODO.md "Maptile Render table"): spawn what maptile_table lists.
local function renderEffect(obj, color)
  local row = MAPTILE.table[obj.getGMNotes()] or {}
  local parts = {}
  for k, v in pairs(row) do
    if v ~= "" then table.insert(parts, k .. "=" .. v) end
  end
  table.sort(parts)
  printToAll("Render " .. obj.getName() .. ": " .. (#parts > 0 and table.concat(parts, ", ") or "(nothing listed)"),
             {1, 0.85, 0.5})
end

function tileExplore(obj, color)
  local m = parseMemo(obj.memo)
  if m.explore <= 0 then
    broadcastToColor("Nothing left to explore here.", color, {1, 0.6, 0.3})
    return
  end
  m.explore = m.explore - 1
  obj.memo = encodeMemo(m)
  renderTile(obj)
  exploreEffect(obj, color, m.explore)
end

function tileRender(obj, color)
  local m = parseMemo(obj.memo)
  if m.rendered ~= 0 then return end
  m.rendered = 1
  obj.memo = encodeMemo(m)
  renderTile(obj)
  renderEffect(obj, color)
end

-- ---------------------------------------------------------------- lifecycle

function onSave()
  return JSON.encode(SETTINGS)
end

function onLoad(state)
  if state and state ~= "" then
    local saved = JSON.decode(state)
    for _, key in ipairs(CONFIG_KEYS) do
      if saved and saved[key] ~= nil then SETTINGS[key] = tostring(saved[key]) end
    end
  end
  -- a saved value the data no longer has falls back to Random
  for _, key in ipairs(CONFIG_KEYS) do
    local ok = false
    for _, v in ipairs(options(key)) do
      if v == SETTINGS[key] then ok = true end
    end
    if not ok then SETTINGS[key] = RANDOM end
  end
  buildPanel()
  for _, obj in ipairs(getObjectsWithTag(TILE_TAG)) do
    renderTile(obj)
  end
end
