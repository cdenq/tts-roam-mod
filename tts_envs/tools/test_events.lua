-- Offline harness: stubs the TTS API and exercises Global.lua's real logic.
-- Run: lua54 tools/test_events.lua
local fails, checks = 0, 0
local function check(cond, msg)
  checks = checks + 1
  if not cond then fails = fails + 1; print("FAIL: "..msg)
  else print("  ok  "..msg) end
end

-- ---- TTS API stubs ----
local objects = {}
local broadcasts = {}
function getObjectFromGUID(g) return objects[g] end
function getAllObjects()
  local t = {}
  for _, o in pairs(objects) do table.insert(t, o) end
  table.sort(t, function(a, b) return a.getGUID() < b.getGUID() end)
  return t
end
function broadcastToAll(msg) table.insert(broadcasts, msg) end
-- Minimal JSON for the harness; TTS supplies the real one in game.
JSON = {}
function JSON.encode(t)
  local function enc(v)
    if type(v) == "table" then
      if #v > 0 then
        local out = {}
        for _, x in ipairs(v) do out[#out + 1] = enc(x) end
        return "[" .. table.concat(out, ",") .. "]"
      end
      local keys = {}
      for k in pairs(v) do keys[#keys + 1] = k end
      table.sort(keys)
      local out = {}
      for _, k in ipairs(keys) do
        out[#out + 1] = string.format("%q", k) .. ":" .. enc(v[k])
      end
      return "{" .. table.concat(out, ",") .. "}"
    elseif type(v) == "string" then
      return string.format("%q", v)
    else
      return tostring(v)
    end
  end
  return enc(t)
end

function JSON.decode(str)
  local pos = 1
  local function skip()
    while pos <= #str and str:sub(pos, pos):match("%s") do pos = pos + 1 end
  end
  local parseValue
  local function parseString()
    pos = pos + 1
    local out = {}
    while true do
      local c = str:sub(pos, pos)
      if c == "" then error("unterminated string") end
      if c == '"' then pos = pos + 1; break end
      if c == "\\" then
        pos = pos + 1
        local e = str:sub(pos, pos)
        if e == "n" then out[#out + 1] = "\n"
        elseif e == "t" then out[#out + 1] = "\t"
        else out[#out + 1] = e end
      else
        out[#out + 1] = c
      end
      pos = pos + 1
    end
    return table.concat(out)
  end
  local function parseArray()
    pos = pos + 1
    local arr = {}
    skip()
    if str:sub(pos, pos) == "]" then pos = pos + 1; return arr end
    while true do
      arr[#arr + 1] = parseValue()
      skip()
      local c = str:sub(pos, pos)
      pos = pos + 1
      if c == "]" then break end
    end
    return arr
  end
  local function parseObject()
    pos = pos + 1
    local obj = {}
    skip()
    if str:sub(pos, pos) == "}" then pos = pos + 1; return obj end
    while true do
      skip()
      local k = parseString()
      skip()
      pos = pos + 1               -- ':'
      obj[k] = parseValue()
      skip()
      local c = str:sub(pos, pos)
      pos = pos + 1
      if c == "}" then break end
    end
    return obj
  end
  parseValue = function()
    skip()
    local c = str:sub(pos, pos)
    if c == "{" then return parseObject() end
    if c == "[" then return parseArray() end
    if c == '"' then return parseString() end
    local rest = str:sub(pos)
    local lit = rest:match("^true") or rest:match("^false") or rest:match("^null")
    if lit then
      pos = pos + #lit
      if lit == "true" then return true elseif lit == "false" then return false end
      return nil
    end
    local num = rest:match("^-?%d+%.?%d*")
    pos = pos + #num
    return tonumber(num)
  end
  return parseValue()
end

Wait = {frames = function(f) f() end,
        condition = function(f, cond) if cond() then f() end end}
function printToAll(msg) table.insert(broadcasts, msg) end
GROUPED = nil
function group(objs)
  GROUPED = objs
  local d = {tag = "Deck", _cards = objs}
  d.setPosition = function() end
  d.getGUID = function() return "regrouped" end
  d.isDestroyed = function() return false end
  return {d}
end

function Vector(x, y, z) return setmetatable({x=x,y=y,z=z}, VecMT) end
VecMT = {__add = function(a,b) return Vector(a.x+b.x, a.y+b.y, a.z+b.z) end}

local function makeCard(guid, gm)
  local o = {memo = "", _gm = gm, _xml = nil, tag = "Card", type = "Card", _name = ""}
  o.getGUID = function() return guid end
  o.getGMNotes = function() return o._gm end
  o.setGMNotes = function(v) o._gm = v end
  o.setName = function(v) o._name = v end
  o.getName = function() return o._name end
  o.isDestroyed = function() return false end
  o.setPosition = function() end
  o._buttons = {}
  o.createButton = function(p) table.insert(o._buttons, p) end
  o.clearButtons = function() o._buttons = {} end
  o.clearInputs = function() end
  o.UI = {setXml = function(v) o._xml = v end, getXml = function() return o._xml end}
  objects[guid] = o
  return o
end

-- ---- load the real script, resolving require() the way the TTS bundler does ----
local src = io.open("../.tts/objects/Global.lua"):read("a")
-- this is the exact text TTS runs, data block and all
-- mirror TTSLua bundling: require("x") -> contents of generated/x.lua
-- data is inlined by the build; nothing to resolve
assert(load(src, "Global.lua"))()

math.randomseed(os.clock() * 1e6 + os.time())

local function seen2(t)
  local k = {}
  for id in pairs(t) do table.insert(k, id) end
  return k
end

local function labels(o)
  local t = {}
  for _, b in ipairs(o._buttons) do table.insert(t, tostring(b.label)) end
  return table.concat(t, " | ")
end
local function hasLabel(o, text)
  return labels(o):find(text, 1, true) ~= nil
end

-- substring matching is wrong for one-character labels like "o" and "<",
-- which occur inside ordinary option text
local function hasButton(o, text)
  for _, b in ipairs(o._buttons) do
    if tostring(b.label) == text then return true end
  end
  return false
end

--[[ Test fixture.

These tests exercise the RENDERING AND BRANCHING LOGIC, so they use their own
small data bank rather than whatever is in the CSVs right now. That keeps them
stable while the real card content is still being written. The data bank the
CSVs actually produce is validated separately, just below.
]]
local REAL_DATA = EVENT_DATA
FIXTURE_DATA = {
  F1 = {
    title = "Abandoned Toll Bridge",
    flavor = "A rickety bridge spans the gorge, and the planks look thin.",
    options = {
      {label = "Pay the toll", tooltip = "Safe", outcomes = {"F1_pay"}},
      {label = "Sneak across", tooltip = "Risky", outcomes = {"F1_sneak_ok", "F1_sneak_fail"}},
      {label = "Cut the bridge", tooltip = "Final", outcomes = {"F1_cut"}},
    },
  },
  F1_pay = {title = "Toll Paid", flavor = "You cross.",
    effect = "Gain 5 gold.", options = {},
    spawn = {items = {{"Ration", "Old Boot", "Ration"}, {"Rope"}},
             status = {{"Blessed"}}, gold = {5, 5}}},
  F1_sneak_ok = {title = "Light Feet", flavor = "You slip across.", options = {}},
  F1_sneak_fail = {title = "Snapped Plank", flavor = "A board gives way.", options = {}},
  F1_cut = {title = "Bridge Cut", flavor = "It falls.", options = {}},
  F2 = {
    title = "Woodland Fox Camp",
    flavor = "Three foxes share a fire.",
    options = {
      {label = "Share a meal", tooltip = "Talk", outcomes = {"F2_talk_ok", "F2_talk_fail"}},
    },
  },
  F2_talk_ok = {title = "Welcome Guest", flavor = "Hot food.", options = {}},
  F2_talk_fail = {title = "Cold Shoulder", flavor = "They refuse.", options = {}},
}
EVENT_DATA = FIXTURE_DATA

-- ---- tests ----
print("\n== data bank (fixture) ==")
check(EVENT_DATA.F1 ~= nil, "F1 exists in the fixture")
check(#EVENT_DATA.F1.options == 3, "F1 has 3 options")
check(#EVENT_DATA.F1_pay.options == 0, "F1_pay is terminal")

print("\n== spawn data shape ==")
local sp = EVENT_DATA.F1_pay.spawn
check(sp ~= nil, "an outcome node can carry a spawn table")
check(#sp.items == 2, "one slot per filled spawn column")
check(#sp.items[1] == 3, "a weighted slot keeps its repeats (2/3 Ration)")
check(#sp.status == 1, "status slots parse the same way")
check(sp.gold[1] == 5 and sp.gold[2] == 5, "a flat gold value becomes {n, n}")
check(EVENT_DATA.F1.spawn == nil, "entry nodes carry no spawn table")

print("\n== spawn button and plan ==")
objects = {}
local sp1 = makeCard("sp1", "F1")
renderCard(sp1)
check(not hasButton(sp1, "o"), "no spawn button on the intro screen")

setMemory(sp1, {at = "F1_pay", picks = {{node = "F1", option = 1, label = "Pay the toll", outcome = "F1_pay"}}})
renderCard(sp1)
check(hasButton(sp1, "o"), "spawn button appears on an outcome with rewards")
local ob, bb = nil, nil
for _, b in ipairs(sp1._buttons) do
  if b.label == "o" then ob = b elseif b.label == "<" then bb = b end
end
check(ob ~= nil and bb ~= nil, "both corner controls are present")
check(math.abs(ob.position[1] + bb.position[1]) < 1e-9, "o mirrors < across the centre")
check(ob.position[3] == bb.position[3], "o sits at the same height as <")
check(ob.click_function == "spawnClick", "o is wired to spawnClick")

setMemory(sp1, {at = "F1_cut", picks = {{node = "F1", option = 3, label = "Cut", outcome = "F1_cut"}}})
renderCard(sp1)
check(not hasButton(sp1, "o"), "no spawn button where the node hands out nothing")

print("\n== spawn plan rolls ==")
check(hasSpawn("F1_pay"), "hasSpawn sees rewards")
check(not hasSpawn("F1_cut"), "hasSpawn is false with no spawn table")
local plan = rollSpawnPlan("F1_pay")
check(#plan.picks == 3, "one pick per filled slot (2 items + 1 status)")
check(plan.gold == 5, "flat gold comes through")
local cats = {}
for _, pk in ipairs(plan.picks) do cats[pk.category] = (cats[pk.category] or 0) + 1 end
check(cats.items == 2 and cats.status == 1, "picks are tagged by category")
check(plan.picks[1].bag == "c98e54", "item picks carry the item bag guid")
check(plan.picks[3].bag == "72ed8a", "status picks carry the status bag guid")

local seen = {}
for i = 1, 3000 do
  local p = rollSpawnPlan("F1_pay")
  seen[p.picks[1].name] = (seen[p.picks[1].name] or 0) + 1
end
check(seen.Ration and seen["Old Boot"], "weighted slot can roll either name")
check(seen.Ration > seen["Old Boot"] * 1.5, "repeats make Ration roughly twice as likely")

EVENT_DATA.F1_sneak_ok.spawn = {gold = {1, 5}}
local glo, ghi = 99, 0
for i = 1, 500 do
  local g = rollSpawnPlan("F1_sneak_ok").gold
  if g < glo then glo = g end
  if g > ghi then ghi = g end
end
check(glo >= 1 and ghi <= 5, "ranged gold stays within bounds")
check(ghi > glo, "ranged gold actually varies")
check(describePlan({picks = {}, gold = 0}) == "nothing", "an empty plan describes as nothing")

print("\n== spawning copies from a bag ==")
-- A bag that behaves like TTS: taking an object REMOVES it until it is put back.
function makeBag(guid, names)
  local b = {tag = "Bag", _contents = {}, _takes = 0, _puts = 0}
  for i, n in ipairs(names) do
    b._contents[i] = {name = n, guid = guid .. "_" .. i}
  end
  b.getGUID = function() return guid end
  b.getPosition = function() return {x = 20, y = 1, z = 20} end
  b.isDestroyed = function() return false end
  b.getObjects = function() return b._contents end
  b.takeObject = function(p)
    b._takes = b._takes + 1
    for i, e in ipairs(b._contents) do
      if e.guid == p.guid then
        table.remove(b._contents, i)
        local o = {_name = e.name, spawning = false, _clones = 0}
        o.getName = function() return o._name end
        o.getGUID = function() return e.guid end
        o.isDestroyed = function() return false end
        o.clone = function(cp)
          o._clones = o._clones + 1
          table.insert(CLONED, {name = e.name, position = cp.position})
          return {}
        end
        return o
      end
    end
    return nil
  end
  b.putObject = function(o)
    b._puts = b._puts + 1
    table.insert(b._contents, {name = o.getName(), guid = o.getGUID()})
  end
  objects[guid] = b
  return b
end

objects = {}
CLONED = {}
local itemBag = makeBag("c98e54", {"Ration", "Rope", "Old Boot"})
local statusBag = makeBag("72ed8a", {"Blessed", "Poisoned"})

local card = makeCard("spawner", "F1")
card.getPosition = function() return {x = 1, y = 2, z = 3} end
setMemory(card, {at = "F1_pay", picks = {{node = "F1", option = 1, label = "Pay", outcome = "F1_pay"}}})

local before = #itemBag._contents
spawnClick(card)
check(#CLONED == 3, "one copy per pick (2 items + 1 status)")
check(#itemBag._contents == before, "the item bag is restocked, not drained")
check(itemBag._takes == 2 and itemBag._puts == 2, "each item is taken out and put back")
check(#statusBag._contents == 2, "the status bag is restocked too")

-- objects stack upward so they do not clip
local P = SPAWN_PLACEMENT
check(CLONED[1].position[2] == 2 + P.first[2], "first copy sits above the card")
check(CLONED[2].position[2] == CLONED[1].position[2] + P.step, "second copy is one step higher")
check(CLONED[3].position[2] == CLONED[2].position[2] + P.step, "third keeps climbing")
check(CLONED[1].position[1] == 1 and CLONED[1].position[3] == 3,
      "copies land over the card in x and z")

print("\n== a name the bag does not have ==")
objects = {}
CLONED = {}
makeBag("c98e54", {"Rope"})          -- no Ration, no Old Boot
makeBag("72ed8a", {"Blessed"})
broadcasts = {}
local card2 = makeCard("spawner2", "F1")
card2.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(card2, {at = "F1_pay", picks = {{node = "F1", option = 1, label = "Pay", outcome = "F1_pay"}}})
spawnClick(card2)
local said = table.concat(broadcasts, " | ")
check(said:find("MISSING", 1, true) ~= nil, "missing names are reported")
check(#CLONED >= 1, "the items it DOES have are still spawned")

print("\n== a bag that is not on the table ==")
objects = {}
CLONED = {}
broadcasts = {}
local card3 = makeCard("spawner3", "F1")
card3.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(card3, {at = "F1_pay", picks = {{node = "F1", option = 1, label = "Pay", outcome = "F1_pay"}}})
spawnClick(card3)
check(#CLONED == 0, "nothing spawns without the bags")
check(table.concat(broadcasts, " "):find("not found", 1, true) ~= nil,
      "a missing bag is reported rather than erroring")

print("\n== status tiles come from their own bag ==")
objects = {}
CLONED = {}
local ibag = makeBag("c98e54", {"Ration", "Rope"})
local sbag = makeBag("72ed8a", {"Blessed", "Poisoned", "Hunger"})

-- an outcome with status only, three slots, no items and no gold
EVENT_DATA.F1_sneak_fail.spawn = {status = {{"Poisoned"}, {"Hunger"}, {"Blessed"}}}
local st = makeCard("statuscard", "F1")
st.getPosition = function() return {x = 5, y = 1, z = 5} end
setMemory(st, {at = "F1_sneak_fail",
               picks = {{node = "F1", option = 2, label = "Sneak", outcome = "F1_sneak_fail"}}})

check(hasSpawn("F1_sneak_fail"), "a status-only outcome still offers the o button")
renderCard(st)
check(hasButton(st, "o"), "o renders for status-only rewards")

spawnClick(st)
check(#CLONED == 3, "all three status slots spawn")
check(sbag._takes == 3 and sbag._puts == 3, "each tile is taken from and returned to the status bag")
check(ibag._takes == 0, "the item bag is not touched for status rewards")
local names = {}
for _, c in ipairs(CLONED) do names[c.name] = true end
check(names.Poisoned and names.Hunger and names.Blessed, "every named tile was spawned")
check(CLONED[3].position[2] == CLONED[1].position[2] + 2 * SPAWN_PLACEMENT.step,
      "status tiles keep climbing so they do not clip")

print("\n== items and status share one y sequence ==")
objects = {}
CLONED = {}
makeBag("c98e54", {"Ration", "Rope"})
makeBag("72ed8a", {"Blessed"})
EVENT_DATA.F1_sneak_fail.spawn = {items = {{"Ration"}, {"Rope"}}, status = {{"Blessed"}}}
local mix = makeCard("mixcard", "F1")
mix.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(mix, {at = "F1_sneak_fail",
                picks = {{node = "F1", option = 2, label = "Sneak", outcome = "F1_sneak_fail"}}})
spawnClick(mix)
check(#CLONED == 3, "items and status both spawn together")
check(CLONED[1].name == "Ration" and CLONED[3].name == "Blessed",
      "items come first, then status, in SPAWN_SOURCES order")
local ys = {}
for _, c in ipairs(CLONED) do table.insert(ys, c.position[2]) end
check(ys[2] - ys[1] == SPAWN_PLACEMENT.step and ys[3] - ys[2] == SPAWN_PLACEMENT.step,
      "one shared y sequence across categories, no overlap")
EVENT_DATA.F1_sneak_fail.spawn = nil

print("\n== gold: fewest coins ==")
-- the split itself, independent of any bag
local counts, short = splitGold(17, {5, 1})
check(counts[5] == 3 and counts[1] == 2, "17 from {5,1} is 3 fives and 2 ones")
check(short == 0, "nothing left over")
counts, short = splitGold(17, {10, 5, 1})
check(counts[10] == 1 and counts[5] == 1 and counts[1] == 2, "17 from {10,5,1} is 10+5+1+1")
counts, short = splitGold(7, {5})
check(counts[5] == 1 and short == 2, "a shortfall is reported, not hidden")
counts, short = splitGold(0, {5, 1})
check(next(counts) == nil and short == 0, "zero gold needs no coins")

print("\n== gold: denominations come from GM Notes ==")
-- a bag whose entries carry their value in gm_notes
local function makeGoldBag(guid, coins)
  local b = {tag = "Bag", _contents = {}, _takes = 0, _puts = 0}
  for i, c in ipairs(coins) do
    b._contents[i] = {name = c.name, guid = guid .. "_" .. i, gm_notes = c.gm}
  end
  b.getGUID = function() return guid end
  b.getPosition = function() return {x = 30, y = 1, z = 30} end
  b.isDestroyed = function() return false end
  b.getObjects = function() return b._contents end
  b.takeObject = function(p)
    b._takes = b._takes + 1
    for i, e in ipairs(b._contents) do
      if e.guid == p.guid then
        local kept = e
        table.remove(b._contents, i)
        local o = {_name = e.name, spawning = false}
        o.getName = function() return o._name end
        o.getGUID = function() return e.guid end
        o.isDestroyed = function() return false end
        o.clone = function(cp)
          table.insert(CLONED, {name = e.name, position = cp.position})
          return {}
        end
        o._entry = kept
        return o
      end
    end
    return nil
  end
  b.putObject = function(o)
    b._puts = b._puts + 1
    table.insert(b._contents, o._entry)
  end
  objects[guid] = b
  return b
end

objects = {}
CLONED = {}
local gbag = makeGoldBag("f0d3ab", {{name = "Coin 1", gm = "1"}, {name = "Coin 5", gm = "5"}})
local denoms = goldDenominations(gbag)
check(#denoms == 2, "both denominations are found")
check(denoms[1] == 5 and denoms[2] == 1, "denominations sort high to low")

print("\n== gold: spawning ==")
objects = {}
CLONED = {}
makeGoldBag("f0d3ab", {{name = "Coin 1", gm = "1"}, {name = "Coin 5", gm = "5"}})
EVENT_DATA.F1_cut.spawn = {gold = {17, 17}}
local gc = makeCard("goldcard", "F1")
gc.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(gc, {at = "F1_cut", picks = {{node = "F1", option = 3, label = "Cut", outcome = "F1_cut"}}})
broadcasts = {}
spawnClick(gc)
check(#CLONED == 5, "17 gold spawns 5 coins (3 fives + 2 ones)")
local fives, ones = 0, 0
for _, c in ipairs(CLONED) do
  if c.name == "Coin 5" then fives = fives + 1 elseif c.name == "Coin 1" then ones = ones + 1 end
end
check(fives == 3 and ones == 2, "the right coins, fewest pieces")
check(CLONED[1].position[2] == SPAWN_PLACEMENT.first[2], "first coin sits at the base height")
check(CLONED[5].position[2] == SPAWN_PLACEMENT.first[2] + 4 * SPAWN_PLACEMENT.step,
      "coins climb so they do not clip")
check(table.concat(broadcasts, " "):find("17 gold", 1, true) ~= nil, "the total is reported")

print("\n== gold: continues the item y sequence ==")
objects = {}
CLONED = {}
makeBag("c98e54", {"Ration"})
makeGoldBag("f0d3ab", {{name = "Coin 5", gm = "5"}})
EVENT_DATA.F1_cut.spawn = {items = {{"Ration"}}, gold = {5, 5}}
local mixg = makeCard("mixgold", "F1")
mixg.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(mixg, {at = "F1_cut", picks = {{node = "F1", option = 3, label = "Cut", outcome = "F1_cut"}}})
spawnClick(mixg)
check(#CLONED == 2, "the item and the coin both spawn")
check(CLONED[1].name == "Ration" and CLONED[2].name == "Coin 5", "items first, then gold")
check(CLONED[2].position[2] - CLONED[1].position[2] == SPAWN_PLACEMENT.step,
      "gold continues the same y sequence, it does not restart")

print("\n== gold: missing bag is reported ==")
objects = {}
CLONED = {}
broadcasts = {}
EVENT_DATA.F1_cut.spawn = {gold = {5, 5}}
local nobag = makeCard("nogoldbag", "F1")
nobag.getPosition = function() return {x = 0, y = 0, z = 0} end
setMemory(nobag, {at = "F1_cut", picks = {{node = "F1", option = 3, label = "Cut", outcome = "F1_cut"}}})
spawnClick(nobag)
check(#CLONED == 0, "no coins without the gold bag")
check(table.concat(broadcasts, " "):find("Gold bag", 1, true) ~= nil, "the missing gold bag is named")
EVENT_DATA.F1_cut.spawn = nil





print("\n== data bank (your CSVs) ==")
check(REAL_DATA ~= nil and next(REAL_DATA) ~= nil, "the CSVs produced a data bank")
local entryCount = 0
for _, node in pairs(REAL_DATA) do
  if node.options and #node.options > 0 then entryCount = entryCount + 1 end
end
check(entryCount > 0, "there is at least one entry node ("..entryCount.." found)")
local dangling = nil
for id, node in pairs(REAL_DATA) do
  for _, opt in ipairs(node.options or {}) do
    for _, o in ipairs(opt.outcomes or {}) do
      if not REAL_DATA[o] and not dangling then dangling = id.." -> "..o end
    end
  end
end
check(dangling == nil, "no option points at a missing node"..
      (dangling and " ("..dangling..")" or ""))


print("\n== render entry node ==")
local card = makeCard("aaa111", "F1")
check(renderCard(card) == true, "renderCard returns true for a labeled card")
local x = labels(card)
check(hasLabel(card, "Abandoned Toll Bridge"), "title rendered")
check(hasLabel(card, "Pay the toll"), "option label rendered")
check(card._buttons[5].click_function == "optionClick2", "option 2 wired to optionClick2")
check(#card._buttons == 7, "id + title + desc + 3 options + X = 7 buttons on the intro")
check(not hasLabel(card, "<"), "no back button on the intro screen")
check(hasLabel(card, "X"), "X is on every screen")
check(card._buttons[4].position[3] < card._buttons[6].position[3], "options descend down the face")
check(optionZ(1) > LAYOUT.CARD_TOP + (LAYOUT.CARD_BOTTOM - LAYOUT.CARD_TOP) * 0.6,
      "options start about two thirds down the card")

print("\n== flavor and effect render as separate blocks ==")
--[[ A node's text is flavour, a blank line, then the effect in brackets. The
two blocks are wrapped SEPARATELY, because wrapLines drops newlines -- wrapping
the joined string would collapse the gap between them. ]]
objects = {}
local fx = makeCard("fx001", "F1")
setMemory(fx, {at = "F1_pay", picks = {{node = "F1", option = 1, label = "Pay", outcome = "F1_pay"}}})
renderCard(fx)
local body = nil
for _, b in ipairs(fx._buttons) do
  if b.click_function == "noop" and tostring(b.label):find("cross", 1, true) then
    body = tostring(b.label)
  end
end
check(body ~= nil, "the text block renders")
check(body:find("You cross", 1, true) ~= nil, "flavor is present")
check(body:find("[Gain 5 gold.]", 1, true) ~= nil, "effect is bracketed")
check(body:find("You cross", 1, true) < body:find("Gain 5 gold", 1, true),
      "flavor comes before the effect")
check(body:find("\n\n", 1, true) ~= nil, "a blank line separates them")

local plain = makeCard("fx002", "F1")
renderCard(plain)
local intro = nil
for _, b in ipairs(plain._buttons) do
  if b.click_function == "noop" and tostring(b.label):find("rickety", 1, true) then
    intro = tostring(b.label)
  end
end
check(intro ~= nil, "an entry node renders its flavor")
check(intro:find("[", 1, true) == nil, "a node with no effect renders no brackets")


print("\n== unlabeled object is ignored ==")
local junk = makeCard("zzz999", "")
check(renderCard(junk) == false, "card with no GMNotes is skipped")
check(#junk._buttons == 0, "no buttons on unrelated object")

print("\n== deterministic branch (single outcome) ==")
optionClick1(card)       -- "Pay the toll" -> F1_pay
check(getMemory(card).at == "F1_pay", "memory advanced to F1_pay")
check(#getMemory(card).picks == 1, "the decision was recorded in history")
check(hasLabel(card, "Toll Paid"), "outcome rendered")
check(hasLabel(card, "X"), "terminal node still shows the X control")
check(table.concat(broadcasts, " | "):find("Toll Paid", 1, true) ~= nil,
      "broadcast reports outcome")

print("\n== reset ==")
resetClick(card)
check(card.memo == "", "memory cleared")
check(hasLabel(card, "Abandoned Toll Bridge"), "back to entry node")

print("\n== random branch hits both outcomes ==")
local seen = {}
for i = 1, 400 do
  card.memo = ""
  optionClick2(card)     -- "Sneak across" -> ok|fail
  local at = getMemory(card).at
  seen[at] = (seen[at] or 0) + 1
end
check(seen.F1_sneak_ok and seen.F1_sneak_ok > 100, "F1_sneak_ok picked (n="..tostring(seen.F1_sneak_ok)..")")
check(seen.F1_sneak_fail and seen.F1_sneak_fail > 100, "F1_sneak_fail picked (n="..tostring(seen.F1_sneak_fail)..")")
local total = (seen.F1_sneak_ok or 0) + (seen.F1_sneak_fail or 0)
check(total == 400, "every click resolved to a valid outcome")
check(#seen2(seen) == 2, "exactly two distinct outcomes seen, no stray node ids")

print("\n== memo survives a world reload (onLoad re-render) ==")
objects = {}
objects["aaa111"] = card
setMemory(card, {at = "F1_cut", picks = {}})
card._buttons = {}
onLoad()
check(hasLabel(card, "Bridge Cut"), "onLoad re-rendered mid-branch state")
check(hasLabel(card, "F1"), "entry id still shown from GMNotes")

print("\n== bad input does not error ==")
chooseOption(card, 99)                -- out-of-range option index
chooseOption(makeCard("tmp", ""), 1)  -- unlabeled object
check(true, "out-of-range index and bad GUID handled without error")

print("\n== layout template ==")
check(LAYOUT ~= nil, "LAYOUT table exists for tuning")
objects = {}
local lay = makeCard("lay1", "F1")
renderCard(lay)
local allLift = true
for _, b in ipairs(lay._buttons) do
  if b.position[2] ~= LAYOUT.LIFT then allLift = false end
end
check(allLift, "every element uses LAYOUT.LIFT for its height")

-- Supersampling: font and box are multiplied by SHARPNESS and scale divides
-- by it, so the VISIBLE size must equal the plain LAYOUT numbers.
local k = LAYOUT.SHARPNESS
check(k > 1, "SHARPNESS supersamples button text")
local title = lay._buttons[2]
check(title.scale ~= nil and math.abs(title.scale[1] - 1 / k) < 1e-9,
      "title scale is 1/SHARPNESS")
check(math.abs(title.font_size * title.scale[1] - LAYOUT.TITLE_FONT) < 1e-9,
      "effective title font equals LAYOUT.TITLE_FONT")
local opt = lay._buttons[4]
local es = LAYOUT.OPTION_SCALE / k
check(math.abs(opt.scale[1] - es) < 1e-9, "option scale is OPTION_SCALE/SHARPNESS")
check(math.abs(opt.width * opt.scale[1] - LAYOUT.OPTION_WIDTH * LAYOUT.OPTION_SCALE) < 1e-9,
      "option buttons are shrunk a further OPTION_SCALE")
-- tuning values are free to change; what must hold is that the block fits
-- on the card face and the rows stay in order
check(optionZ(1) < optionZ(2), "options descend in order")
check(optionZ(#EVENT_DATA.F1.options) <= LAYOUT.CARD_BOTTOM,
      "the last option still sits on the card")


print("\n== outcome locks in for the session ==")
objects = {}
local lock = makeCard("lock1", "F1")
optionClick2(lock)                        -- random: ok or fail
local first = getMemory(lock).at
check(first == "F1_sneak_ok" or first == "F1_sneak_fail", "rolled an outcome")
local rec = recordedPick(getMemory(lock), "F1")
check(rec ~= nil and rec.outcome == first, "the roll was recorded in history")
-- going back and re-picking the same option must NOT reroll
local stable = true
for i = 1, 50 do
  backClick(lock)
  replayClick(lock)
  if getMemory(lock).at ~= first then stable = false end
end
check(stable, "replaying the same decision never rerolls")

print("\n== review screen after a decision ==")
backClick(lock)
check(hasLabel(lock, "<"), "back button appears once the card has history")
check(hasLabel(lock, "Abandoned Toll Bridge"), "review shows the entry scenario")
local taken, untaken = nil, 0
for _, b in ipairs(lock._buttons) do
  if b.click_function == "replayClick" then taken = b
  elseif b.click_function == "noop" and b.color
     and b.font_color and b.font_color[1] == LAYOUT.UNTAKEN_TEXT[1] then
    untaken = untaken + 1
  end
end
check(taken ~= nil, "the chosen option replays instead of rerolling")
check(taken.color[2] > taken.color[1], "chosen option is green")
check(taken.font_color[1] == 0 and taken.font_color[2] == 0, "chosen option text is black")
check(untaken == 2, "the other two options are inert and greyed")

print("\n== X clears the locked-in memory ==")
resetClick(lock)
check(lock.memo == "", "memory wiped")
check(#getMemory(lock).picks == 0, "history gone")
check(not hasLabel(lock, "<"), "back button hidden again on the intro")



print("\n== card index (CARD_SETS) ==")
--[[ The importer bag reads these out of Global, so they must be present and
agree with the data bank. Cards carry only an id; everything else is rendered
by Global, so a stale or wrong index is the one way importing can go bad.

These check against REAL_DATA (what the CSVs produced), not the small fixture
EVENT_DATA was swapped to above -- the index names real ids like F36.
]]
check(type(CARD_SETS) == "table", "CARD_SETS exists")
check(type(CARD_SET_ORDER) == "table", "CARD_SET_ORDER exists")
check(#CARD_SET_ORDER > 0, "at least one card set")

local inIndex = {}
local total = 0
local dupes, missing, optionless = 0, 0, 0
for _, setName in ipairs(CARD_SET_ORDER) do
  check(CARD_SETS[setName] ~= nil, "set " .. setName .. " has an id list")
  for _, id in ipairs(CARD_SETS[setName] or {}) do
    total = total + 1
    if inIndex[id] then dupes = dupes + 1 end
    inIndex[id] = true
    local node = REAL_DATA[id]
    if not node then
      missing = missing + 1
    elseif #node.options == 0 then
      optionless = optionless + 1
    end
  end
end
check(total > 0, "the index names some cards ("..total.." found)")
check(dupes == 0, "no id appears in two sets")
check(missing == 0, "every card id exists in the data bank")
check(optionless == 0, "every card id is an entry node (has options)")

-- An outcome node must never get a card: it has no options, so Global would
-- render a dead end. Conversely every entry node should be somebody's card.
local leaked = 0
for id, node in pairs(REAL_DATA) do
  if #node.options > 0 and not inIndex[id] then leaked = leaked + 1 end
end
check(leaked == 0, "every entry node in the bank is in some card set")


print("\n== importing a card stamps only identity ==")
--[[ What the importer does to each clone, and nothing more: Global renders
from GMNotes, and an empty memo means "start at the entry node". ]]
EVENT_DATA = REAL_DATA              -- render against the real bank
local firstId = CARD_SETS[CARD_SET_ORDER[1]][1]
local fresh = makeCard("imp001", firstId)
fresh.memo = ""
check(currentNode(fresh) == firstId, "a fresh card starts at its entry node")
check(renderCard(fresh), "Global renders it from GMNotes alone")
check(hasLabel(fresh, REAL_DATA[firstId].title), "the title comes from the bank")
check(#getMemory(fresh).picks == 0, "no branch history on a fresh card")
check(hasLabel(fresh, firstId), "the id is shown from GMNotes")

--[[ The object NAME is the authored title, not the id -- that is what shows in
search, hands and bag listings. The id stays authoritative in GMNotes, so the
name is cosmetic and renaming a card never changes what Global renders.
]]
local named, idFallback = 0, 0
for _, setName in ipairs(CARD_SET_ORDER) do
  for _, id in ipairs(CARD_SETS[setName]) do
    local node = REAL_DATA[id]
    local name = (node and node.title ~= "" and node.title) or id
    named = named + 1
    if name == id then idFallback = idFallback + 1 end
  end
end
check(named > 0, "every card gets a name")
check(idFallback == 0, "no card falls back to its id for a name ("..named.." titled)")
check(REAL_DATA[firstId].title ~= firstId, "a title is not just the id")
EVENT_DATA = FIXTURE_DATA



--[[ ==== economy: reputation and pricing ====

These exercise the real ECONOMY table spliced in by tools/sync_gold.py, so a
gold_variables.csv edit that breaks an invariant fails the build rather than surfacing
as a wrong price at a merchant three sessions later.
]]
print("\n== economy: reputation bands ==")

check(ECONOMY ~= nil, "ECONOMY is spliced into Global")
check(ECONOMY.rep ~= nil and #ECONOMY.rep == 5, "five reputation bands")
check(ECONOMY.prices ~= nil and next(ECONOMY.prices) ~= nil,
      "ECONOMY.prices is populated")

local ascending = true
for i = 2, #ECONOMY.rep do
  if ECONOMY.rep[i].min <= ECONOMY.rep[i - 1].min then ascending = false end
end
check(ascending, "rep band minimums ascend")

REP = {}
check(FACTIONS ~= nil and FACTIONS.riverfolk ~= nil,
      "FACTIONS is spliced into Global")
check(repScore("riverfolk") == FACTIONS.riverfolk.default_rep,
      "an untouched faction uses its default, not 0")
check(factionName("riverfolk") == FACTIONS.riverfolk.name,
      "a faction id resolves to its display name")
-- Starting reps are tuned by hand on the factions sheet, so check only that
-- each one lands in the band its own default_rep falls in, whatever it is.
local misplaced = {}
for id, f in pairs(FACTIONS) do
  local expected = ECONOMY.rep[1]
  for _, b in ipairs(ECONOMY.rep) do
    if f.default_rep >= b.min then expected = b end
  end
  if repBand(id) ~= expected then table.insert(misplaced, id) end
end
check(#misplaced == 0, "every faction starts in the band of its default_rep"
      .. (#misplaced > 0 and (" (" .. table.concat(misplaced, ", ") .. ")") or ""))

REP.test = -9999
check(repBand("test") ~= nil, "a score below every minimum still resolves")
REP.test = 9999
check(repBand("test").name == "revered", "a huge score lands in the top band")

print("\n== economy: pricing ==")

-- A band MAY pay more than it charges (sync_gold.py warns, not fails), so
-- only the bare margins are held to buy > sell here.
check(ECONOMY.sell_pct < ECONOMY.buy_pct, "sell_pct is below buy_pct")

REP = {}
check(priceFor({name = "Nonexistent Thing", faction = "eyrie", buying = true})
      == nil, "an unknown item has no price (nil, not 0)")

check(priceFor({value = 25, is_gold = true, faction = "riverfolk",
                buying = true}) == 25
      and priceFor({value = 25, is_gold = true, faction = "riverfolk",
                    buying = false}) == 25,
      "gold is face value in both directions")

REP.test = 0
check(priceFor({value = 10, faction = "test", buying = true})
      >= 10 * (1 + ECONOMY.buy_pct), "a buy price rounds up")
check(priceFor({value = 10, faction = "test", buying = false})
      <= 10 * (1 + ECONOMY.sell_pct), "a sell price rounds down")

local plain = priceFor({value = 100, faction = "test", buying = true})
local marked = priceFor({value = 100, faction = "test", buying = true,
                         adjustment_buy = 0.5})
check(marked > plain, "a shop's adjustment_buy raises the buy price")
check(priceFor({value = 100, faction = "test", buying = false,
                adjustment_buy = 0.5})
      == priceFor({value = 100, faction = "test", buying = false}),
      "adjustment_buy leaves the sell price alone")

-- Offsets ADD: the user's worked examples, with sell_pct pinned to -0.25.
local savedSell = ECONOMY.sell_pct
ECONOMY.sell_pct = -0.25
check(priceFor({value = 100, faction = "test", buying = false,
                adjustment_sell = 0.1}) == 85,
      "sell: -25% + 10% = -15%, so 100g fetches 85g")
check(priceFor({value = 100, faction = "test", buying = false,
                adjustment_sell = 0.3}) == 105,
      "sell: -25% + 30% = +5%, so 100g fetches 105g (no float drift to 104)")
check(priceFor({value = 100, faction = "test", buying = false,
                adjustment_sell = -2}) == 0,
      "a sum below -100% floors the price at 0, never negative")
ECONOMY.sell_pct = savedSell

REP.test = ECONOMY.rep[#ECONOMY.rep].min
local revBuy = priceFor({value = 100, faction = "test", buying = true})
local revSell = priceFor({value = 100, faction = "test", buying = false})
REP.test = ECONOMY.rep[1].min
local enemyBuy = priceFor({value = 100, faction = "test", buying = true})
local enemySell = priceFor({value = 100, faction = "test", buying = false})
check(revBuy < enemyBuy, "revered buys cheaper than an enemy does")
check(revSell > enemySell, "revered sells dearer than an enemy does")

REP = {}
local ore = ECONOMY.prices["Amberstone"]
check(ore ~= nil and ore > 0, "Amberstone has a price (" .. tostring(ore) .. "g)")
check(priceFor({name = "Amberstone", faction = "marquisate", buying = true})
      > priceFor({name = "Amberstone", faction = "marquisate", buying = false}),
      "buying Amberstone costs more than selling it returns")

-- The Buy / Sell buttons: a signed net label and a coloured breakdown.
local function find(text, s) return string.find(text, s, 1, true) ~= nil end
REP = {}
local summary = priceSummary({faction = "none", adjustment_buy = 0.1})
check(summary.buy_label == string.format("%+d%%",
                                         math.floor((ECONOMY.buy_pct + 0.1) * 100 + 0.5))
      and find(summary.buy_tooltip, "Net change in final asking price of items and spells you buy.")
      and find(summary.buy_tooltip, "Merchant Adjustment: [E05050]+10%[-]")
      and find(summary.buy_tooltip, "Party Adjustment: [FFFFFF]+0%[-]"),
      "buy: label is the summed offset; a surcharge is red")
check(find(priceSummary({faction = "none", adjustment_buy = -0.1}).buy_tooltip,
           "Merchant Adjustment: [50C050]-10%[-]"),
      "buy: a discount is green")
check(summary.buy_good == (ECONOMY.buy_pct + 0.1 > 0 and -1 or 1),
      "buy: a net surcharge is judged worse for the player")
local free = priceSummary({faction = "none", adjustment_buy = -ECONOMY.buy_pct})
check(free.buy_label == "+0%" and free.buy_good == 0,
      "buy: a net of zero reads +0% and is white")

local savedRep = REP
REP = {test = ECONOMY.rep[1].min}
local enemyBand = ECONOMY.rep[1]
local sellSum = priceSummary({faction = "test", adjustment_sell = 0.5})
local function tag(offset)
  if offset < 0 then return "[E05050]" end
  return offset > 0 and "[50C050]" or "[FFFFFF]"
end
check(find(sellSum.sell_tooltip, "Default Global: " .. tag(ECONOMY.sell_pct))
      and find(sellSum.sell_tooltip, "Reputation Adjustment: " ..
               tag(enemyBand.sell))
      and find(sellSum.sell_tooltip, "Party Adjustment: [FFFFFF]+0%[-]")
      and find(sellSum.sell_tooltip, "Merchant Adjustment: [50C050]+50%[-]"),
      "sell: each source is coloured red / white / green")
REP = {}
local neutral = priceSummary({faction = "none", adjustment_sell =
                              -ECONOMY.sell_pct})
check(neutral.sell_label == "+0%" and neutral.sell_good == 0,
      "sell: a net of zero reads +0% and is white")
local down = priceSummary({faction = "none"})
check(down.sell_good == (ECONOMY.sell_pct < 0 and -1 or 1)
      and string.sub(down.sell_label, 1, 1) == (ECONOMY.sell_pct < 0 and "-" or "+"),
      "sell: the label is signed and its colour follows the sign")
check(priceSummary({faction = "none", adjustment_sell = -5}).sell_label
      == "-100%", "sell: the label never shows below -100%")
REP = savedRep

REP = {}
check(priceFor({value = 100, faction = "none", buying = false,
                adjustment_sell = -0.5})
      < priceFor({value = 100, faction = "none", buying = false}),
      "a negative adjustment_sell lowers what the merchant pays you")

-- Party buffs flow into every price.
PARTY_PRICE_MODS = {}
local unbuffed = priceFor({value = 100, faction = "none", buying = true})
PARTY_PRICE_MODS = {{label = "Guild writ", buy = -0.1, sell = 0.1}}
local buffed = priceFor({value = 100, faction = "none", buying = true})
check(buffed < unbuffed, "a party buff lowers the buy price")
check(find(priceSummary({faction = "none"}).buy_tooltip,
           "Party Adjustment: [50C050]-10%[-]"),
      "a party buff shows as the Party Adjustment line")
PARTY_PRICE_MODS = {}
REP = {}

print(string.format("\n%d/%d checks passed", checks - fails, checks))
os.exit(fails == 0 and 0 or 1)
