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
function self.getScale() return {x = 3.7, y = 4.95, z = 2.23} end
function self.getPosition() return {x = 0, y = 1, z = 0} end
local spawned = {}
function spawnObjectData(p)
  local o = newObject({Nickname = p.data.Nickname, GMNotes = p.data.GMNotes, memo = p.data.Memo, data = p.data,
                       tooltip = p.data.Tooltip})
  o.guid = "t" .. (#spawned + 1)
  function o.getGUID() return o.guid end
  table.insert(spawned, o)
  p.callback_function(o)
end
local tagged = {}
function getObjectsWithTag() return tagged end
local globalCalls = {}
Global = {call = function(fn, args) table.insert(globalCalls, {fn = fn, args = args}) end}

dofile(path)
-- every combination gets a fake URL, as if the sheet were filled
local allBiomes = {}
for b, v in pairs(MAPTILE.biomes) do
  allBiomes[v.deck] = allBiomes[v.deck] or {}
  table.insert(allBiomes[v.deck], b)
  for _, tier in pairs(MAPTILE.tiers[b] or {}) do
    if MAPTILE.biomes[tier.tileset] == nil then table.insert(allBiomes[v.deck], tier.tileset) end
  end
end
for _, d in ipairs(MAPTILE.decks) do
  d.back = "back_" .. d.id
  for _, b in ipairs(allBiomes[d.id]) do
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
check(#self.buttons == 4, "4 panel buttons while Advanced is hidden")
check(self.buttons[3].label == "Spawn guildhall", "guildhall on the top row")
local sc = self.buttons[1].scale
check(math.abs(sc[1] * 3.7 - sc[3] * 2.23) < 1e-9, "button scale cancels the bag's uneven scale")
check(math.abs(self.buttons[1].position[2] * 4.95 - (-0.9)) < 1e-9, "buttons sit LIFT above the bag's base")
toggleAdvanced()
check(#self.buttons == 19, "Advanced adds 5 settings + Force + 4 edges + 5 resets")
check(self.buttons[15].label == "↺" and self.buttons[15].click_function == "resetDeck", "a reset beside each setting")
local function label(i) return self.buttons[i + 1].label end
check(label(4) == "Region: Random" and label(5) == "Biome: Random", "everything starts Random; Deck shows as Region")
local function tip(i) return self.buttons[i + 1].tooltip end
check(tip(4):find("^Options: Random, " .. MAPTILE.decks[1].name), "Region tooltip lists its options")
check(tip(5) == "Pick a Region first" and tip(7) == "Pick a Pattern first", "locked buttons say what unlocks them")
check(self.buttons[5].position[3] == self.buttons[6].position[3], "Deck and Biome share a row")

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
check(tip(5):find(MAPTILE.biomes[firstBiome].name, 1, true), "Biome tooltip lists that region's biomes")
cycleDeck(nil, "White", false)
check(SETTINGS.biome == "random", "changing deck resets biome")
cycleOrientation(nil, "White", false)
check(SETTINGS.orientation == "random", "orientation locked while pattern is Random")
cyclePattern(nil, "White", false); cyclePattern(nil, "White", false)
check(SETTINGS.pattern == MAPTILE.patterns[2], "pattern cycles")
cycleOrientation(nil, "White", false)
check(SETTINGS.orientation == MAPTILE.orientations[SETTINGS.pattern][1], "orientation cycles that pattern's rotations")
check(label(7) == "Orientation: " .. ORIENTATION_GLYPHS[SETTINGS.orientation], "orientation label shows the glyph")
cyclePattern(nil, "White", false)
check(SETTINGS.orientation == "random", "changing pattern resets orientation")
cycleDensity(nil, "White", false)
check(SETTINGS.density == "1", "density cycles 1..3")
check(label(8) == "Density: 1", "label follows the value")
toggleAdvanced()
check(#self.buttons == 4, "Advanced again hides them")
cycleDensity(nil, "White", false)
check(SETTINGS.density == "2", "settings still cycle while hidden")
toggleAdvanced()
check(label(8) == "Density: 2", "and show the current value when reopened")

print("== reset ==")
SETTINGS.deck = MAPTILE.decks[1].id; SETTINGS.biome = MAPTILE.decks[1].biomes[1]
SETTINGS.pattern = "tee"; SETTINGS.orientation = "NES"; SETTINGS.density = "2"
resetBiome()
check(SETTINGS.biome == "random" and SETTINGS.deck == MAPTILE.decks[1].id, "reset Biome: only Biome goes Random")
SETTINGS.biome = MAPTILE.decks[1].biomes[1]
resetDeck()
check(SETTINGS.deck == "random" and SETTINGS.biome == "random", "reset Region also resets Biome")
resetPattern()
check(SETTINGS.pattern == "random" and SETTINGS.orientation == "random", "reset Pattern also resets Orientation")
resetDensity()
check(SETTINGS.density == "random" and label(8) == "Density: Random", "reset Density, label follows")
SETTINGS.pattern = "tee"; SETTINGS.orientation = "NES"; SETTINGS.force = "on"
resetPattern()
check(SETTINGS.pattern == "tee", "reset ignored while Force overrides Pattern")
SETTINGS.force = "off"; SETTINGS.density = "2"

print("== force ==")
check(label(9) == "Force: Off" and label(10) == "Force: N" and label(13) == "Force: W", "Force: Off + four edge buttons")
check(self.buttons[11].color == PANEL.LOCKED_COLOR, "edges are grey while Force is off")
SETTINGS.pattern = "tee"; SETTINGS.orientation = "NES"
toggleForceN(); toggleForceE()
check(SETTINGS.edges == "NE" and SETTINGS.force == "off", "edges can be set while Force is off")
toggleForce()
check(SETTINGS.force == "on" and label(9) == "Force: On", "Force toggles on")
check(self.buttons[11].color == PANEL.MUST_COLOR and self.buttons[13].color == PANEL.CONFIG_COLOR,
      "must edges green, either-way edges blue while on")
check(tip(7):find("Overridden"), "overridden buttons say so")
local prev = {SETTINGS.pattern, SETTINGS.orientation}
cyclePattern(nil, "White", false); cycleOrientation(nil, "White", false)
check(SETTINGS.pattern == prev[1] and SETTINGS.orientation == prev[2], "pattern + orientation ignore clicks while forced")
check(self.buttons[7].color == PANEL.LOCKED_COLOR and self.buttons[8].color == PANEL.LOCKED_COLOR,
      "pattern + orientation shown locked while forced")
toggleForceN()
check(SETTINGS.edges == "E", "clicking a selected edge clears it")
toggleForceW(); toggleForceN()
check(SETTINGS.edges == "NEW", "edges stay in NESW order whatever the click order")
toggleForceS(nil, "White", true)
check(SETTINGS.noedges == "S" and self.buttons[13].color == PANEL.MUST_NOT_COLOR, "right-click = must NOT, red")
toggleForceS(nil, "White", true)
check(SETTINGS.noedges == "" and self.buttons[13].color == PANEL.CONFIG_COLOR, "right-click again clears it")
toggleForceN(nil, "White", true)
check(SETTINGS.edges == "EW" and SETTINGS.noedges == "N", "right-click on a green edge switches it to red")
toggleForceN(nil, "White", false)
check(SETTINGS.edges == "NEW" and SETTINGS.noedges == "", "left-click on a red edge switches it to green")

local function drawForced(edges, n, noedges)
  local got, n1 = {}, #spawned
  SETTINGS = {deck = "woodland", biome = "forest", pattern = "cross", orientation = "NESW", density = "2",
              force = "on", edges = edges, noedges = noedges or ""}
  for _ = 1, n do drawSpecific(nil, "White") end
  for i = n1 + 1, #spawned do
    local key = spawned[i].data.CustomImage.ImageURL:match("^url:forest|(%w+|%w+)|2$") or "?"
    got[key] = (got[key] or 0) + 1
  end
  return got, #spawned - n1
end
local function kinds(got)
  local n = 0
  for _ in pairs(got) do n = n + 1 end
  return n
end
local got, n = drawForced("NE", 600)
local ok = n == 600
for k in pairs(got) do
  local o = k:match("|(%w+)$") or ""
  if not (o:find("N") and o:find("E")) then ok = false end
end
check(ok, "N + E: every tile has a road on both, deck/biome/density kept")
check(kinds(got) == 4, "N + E: corner NE, tee NES, tee NEW, cross all come up (got " .. kinds(got) .. ")")
got = drawForced("N", 800)
local tees = 0
for k, c in pairs(got) do
  if k:find("^tee") then tees = tees + c end
end
check(kinds(got) == 8, "N alone: all 8 shapes with an N road (got " .. kinds(got) .. ")")
check(tees > 800 * 3 / 8 * 0.75 and tees < 800 * 3 / 8 * 1.25, "even per shape: tees ~3/8 (got " .. tees .. ")")
got = drawForced("NESW", 50)
check(kinds(got) == 1 and got["cross|NESW"] == 50, "all four edges = only the cross")
got = drawForced("", 400)
check(kinds(got) == 15, "Force on with no edge = any of the 15 shapes (got " .. kinds(got) .. ")")
got = drawForced("W", 40, "NES")
check(kinds(got) == 1 and got["deadend|W"] == 40, "red N E S + green W = only the dead end open to the W")
got = drawForced("", 300, "N")
local noN = true
for k in pairs(got) do
  if (k:match("|(%w+)$") or ""):find("N") then noN = false end
end
check(noN and kinds(got) == 7, "red N alone: the 7 shapes with no N road (got " .. kinds(got) .. ")")
local before = #spawned
SETTINGS.edges, SETTINGS.noedges = "", "NESW"
drawSpecific(nil, "White")
check(#spawned == before and messages[#messages]:find("No tile shape"), "nothing fits: says so, draws nothing")
SETTINGS.force = "off"; SETTINGS.edges = ""; SETTINGS.noedges = ""

print("== draw specific ==")
SETTINGS = {deck = "woodland", biome = "forest", pattern = "corner", orientation = "ES", density = "2"}
drawSpecific(nil, "White")
local t = spawned[#spawned]
check(t ~= nil and t.data.CustomImage.ImageURL == "url:forest|corner|ES|2", "spawns the exact image")
check(t.data.CustomImage.ImageSecondaryURL == "back_woodland", "back = the deck's back")
check(t.data.Nickname == "Forest", "name: the biome name only")
check(t.data.GMNotes == "forest", "GMNotes = biome")
check(t.data.Memo == "d=2|explore=2|rendered=0", "memo from density table")
check(t.data.GUID == nil, "GUID cleared for TTS to assign")
check(t.data.Tags[1] == TILE_TAG and t.data.Tags[2] == "Region:woodland" and t.data.Tags[3] == "Biome:forest"
      and #t.data.Tags == 3, "tagged Maptile + Region + Biome, Template tag stripped")
check(#t.buttons == 3 and t.buttons[1].label == "Explore: 2" and t.buttons[2].label == "Render" and
      t.buttons[3].label == "?", "tile shows Explore + Render + ?")
check(t.data.Tooltip == false and t.buttons[3].font_color[1] > 0.3, "tooltip starts off, ? is grey")
tileHelp(t)
check(t.tooltip == true and t.buttons[3].font_color[1] == 0, "? turns the tooltip on and goes black")
tileHelp(t)
check(t.tooltip == false and t.buttons[3].font_color[1] > 0.3, "? again turns it off")
check(takes == 1, "template taken out once")

print("== tile buttons ==")
tileExplore(t, "Red")
check(t.memo == "d=2|explore=1|rendered=0" and t.buttons[1].label == "Explore: 1", "explore decrements memo + label")
tileExplore(t, "Red"); tileExplore(t, "Red")
check(t.memo:find("explore=0") and messages[#messages]:find("Nothing left"), "explore stops at 0")
check(#t.buttons == 2 and t.buttons[1].label == "Render", "Explore button is gone at 0")
MAPTILE.table.forest = {meeple = {{"Cave"}}, gold = {1, 3}}
tileRender(t)
check(t.memo:find("rendered=1") and #t.buttons == 1 and t.buttons[1].label == "?", "render runs once, then its button goes")
local call = globalCalls[#globalCalls]
check(call and call.fn == "spawnFromFor" and call.args.guid == t.guid and call.args.spawn.meeple[1][1] == "Cave",
      "render hands the biome's spawn table to Global by tile GUID")
tileRender(t)
check(t.memo:find("rendered=1") and #globalCalls == 1, "second render does nothing")
MAPTILE.table.forest = nil

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
local drewGuildhall = false
for i = before + 1, #spawned do
  if spawned[i].data.GMNotes == MAPTILE.guildhall then drewGuildhall = true end
end
check(not drewGuildhall, "Draw never gives the guildhall")
local settlement = nil
for _, d in ipairs(MAPTILE.decks) do
  if d.id == MAPTILE.biomes[MAPTILE.guildhall].deck then settlement = d end
end
local listed = false
for _, b in ipairs(settlement.biomes) do
  if b == MAPTILE.guildhall then listed = true end
end
check(not listed, "Draw specific cannot cycle to the guildhall")

print("== town tiers ==")
local inPool = false
for _, b in ipairs(MAPTILE.weights["biome:settlement"]) do
  if b == "town" or b == "settlement" then inPool = true end
end
check(not inPool, "settlement/town only come from a tier")
MAPTILE.weights["tier:city"] = {"1"}
SETTINGS = {deck = "settlement", biome = "city", pattern = "corner", orientation = "ES", density = "2"}
drawSpecific(nil, "White")
local town = spawned[#spawned]
check(town.data.CustomImage.ImageURL == "url:settlement|corner|ES|2", "tier 1 city uses the settlement images")
check(town.data.GMNotes == "settlement" and town.data.Nickname == "Settlement", "tier 1 becomes a settlement")
check(town.data.Memo == "d=2|explore=2|rendered=0", "tier never reaches the memo")
check(town.data.Tags[2] == "Region:settlement" and town.data.Tags[3] == "Biome:settlement", "tagged by its gmnotes biome")
MAPTILE.weights["tier:city"] = {"2"}
drawSpecific(nil, "White")
check(spawned[#spawned].data.GMNotes == "town" and
      spawned[#spawned].data.CustomImage.ImageURL == "url:town|corner|ES|2", "tier 2 becomes a town on town images")
MAPTILE.weights["tier:city"] = {"3"}
drawSpecific(nil, "White")
check(spawned[#spawned].data.CustomImage.ImageURL == "url:city|corner|ES|2" and
      spawned[#spawned].data.GMNotes == "city", "tier 3 is a city on city images")
MAPTILE.weights["tier:city"] = {"1", "2", "3"}
MAPTILE.images["settlement|corner|ES|2"] = nil
MAPTILE.images["town|corner|ES|2"] = nil
local n0 = #spawned
for _ = 1, 20 do drawSpecific(nil, "White") end
check(#spawned - n0 == 20, "a tier with no image rerolls the tier instead of failing")
for i = n0 + 1, #spawned do
  if spawned[i].data.GMNotes ~= "city" then check(false, "only tier 3 can be drawn here") break end
end
MAPTILE.images["settlement|corner|ES|2"] = "url:settlement|corner|ES|2"
MAPTILE.images["town|corner|ES|2"] = "url:town|corner|ES|2"

print("== spawn guildhall ==")
before = #spawned
for _ = 1, 50 do spawnGuildhall(nil, "White") end
local allGuildhall = #spawned - before == 50
for i = before + 1, #spawned do
  if spawned[i].data.GMNotes ~= MAPTILE.guildhall then allGuildhall = false end
end
check(allGuildhall, "Spawn guildhall always gives a guildhall")
check(spawned[#spawned].data.CustomImage.ImageSecondaryURL == "back_" .. settlement.id, "guildhall gets its deck's back")
MAPTILE.weights["guildhall:pattern"] = {"cross"}
MAPTILE.weights["guildhall:density"] = {"3"}
spawnGuildhall(nil, "White")
check(spawned[#spawned].data.CustomImage.ImageURL == "url:guildhall|cross|NESW|3", "guildhall rolls from guildhall:* pools")
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
onLoad("deck=woodland;biome=forest;pattern=tee;orientation=NES;density=3;force=on;edges=SN;noedges=WE;advanced=1")
check(SETTINGS.biome == "forest" and SETTINGS.orientation == "NES" and SETTINGS.force == "on" and SETTINGS.edges == "NS" and SETTINGS.noedges == "EW",
      "settings restored from save, edges back in NESW order")
check(ADVANCED and #self.buttons == 19, "Advanced open state restored")
check(#t.buttons == 1, "onLoad re-renders tagged tiles from memo")
onLoad("deck=nope;biome=forest;pattern=tee;orientation=XX;density=3;force=maybe;edges=QZ")
check(SETTINGS.deck == "random" and SETTINGS.orientation == "random" and SETTINGS.force == "off" and SETTINGS.edges == "" and SETTINGS.noedges == "",
      "unknown saved values fall back to Random, Force off, no edges")

print(string.format("\n%d/%d checks passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
