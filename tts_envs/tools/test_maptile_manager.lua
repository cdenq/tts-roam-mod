-- Offline harness for the staged Maptile Manager script (stubs the TTS API, fakes every image URL).
-- Run from the repo root after a sync:
--   tts_envs/tools/bin/lua54.exe tts_envs/tools/test_maptile_manager.lua ".tts/objects/Maptile Manager.b77050.lua"
local path = arg[1]
local pass, fail = 0, 0
local function check(cond, what)
  if cond then pass = pass + 1; print("  ok  " .. what) else fail = fail + 1; print("  FAIL " .. what) end
end

-- ---- TTS stubs
local messages = {}
function broadcastToAll(m) table.insert(messages, m) end
function broadcastToColor(m) table.insert(messages, m) end
function printToAll(m) table.insert(messages, m) end
Player = setmetatable({}, {__index = function(_, c) return {steam_name = c .. "Player"} end})
JSON = {encode = function(t) local s = {} for k, v in pairs(t) do s[#s + 1] = k .. "=" .. v end return table.concat(s, ";") end,
        decode = function(s) local t = {} for k, v in s:gmatch("(%w+)=([^;]*)") do t[k] = v end return t end}

local function newObject(fields)
  local o = fields or {}
  o.buttons = {}
  o.memo = o.memo or ""
  function o.createButton(p) table.insert(o.buttons, p) end
  function o.clearButtons() o.buttons = {} end
  function o.getButtons() return o.buttons end
  function o.editButton(p) for k, v in pairs(p) do if k ~= "index" then o.buttons[p.index + 1][k] = v end end end
  function o.getGMNotes() return o.GMNotes or "" end
  function o.getName() return o.Nickname or "" end
  function o.isDestroyed() return false end
  function o.setLock() end
  return o
end

local templateObj = newObject({Nickname = "tpl", GMNotes = "maptile_template"})
function templateObj.getData()
  return {GUID = "abc123", Nickname = "tpl", GMNotes = "maptile_template", Tags = {"Template"},
          CustomImage = {ImageURL = "tpl_front", ImageSecondaryURL = "tpl_back", CustomTile = {Thickness = 0.2}}}
end
self = newObject()
local takes = 0
function self.getObjects() return {{guid = "abc123", gm_notes = "maptile_template"}} end
function self.getBounds() return {center = {x = 0, y = 1, z = 0}, size = {x = 2, y = 2, z = 2}} end
function self.takeObject(p) takes = takes + 1; p.callback_function(templateObj) end
function self.putObject() end
function self.positionToWorld(p) return p end
local spawned = {}
function spawnObjectData(p)
  local o = newObject({Nickname = p.data.Nickname, GMNotes = p.data.GMNotes, memo = p.data.Memo, data = p.data})
  table.insert(spawned, o)
  p.callback_function(o)
end
local tagged = {}
function getObjectsWithTag() return tagged end

dofile(path)
-- every combination gets a fake URL, as if the sheet were filled
for _, d in ipairs(MAPTILE.decks) do
  d.back = "back_" .. d.id
  for _, b in ipairs(d.biomes) do
    for _, p in ipairs(MAPTILE.patterns) do
      for _, o in ipairs(MAPTILE.orientations[p]) do
        for _, n in ipairs(MAPTILE.densities) do
          MAPTILE.images[b .. "|" .. p .. "|" .. o .. "|" .. n] = "url:" .. b .. "|" .. p .. "|" .. o .. "|" .. n
        end
      end
    end
  end
end

print("== panel ==")
onLoad("")
check(#self.buttons == 7, "7 panel buttons (Draw, Draw specific, 5 settings)")
local function label(i) return self.buttons[i + 1].label end
check(label(2) == "Deck: Random" and label(3) == "Biome: Random", "everything starts Random")

print("== cycling ==")
cycleBiome(nil, "White", false)
check(SETTINGS.biome == "random", "biome stays Random while deck is Random")
cycleDeck(nil, "White", false)
check(SETTINGS.deck == MAPTILE.decks[1].id, "left-click moves deck forward")
cycleDeck(nil, "White", true)
check(SETTINGS.deck == "random", "right-click moves deck back")
cycleDeck(nil, "White", true)
check(SETTINGS.deck == MAPTILE.decks[#MAPTILE.decks].id, "right-click wraps to the last deck")
cycleBiome(nil, "White", false)
local firstBiome = MAPTILE.decks[#MAPTILE.decks].biomes[1]
check(SETTINGS.biome == firstBiome, "biome now cycles that deck's biomes")
cycleDeck(nil, "White", false)
check(SETTINGS.biome == "random", "changing deck resets biome")
cycleOrientation(nil, "White", false)
check(SETTINGS.orientation == "random", "orientation locked while pattern is Random")
cyclePattern(nil, "White", false); cyclePattern(nil, "White", false)
check(SETTINGS.pattern == MAPTILE.patterns[2], "pattern cycles")
cycleOrientation(nil, "White", false)
check(SETTINGS.orientation == MAPTILE.orientations[SETTINGS.pattern][1], "orientation cycles that pattern's rotations")
cyclePattern(nil, "White", false)
check(SETTINGS.orientation == "random", "changing pattern resets orientation")
cycleDensity(nil, "White", false)
check(SETTINGS.density == "1", "density cycles 1..3")
check(label(6) == "Density: 1", "label follows the value")

print("== draw specific ==")
SETTINGS = {deck = "woodland", biome = "forest", pattern = "corner", orientation = "ES", density = "2"}
drawSpecific(nil, "White")
local t = spawned[#spawned]
check(t ~= nil and t.data.CustomImage.ImageURL == "url:forest|corner|ES|2", "spawns the exact image")
check(t.data.CustomImage.ImageSecondaryURL == "back_woodland", "back = the deck's back")
check(t.data.Nickname == "Forest Corner Tile", "name: <Biome> <Pattern> Tile")
check(t.data.GMNotes == "forest", "GMNotes = biome")
check(t.data.Memo == "d=2|explore=2|rendered=0", "memo from density table")
check(t.data.GUID == nil, "GUID cleared for TTS to assign")
check(t.data.Tags[1] == "MapTile" and #t.data.Tags == 1, "tagged MapTile, Template tag stripped")
check(#t.buttons == 2 and t.buttons[1].label == "Explore: 2" and t.buttons[2].label == "Render", "tile shows Explore + Render")
check(takes == 1, "template taken out once")

print("== tile buttons ==")
tileExplore(t, "Red")
check(t.memo == "d=2|explore=1|rendered=0" and t.buttons[1].label == "Explore: 1", "explore decrements memo + label")
tileExplore(t, "Red"); tileExplore(t, "Red")
check(t.memo:find("explore=0") and messages[#messages]:find("Nothing left"), "explore stops at 0")
tileRender(t, "Red")
check(t.memo:find("rendered=1") and #t.buttons == 1, "render runs once, then its button goes")
tileRender(t, "Red")
check(t.memo:find("rendered=1"), "second render does nothing")

print("== draw random ==")
local before = #spawned
for _ = 1, 200 do drawRandom(nil, "White") end
check(#spawned - before == 200, "200 random draws all spawn")
local decks = {}
for i = before + 1, #spawned do
  local b = spawned[i].data.GMNotes
  decks[MAPTILE.biomes[b].deck] = (decks[MAPTILE.biomes[b].deck] or 0) + 1
end
local n = 0
for _ in pairs(decks) do n = n + 1 end
check(n == #MAPTILE.decks, "every deck comes up")
check(takes == 1, "template still taken out only once")

print("== missing url ==")
MAPTILE.images["forest|corner|ES|2"] = nil
SETTINGS = {deck = "woodland", biome = "forest", pattern = "corner", orientation = "ES", density = "2"}
local count = #spawned
drawSpecific(nil, "White")
check(#spawned == count and messages[#messages]:find("No image URL"), "missing url reports, spawns nothing")

print("== reload ==")
tagged = {t}
t.buttons = {}
onLoad("deck=woodland;biome=forest;pattern=tee;orientation=NES;density=3")
check(SETTINGS.biome == "forest" and SETTINGS.orientation == "NES", "settings restored from save")
check(#t.buttons == 1, "onLoad re-renders tagged tiles from memo")
onLoad("deck=nope;biome=forest;pattern=tee;orientation=XX;density=3")
check(SETTINGS.deck == "random" and SETTINGS.orientation == "random", "unknown saved values fall back to Random")

print(string.format("\n%d/%d checks passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
