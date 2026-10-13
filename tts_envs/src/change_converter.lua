--[[ Change Converter: make change and consolidate coins.

This is the source for the in-game bag nicknamed "Change Converter"
(GUID 305b4a). There is no generated data and no sync step -- edit this file
and push it with "TTS Editor: Update Object" on
.tts/objects/Change Converter.305b4a.lua, or Ctrl+Alt+S.

LAYOUT

  [ Break-down ]            [ Cash-up ]       row 1, flanking the bag
  [          total: 0           ]             row 2, the running sum
  [ 0 ][ 0 ][ 0 ][ 0 ][ 0 ][ 0 ]              row 3, one tally per coin

Rows 2 and 3 are both exactly PANEL.SPAN_X wide: six buttons plus five gaps
are solved against it in denomLayout(), so changing SPAN_X re-fits the whole
panel without touching anything else.

WHAT IT DOES

A coin that enters the bag is counted, not stored as a number: COUNTS is
rebuilt from the bag's real contents on every change (recount()), so the
display cannot drift from what is actually inside. A coin is anything tagged
"Gold" whose GMNotes parse as a positive number -- the same convention
goldDenominations() in global.lua already reads.

  Cash-up     consolidate into the FEWEST coins: 7 Nibs -> 1 Shard + 2 Nibs.
              Greedy largest-first, which is exact for this denomination set.
  Break-down  split each coin into the authored spread in BREAKDOWN: a
              Dragon(25) -> 10, 5, 5 and 5x 1. Nibs cannot break and are
              left alone.

Both consume everything they convert and put the result back in the bag.
]]

--[[ Panel geometry.

Object-local {x, y, z}: TTS multiplies these by the bag's own scale, and a bag
is about 1 unit across, so these numbers are sized for a bag rather than a
card. +z is toward the bag's front, so the panel hangs BELOW it on the table.

TTS rasterises button text at font_size then shrinks the drawn result by
scale, so a big font with a small scale gives sharper text than the reverse.
SHARPNESS is that multiplier; every horizontal measurement here is in VISIBLE
local units and converted at the last moment by unitsToPx(). Same trick as
PANEL in tiletoken_importer.lua and LAYOUT in global.lua.
]]
PANEL = {
  SHARPNESS = 4,
  BTN_SCALE = 0.75,

  LIFT = 0.25,              -- just above the table surface

  ACTION_Z = 0,             -- row 1: level with the bag, one either side
  ACTION_X = 3.4,
  WIDE_Z = 2.1,             -- row 2
  DENOM_Z = 3.2,            -- row 3

  --[[ How wide the panel is, in object-local units -- the same units as
  ACTION_X and as COL_X in tiletoken_importer.lua. The wide button and the six
  coins below it both span exactly this, so widening the panel is ONE edit.
  ]]
  SPAN_X = 6.8,

  --[[ Pre-shrink pixels per local unit, at BTN_SCALE.

  createButton's `width` is not in local units and the API does not give the
  conversion, so this is measured rather than derived: at 535 the coin row
  overhung the band above it by 1.21x, which puts the true figure at ~650.
  Tune SPAN_X for layout; touch this only if buttons are the wrong SIZE while
  still sitting in the right PLACES.
  ]]
  PX_PER_UNIT = 650,

  -- Heights stay in pixels; only the horizontal layout is solved in units.
  ACTION_W = 1500,
  ACTION_H = 420,
  ACTION_FONT = 170,

  WIDE_H = 420,
  WIDE_FONT = 170,

  DENOM_H = 420,
  DENOM_FONT = 150,
  DENOM_GAP = 0.1,          -- gap between denomination buttons, LOCAL units

  BREAKDOWN_COLOR = {0.62, 0.18, 0.18},
  CASHUP_COLOR = {0.18, 0.5, 0.24},
  WIDE_COLOR = {0.16, 0.16, 0.18},
  TEXT_COLOR = {1, 1, 1},
  DARK_TEXT = {0.12, 0.1, 0.06},
}

--[[ The six denominations, ascending.

`color` approximates each coin's metal so the row reads as currency at a
glance; `dark` flips the label to dark ink on the light faces.

BREAKS_INTO is derived, not authored -- see breakInto(). A coin breaks into
whole units of the next denomination down that divides it, which for this set
means Shard->Nib, Taol->Shard, Dragon->Shard, Sun->Dragon, Harbor Moon->Sun.
]]
COINS = {
  {name = "Nib", value = 1, color = {0.72, 0.42, 0.26}},
  {name = "Shard", value = 5, color = {0.74, 0.76, 0.78}, dark = true},
  {name = "Taol", value = 10, color = {0.70, 0.60, 0.26}, dark = true},
  {name = "Dragon", value = 25, color = {0.80, 0.82, 0.84}, dark = true},
  {name = "Sun", value = 50, color = {0.85, 0.68, 0.22}, dark = true},
  {name = "Harbor Moon", value = 100, color = {0.91, 0.76, 0.30}, dark = true},
}

