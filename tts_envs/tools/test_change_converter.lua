-- Offline harness for the Change Converter (stubs the TTS API, tests the pure conversion logic).
-- Run from tts_envs/: tools/bin/lua54.exe tools/test_change_converter.lua src/change_converter.lua
local path = arg[1] or "src/change_converter.lua"
local pass, fail = 0, 0
local function check(cond, what)
  if cond then pass = pass + 1; print("  ok  " .. what) else fail = fail + 1; print("  FAIL " .. what) end
end

-- ---- TTS stubs
local messages = {}
function broadcastToAll(m) table.insert(messages, m) end
function broadcastToColor(m) table.insert(messages, m) end

local contents = {}
self = {buttons = {}}
function self.createButton(p) table.insert(self.buttons, p) end
function self.clearButtons() self.buttons = {} end
function self.editButton(p) for k, v in pairs(p) do if k ~= "index" then self.buttons[p.index + 1][k] = v end end end
function self.getObjects() return contents end

local function coin(value) return {guid = "c" .. value, tags = {"Gold"}, gm_notes = tostring(value)} end
local function fill(values)
  contents = {}
  for _, v in ipairs(values) do table.insert(contents, coin(v)) end
end
local function total(plan)
  local sum = 0
  for d, n in pairs(plan) do sum = sum + d * n end
  return sum
end
local function coins(plan)
  local n = 0
  for _, k in pairs(plan) do n = n + k end
  return n
end

dofile(path)

-- applyPlan is the async spawn half; capture what the click handlers ask it for.
local applied
function applyPlan(plan, value, before) applied = {plan = plan, value = value, before = before} end

print("== load ==")
onLoad()
check(#messages == 0, "every authored BREAKDOWN conserves value")
check(#self.buttons == 9, "panel has 2 actions, a total and 6 tallies")

print("== checkBreakdowns ==")
BREAKDOWN[25][1] = 4
checkBreakdowns()
check(#messages == 1 and messages[1]:find("BREAKDOWN%[25%] sums to 24"), "a breakdown that burns gold is reported")
BREAKDOWN[25][1] = 5
messages = {}

print("== fewestCoins ==")
local plan, left = fewestCoins(0)
check(next(plan) == nil and left == 0, "0 gold -> no coins")
plan, left = fewestCoins(7)
check(plan[5] == 1 and plan[1] == 2 and coins(plan) == 3 and left == 0, "7 -> Shard + 2 Nibs")
plan, left = fewestCoins(189)
check(plan[100] == 1 and plan[50] == 1 and plan[25] == 1 and plan[10] == 1 and plan[1] == 4 and left == 0,
      "189 -> 100, 50, 25, 10, 4x 1")
local exact = true
for amount = 1, 300 do
  plan, left = fewestCoins(amount)
  if total(plan) ~= amount or left ~= 0 then exact = false end
end
check(exact, "1..300 always split exactly with nothing left over")

print("== breakInto ==")
check(breakInto(1) == nil, "a Nib cannot break")
local conserved = true
for _, c in ipairs(COINS) do
  local mix = breakInto(c.value)
  if mix then
    if total(mix) ~= c.value then conserved = false end
    for d in pairs(mix) do if d >= c.value then conserved = false end end
  end
end
check(conserved, "every breakdown sums to its coin and uses only smaller coins")

print("== counting ==")
check(entryValue(coin(25)) == 25, "tagged entry reads its GMNotes value")
check(entryValue({tags = {"Gold"}, gm_notes = "abc"}) == nil, "non-numeric GMNotes is not money")
check(entryValue({tags = {"Gold"}, gm_notes = "-5"}) == nil, "negative value is not money")
check(entryValue({tags = {}, gm_notes = "5"}) == nil, "untagged entry is not money")
check(entryValue({tags = {"Gold"}, description = "10"}) == 10, "falls back to description when GMNotes is absent")
check(coinValue({hasTag = function(t) return t == "Gold" end, getGMNotes = function() return "50" end}) == 50,
      "tagged object reads its GMNotes value")
check(coinValue(nil) == nil, "nil object is not money")
fill({1, 1, 5, 25})
table.insert(contents, {guid = "x", tags = {"Item"}, gm_notes = "99"})
check(recount() == 32, "recount sums only coins")
check(COUNTS[1] == 2 and COUNTS[5] == 1 and COUNTS[25] == 1 and coinCount() == 4, "recount tallies each denomination")
check(self.buttons[3].label == "Total: 32", "total button shows the sum")
check(self.buttons[4].label == "2" and self.buttons[5].label == "1", "tally buttons show the counts")

print("== cashUpClick ==")
contents = {}
applied = nil
cashUpClick(self, "White")
check(applied == nil and messages[#messages] == "Nothing in the converter.", "empty bag does nothing")
fill({1, 1, 1, 1, 1, 1, 1})
cashUpClick(self, "White")
check(applied and applied.value == 7 and applied.before == 7 and applied.plan[5] == 1 and applied.plan[1] == 2,
      "7 Nibs cash up to Shard + 2 Nibs")
check(busy, "busy is set while converting")
applied = nil
cashUpClick(self, "White")
check(applied == nil, "a second click while busy is ignored")
busy = false

print("== breakDownClick ==")
fill({1, 1})
applied = nil
breakDownClick(self, "White")
check(applied == nil and messages[#messages] == "Nothing left to break down.", "only Nibs -> nothing to break")
fill({100, 25, 1})
breakDownClick(self, "White")
check(applied and total(applied.plan) == 126 and applied.value == 126 and applied.before == 3, "break-down conserves the total")
check(applied.plan[50] == 1 and applied.plan[25] == 1 and applied.plan[10] == 3 and applied.plan[5] == 3
      and applied.plan[1] == 6, "each coin drops one tier, Nibs stay")
check(applied.plan[100] == nil, "broken coins are not handed back")
busy = false
fill({5, 5})
breakDownClick(self, "White")
check(applied.plan[1] == 10 and coins(applied.plan) == 10, "two Shards -> 10 Nibs")
busy = false

print(string.format("\n%d/%d checks passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