-- Only objects carrying this tag are treated as money.
GOLD_TAG = "Gold"

-- Where coins are drawn from when the converter has to hand one back.
GOLD_BAG = "f0d3ab"

-- value -> how many of this coin are in the bag. Rebuilt by recount().
COUNTS = {}

-- Guards the convert/respawn cycle: putObject and takeObject are async, and a
-- second click mid-run would double-count.
busy = false


-- ------------------------------------------------------------------ setup ---

function onLoad()
  checkBreakdowns()
  buildPanel()
  recount()
end

--[[ Convert visible sizes into the supersampled numbers createButton wants.

Returns font, width, height and a uniform scale vector. `extra` is an
additional shrink on top of SHARPNESS -- BTN_SCALE, normally.
]]
function sharp(font, width, height, extra)
  local k = PANEL.SHARPNESS
  local s = (extra or 1) / k
  return font * k, width * k, height * k, {s, s, s}
end

-- Local units -> the pixel figure createButton wants, at BTN_SCALE.
function unitsToPx(units)
  return units * PANEL.PX_PER_UNIT
end

-- Width of one denomination button and the span it shares with the row above.
function denomLayout()
  local span = PANEL.SPAN_X
  local gaps = PANEL.DENOM_GAP * (#COINS - 1)
  return (span - gaps) / #COINS, span
end

function denomX(index)
  local w, span = denomLayout()
  return -span / 2 + w / 2 + (index - 1) * (w + PANEL.DENOM_GAP)
end

function addButton(p)
  self.createButton({
    click_function = p.fn, function_owner = self,
    label = p.label, tooltip = p.tooltip,
    position = {p.x, PANEL.LIFT, p.z},
    rotation = {0, 0, 0}, scale = p.scale,
    width = p.width, height = p.height, font_size = p.font,
    color = p.color, font_color = p.text
  })
end

function buildPanel()
  self.clearButtons()

  -- Row 1: the two actions, flanking the bag.
  local f, w, h, sc = sharp(PANEL.ACTION_FONT, PANEL.ACTION_W, PANEL.ACTION_H,
                            PANEL.BTN_SCALE)
  addButton({fn = "breakDownClick", label = "Break-down",
             tooltip = "Break every coin down one tier.",
             x = -PANEL.ACTION_X, z = PANEL.ACTION_Z,
             width = w, height = h, font = f, scale = sc,
             color = PANEL.BREAKDOWN_COLOR, text = PANEL.TEXT_COLOR})
  addButton({fn = "cashUpClick", label = "Cash-up",
             tooltip = "Consolidate into the fewest coins.",
             x = PANEL.ACTION_X, z = PANEL.ACTION_Z,
             width = w, height = h, font = f, scale = sc,
             color = PANEL.CASHUP_COLOR, text = PANEL.TEXT_COLOR})

  -- Row 2: the running total, spanning the whole panel.
  f, w, h, sc = sharp(PANEL.WIDE_FONT, unitsToPx(PANEL.SPAN_X), PANEL.WIDE_H,
                      PANEL.BTN_SCALE)
  addButton({fn = "noop", label = "", tooltip = "Total value in the bag.",
             x = 0, z = PANEL.WIDE_Z,
             width = w, height = h, font = f, scale = sc,
             color = PANEL.WIDE_COLOR, text = PANEL.TEXT_COLOR})

  -- Row 3: one tally per denomination, filling the same span.
  local each = denomLayout()
  for i, coin in ipairs(COINS) do
    f, w, h, sc = sharp(PANEL.DENOM_FONT, unitsToPx(each), PANEL.DENOM_H,
                        PANEL.BTN_SCALE)
    addButton({fn = "noop", label = "0",
               tooltip = string.format("%s (%d)", coin.name, coin.value),
               x = denomX(i), z = PANEL.DENOM_Z,
               width = w, height = h, font = f, scale = sc,
               color = coin.color,
               text = coin.dark and PANEL.DARK_TEXT or PANEL.TEXT_COLOR})
  end
end

function noop() end


-- ----------------------------------------------------------------- counting ---

--[[ The coin value an object carries, or nil when it is not money.

Tag first, GMNotes second: the tag is what makes something a coin, and the
notes carry its face value. Reads the same field goldDenominations() in
global.lua does, so a coin minted for one system works in the other.
]]
function coinValue(obj)
  if obj == nil then return nil end
  if not (obj.hasTag and obj.hasTag(GOLD_TAG)) then return nil end
  local v = tonumber(obj.getGMNotes and obj.getGMNotes() or "")
  if v == nil or v <= 0 then return nil end
  return math.floor(v)
end

-- Same test against a bag ENTRY, which is a plain table, not an Object.
function entryValue(entry)
  local tags = entry.tags or {}
  local tagged = false
  for _, t in ipairs(tags) do
    if t == GOLD_TAG then tagged = true break end
  end
  if not tagged then return nil end
  local raw = entry.gm_notes or entry.gmNotes or entry.description or ""
  local v = tonumber(raw)
  if v == nil or v <= 0 then return nil end
  return math.floor(v)
end

--[[ Rebuild COUNTS from what is actually in the bag and redraw.

Deliberately a full recount rather than an increment: an item can leave the
bag, be deleted by another script, or arrive while this one is busy, and a
running tally would drift from the truth with no way to notice.
]]
function recount()
  COUNTS = {}
  local total = 0
  for _, entry in ipairs(self.getObjects()) do
    local v = entryValue(entry)
    if v then
      COUNTS[v] = (COUNTS[v] or 0) + 1
      total = total + v
    end
  end
  refreshPanel(total)
  return total
end

-- Buttons are indexed in creation order: 0 and 1 are the actions, 2 is the
-- total, and 3..8 are the six tallies.
function refreshPanel(total)
  self.editButton({index = 2, label = string.format("Total: %d", total)})
  for i, coin in ipairs(COINS) do
    self.editButton({index = 2 + i,
                     label = tostring(COUNTS[coin.value] or 0)})
  end
end

-- How many coins are in the bag right now, across all denominations.
-- Reads COUNTS, so call recount() first if the contents may have changed.
function coinCount()
  local n = 0
  for _, coin in ipairs(COINS) do n = n + (COUNTS[coin.value] or 0) end
  return n
end


function onObjectEnterContainer(container, obj)
  if container == self then recount() end
end

function onObjectLeaveContainer(container, obj)
  if container == self then recount() end
end


-- --------------------------------------------------------------- conversion ---

-- Descending denomination values, for greedy splitting.
function denomsDescending()
  local out = {}
  for _, coin in ipairs(COINS) do table.insert(out, coin.value) end
  table.sort(out, function(a, b) return a > b end)
  return out
end

--[[ The fewest coins adding up to `amount`.

Greedy largest-first. That is only optimal for a "canonical" denomination set,
and this one (1, 5, 10, 25, 50, 100) is canonical -- the same reason it works
for real coinage. Mirrors splitGold() in global.lua.
]]
function fewestCoins(amount)
  local counts, left = {}, amount
  for _, d in ipairs(denomsDescending()) do
    local n = math.floor(left / d)
    if n > 0 then
      counts[d] = n
      left = left - n * d
    end
  end
  return counts, left
end

--[[ What one coin becomes when broken down. AUTHORED, not derived.

Each entry is a {denomination -> count} mix that must sum to the coin's own
value -- verified at load by checkBreakdowns(). A Nib has no entry and cannot
be broken.

These are hand-chosen rather than computed: a greedy split would hand back
2x Taol for a Dragon, and the intent here is a spread of denominations the
player can actually spend, not the fewest coins. Cash-up is the operation
that minimises coin count; this is its opposite.

  Harbor Moon(100) -> 50, 25, 10, 10, 5
  Sun(50)          -> 25, 10, 5, 5, 5x 1
  Dragon(25)       -> 10, 5, 5, 5x 1
  Taol(10)         -> 5, 5x 1
  Shard(5)         -> 5x 1
]]
BREAKDOWN = {
  [100] = {[50] = 1, [25] = 1, [10] = 2, [5] = 1},
  [50] = {[25] = 1, [10] = 1, [5] = 2, [1] = 5},
  [25] = {[10] = 1, [5] = 2, [1] = 5},
  [10] = {[5] = 1, [1] = 5},
  [5] = {[1] = 5},
}

function breakInto(value)
  return BREAKDOWN[value]
end

--[[ Fail loudly at load if a breakdown does not conserve value.

A table like this is edited by hand and a typo silently mints or burns gold
every time somebody clicks the button, which is exactly the kind of bug that
surfaces three sessions later as "the bank is short".
]]
function checkBreakdowns()
  for value, mix in pairs(BREAKDOWN) do
    local sum = 0
    for d, n in pairs(mix) do sum = sum + d * n end
    if sum ~= value then
      broadcastToAll(string.format(
        "Change Converter: BREAKDOWN[%d] sums to %d, not %d -- "
        .. "Break-down would alter the money supply.", value, sum, value),
        {1, 0.4, 0.4})
    end
  end
end

--[[ Where converted change is laid out, in front of the converter.

+z is the bag's front, the same side the button panel is on, so the payout
lands clear of the bag itself and of the panel's far edge. Coins march along
+x and wrap onto a new row away from the bag.
]]
PAYOUT = {
  START_X = -3.0,
  START_Z = 4.7,
  STEP_X = 0.9,
  STEP_Z = 0.9,
  PER_ROW = 8,
  DROP_HEIGHT = 1.5,
}

function payoutPosition(n)
  local col = (n - 1) % PAYOUT.PER_ROW
  local row = math.floor((n - 1) / PAYOUT.PER_ROW)
  return self.positionToWorld({
    PAYOUT.START_X + col * PAYOUT.STEP_X,
    PAYOUT.DROP_HEIGHT,
    PAYOUT.START_Z + row * PAYOUT.STEP_Z
  })
end

--[[ Convert everything in the bag and lay the change out in front of it.

`plan` maps a coin value to how many of that coin to hand back. The money
inside is destroyed first, so a plan is absolute, not a delta -- the converter
ends up empty and the player picks their change up off the table.
]]
function applyPlan(plan, value, before)
  local bag = getObjectFromGUID(GOLD_BAG)
  if bag == nil then
    broadcastToAll("Gold bag " .. GOLD_BAG .. " not found.", {1, 0.5, 0.5})
    busy = false
    return
  end

  -- Destroy the money already inside. getObjects() is a snapshot, so taking
  -- from it while iterating is safe.
  for _, entry in ipairs(self.getObjects()) do
    if entryValue(entry) then
      self.takeObject({guid = entry.guid, smooth = false,
                       callback_function = function(o) destroyObject(o) end})
    end
  end

  -- Then mint the replacements from the canonical gold bag.
  local queue = {}
  for _, coin in ipairs(COINS) do
    for _ = 1, (plan[coin.value] or 0) do
      table.insert(queue, coin.value)
    end
  end
  mintStep(bag, queue, 1, value, before, 0)
end

--[[ Clone one coin out of the gold bag per step and lay it in front.

CLONES rather than takes: GOLD_BAG is a finite stock shared with global.lua's
spawnCopyFromBag, so removing coins from it would drain the bank every time
somebody made change. The take -> wait -> clone -> put-back dance mirrors
spawnCopyFromBag exactly, including waiting for the original to finish
spawning before cloning it.

Sequential rather than a loop: takeObject is async, and firing dozens at once
against the same container drops objects on the floor.
]]
function mintStep(bag, queue, index, value, before, placed)
  if index > #queue then
    Wait.frames(function()
      recount()
      -- "Converted 37: 12 -> 4 coins" -- the value is unchanged by design, so
      -- the interesting number is how many coins it now takes to hold it.
      broadcastToAll(string.format("Converted %d: %d -> %d coin%s",
                                   value, before, placed,
                                   placed == 1 and "" or "s"),
                     {0.9, 0.85, 0.6})
      busy = false
    end, 2)
    return
  end

  local want = queue[index]
  local found = nil
  for _, entry in ipairs(bag.getObjects()) do
    if entryValue(entry) == want then found = entry.guid break end
  end
  if found == nil then
    broadcastToAll(string.format("No %d-gold coin in the gold bag.", want),
                   {1, 0.8, 0.3})
    mintStep(bag, queue, index + 1, value, before, placed)
    return
  end

  local target = payoutPosition(placed + 1)
  local original = bag.takeObject({
    guid = found, smooth = false,
    position = bag.getPosition() + Vector(0, 3, 0)
  })

  Wait.condition(
    function()
      original.clone({position = target, snap_to_grid = false})
      -- Put the original straight back so the bag keeps its stock.
      Wait.frames(function()
        bag.putObject(original)
        mintStep(bag, queue, index + 1, value, before, placed + 1)
      end, 2)
    end,
    function() return original ~= nil and not original.spawning end
  )
end


-- ------------------------------------------------------------------ actions ---

function cashUpClick(obj, playerColor, altClick)
  if busy then return end
  local total = recount()
  if total <= 0 then
    broadcastToColor("Nothing in the converter.", playerColor, {1, 0.8, 0.3})
    return
  end
  busy = true
  applyPlan(fewestCoins(total), total, coinCount())
end

function breakDownClick(obj, playerColor, altClick)
  if busy then return end
  local total = recount()
  if total <= 0 then
    broadcastToColor("Nothing in the converter.", playerColor, {1, 0.8, 0.3})
    return
  end

  -- One tier down per coin; a Nib has nowhere to go and stays as it is.
  local plan, moved = {}, false
  for _, coin in ipairs(COINS) do
    local n = COUNTS[coin.value] or 0
    if n > 0 then
      local mix = breakInto(coin.value)
      if mix then
        for d, per in pairs(mix) do
          plan[d] = (plan[d] or 0) + n * per
        end
        moved = true
      else
        plan[coin.value] = (plan[coin.value] or 0) + n
      end
    end
  end

  if not moved then
    broadcastToColor("Nothing left to break down.", playerColor, {1, 0.8, 0.3})
    return
  end
  busy = true
  applyPlan(plan, total, coinCount())
end
