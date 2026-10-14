--[[ Merchant Board: one board, every merchant.

Source for the in-game board, GUID ecde97 (nicknamed "Shop" in game). Staged
by tools/sync/sync_merchant_board.py, which also inlines SHOPS and STOCK from
data/shops.xlsx.

HOW IT WORKS

A meeple dropped in the slot zone names a shop in its GMNotes ("village_general").
Everything else -- faction, prices, what is in stock -- follows from that, so
one board serves every merchant in the game. In final development these are
plain meeples with GMNotes; nothing about the board cares what the object is.

  Restock   roll what the merchant has today and lay up to 16 wares onto
            the slots, in stock-sheet order. Needs a meeple. Deliberately spammable: it has no
            memory, so clicking twice gives you twice the stock, and reload
            needs no state because the items are ordinary world objects.
  Clear     delete every item on the board, meeple excepted. Works with or
            without a merchant present.
  Reconcile confirm-then-commit. Greys out and spawns a "Confirm?" button
            that expires after CONFIRM_SECONDS.

THE TWO ZONES

  Zone A    what you are BUYING -- items dragged off the slots
  Zone B    what you are OFFERING -- your items and your coins

A is valued at the buy price, B at the sell price, so the same sword costs
more to buy than it fetches to sell. That spread is where gold leaves the
game. Reconcile succeeds when A <= B; the difference comes back as coins.

WHY ZONES AND NOT POLLING

A scripting zone does not follow its board -- TTS has no parent/child
transform inheritance -- so the obvious alternative is to poll with
Physics.cast every frame. The API warns that 30+ casts at once will "cause
your game to stutter and/or crash", and this is one of six boards planned.
Instead the zones are repositioned from calibrated offsets whenever the
board is dropped, which costs nothing while it sits still.

PRICING LIVES IN GLOBAL

TTS sandboxes each script's tables, so this board cannot read ECONOMY. It
calls Global.call("priceObject", ...) per object instead, which keeps one
pricing authority and means a reputation change needs no re-sync here.
]]

--[[ Where everything goes, in WORLD units, measured from the real table.

CAPTURE holds the raw positions read off the hand-placed zones, verbatim.
Nothing below is in board-local units: TTS multiplies local positions by the
board's SCALE and turns them by its ROTATION, so a hand-computed local offset
is wrong the moment either is not 1 / 0 -- which is how the first version put
every zone mirrored and every button off the edge of the table.

Instead the board CALIBRATES itself: it measures each world offset against
its own transform with positionToLocal, saves the result, and from then on
places everything with positionToWorld. Those two are exact inverses, so
scale and rotation come out right without any arithmetic here.

To re-capture after moving a zone by hand: read the new world positions, paste
them into CAPTURE, and push. A changed CAPTURE forces a fresh calibration --
just do it without rotating the board in between.
]]
CAPTURE = {
  board = {-5.98, 1.48, -27.11},     -- ecde97
  zones = {
    meeple = {-15.74, 1.6, -21.04}, -- 0e2042
    a = {-11.76, 1.6, -30.95},      -- 2d3b48, buying
    b = {-0.23, 1.6, -30.95},       -- 6c541b, offering
    board = {-5.99, 1.6, -27.08},   -- 09c9c3, everything
  },
}

--[[ Buttons and slots, as WORLD offsets {dx, dz} from the
board's centre, in the same orientation as CAPTURE.

Read off the zones: the trading zones sit 5.8 either side and 3.84 toward -z,
the meeple slot 9.76 left and 6.07 toward +z. So +z is the meeple end, where
the wares go, and -z the trading end.
]]
PLACE = {
  -- Header: who / what beside the meeple slot, the faction, the prices.
  name = {-5.8, 6.8},               -- the meeple's own name
  role = {-5.8, 6.0},               -- "Town Blacksmith", under the name
  tier = {-5.8, 5.2},               -- "Town - Tier 1", under the role
  faction = {0, 6.8},               -- "Denizens" / "Marquisate"
  standing = {0, 6.0},              -- reputation with that faction, under it
  buy = {5.15, 6.8},                -- "Buy: 92%" -- net of every modifier
  sell = {5.15, 6.0},               -- "Sell: 110%"; hover either for why
  -- The 16 stock slots, laid over the two rows of 8 bottles in the art.
  slot_first = {-8.51, 3.72},       -- top-left bottle
  zone_a_label = {0, -2.1},       -- "Buying", at the head of the -> arrow
  zone_b_label = {0, -5.6},      -- "Offering", at the head of the <- arrow
  reconcile = {0, -3.75},            -- between the two arrows
  confirm = {0, -6.9},              -- under the <- arrow
  clear = {9.2, 6.3},               -- top right, by the banner star
  restock = {9.2, 5.4},             -- under Clear
}

SLOT_COLS = 8
SLOT_ROWS = 2
SLOT_COUNT = SLOT_COLS * SLOT_ROWS
SLOT_STEP_X = 2.43    -- world units between bottles along a row
SLOT_STEP_Z = -2.43   -- world units from the top row to the bottom row
BUTTON_LIFT = 0.05    -- world units above the board's top face
DROP_HEIGHT = 1.0     -- world units above the top face for change
CHANGE_INSET = 0.6    -- world units in from the offering zone's corner
SLOT_LIFT = 0.5       -- world units above the board's ORIGIN for a ware
STACK_STEP = 0.5      -- extra height per copy on the same slot

--[[ Button styling. Widths and heights are in createButton's own units, which
the API does not tie to world units; the board's scale is divided out in
sharp(), so these read the same whatever size the board is. ]]
LAYOUT = {
  SHARPNESS = 4,
  BTN_SCALE = 0.75,
  HEADER_SCALE = 1.5,   -- the header, on top of BTN_SCALE: box and font alike

  HEADER_W = 2400,
  HEADER_H = 340,       -- shorter than BTN_H, so the stacked pairs fit
  HEADER_FONT = 140,
  DISCOUNT_W = 1900,
  --[[ The Buying / Offering totals are READOUTS, not controls, drawn as
  floating text. A button with width and height 0 is invisible but keeps its
  label (API, createButton) -- which also leaves nothing to hover or click.
  Making the face transparent does NOT work: it hides the label too. ]]
  ZONE_FONT = 260,
  ZONE_TEXT = {0, 0, 0},
  RECONCILE_W = 1700,
  SMALL_W = 1100,
  BTN_H = 420,
  BTN_FONT = 165,

  HEADER_BG = {0, 0, 0, 0.75},
  BUY_BG = {0.55, 0.22, 0.18},
  SELL_BG = {0.18, 0.42, 0.26},
  RECONCILE_BG = {0.22, 0.34, 0.5},
  GOOD_TEXT = {0.45, 0.9, 0.45},  -- a price moved in the player's favour
  BAD_TEXT = {1, 0.45, 0.4},      -- ...or against them
  CONFIRM_BG = {0.75, 0.55, 0.12},
  GREY_BG = {0.3, 0.3, 0.32},
  TEXT = {1, 1, 1},
  DIM_TEXT = {0.6, 0.6, 0.62},
}

-- Scripting zones, by role.
ZONE_GUIDS = {
  a = "2d3b48",       -- buying
  b = "6c541b",       -- offering
  meeple = "0e2042",  -- merchant slot
  board = "09c9c3",   -- everything, for Clear
}

--[[ Every zone is this much taller than it was placed by hand, bottom face
kept where it was, so wares stacked on a slot are still inside.

The hand-placed height is read once and saved (zoneHeights), so reloads and
board drags do not grow the zones again. Resized a zone by hand? Clear its
entry from the saved state, or it keeps the old base. ]]
ZONE_EXTRA_HEIGHT = 1.5
zoneHeights = {}

GOLD_TAG = "Gold"

--[[ The board only ever touches an object carrying EVERY tag of one of these
sets: Clear deletes nothing else, and the trading zones count nothing else.
The zones overlap the table, which is built from objects, and anything else
dropped there (a die, a stray token) is simply not part of the trade. ]]
TRACKED_TAGS = {
  {"Item", "Tile"},
  {"Gold", "Object"},
}

-- Where cloned stock and change come from.
ITEM_BAG = "c98e54"
GOLD_BAG = "f0d3ab"

CONFIRM_SECONDS = 3

-- Board-local offsets produced by calibrate(), keyed by name. Persisted.
OFFSETS = {}

-- Live state. Not persisted: the items on the board ARE the state, and they
-- survive a reload on their own.
confirmTimer = nil
busy = false
stocking = nil -- the Restock run in flight: queue, index, placed, shop


-- ------------------------------------------------------------ calibration ---

-- A fingerprint of CAPTURE, so editing it forces a fresh calibration.
function captureSignature()
  local parts = {}
  local function add(v) table.insert(parts, string.format("%.3f", v)) end
  for _, v in ipairs(CAPTURE.board) do add(v) end
  for _, role in ipairs({"meeple", "a", "b", "board"}) do
    for _, v in ipairs(CAPTURE.zones[role]) do add(v) end
  end
  return table.concat(parts, ",")
end

-- Height of the board's upper face above its origin, in world units.
function boardTop()
  local bounds = self.getBounds()
  return bounds.center.y + bounds.size.y / 2 - self.getPosition().y
end

--[[ The board's FRAME: where one world unit along each CAPTURE axis lands in
board-local coordinates. Rotation and scale are both inside it, so any world
offset becomes a local one by plain arithmetic:

  local = dx * BASIS.x + dy * BASIS.y + dz * BASIS.z

Only the frame is saved, never the positions built from it -- so editing
PLACE moves a button on the next load with no recalibration, and turning the
board afterwards changes nothing.
]]
BASIS = nil

function captureDelta(role)
  local w, b = CAPTURE.zones[role], CAPTURE.board
  return {w[1] - b[1], w[2] - b[2], w[3] - b[3]}
end

--[[ Measure the frame against the board's CURRENT transform.

Valid only while the board sits at the rotation it had when CAPTURE was
read. Position does not matter -- every offset is relative to the centre.
]]
function calibrate()
  local origin = self.getPosition()
  local function axis(dx, dy, dz)
    local p = self.positionToLocal(origin + Vector(dx, dy, dz))
    return {p.x, p.y, p.z}
  end
  BASIS = {x = axis(1, 0, 0), y = axis(0, 1, 0), z = axis(0, 0, 1),
           signature = captureSignature()}
end

--[[ Recover the frame from an older save that stored finished positions.

That save holds three zone offsets in local units, and CAPTURE says where
each one was in world units. Three known pairs pin down a 3x3 frame exactly:
  L = M * D   so   M = L * inverse(D)
This keeps an already-calibrated board calibrated, whatever it has been
turned to since.
]]
function basisFromOffsets(offsets)
  local roles = {"a", "b", "meeple"}
  local D, L = {}, {}
  for c, role in ipairs(roles) do
    local d, l = captureDelta(role), offsets["zone_" .. role]
    if l == nil then return nil end
    for r = 1, 3 do
      D[r] = D[r] or {}
      L[r] = L[r] or {}
      D[r][c], L[r][c] = d[r], l[r]
    end
  end
  local inv = invert3(D)
  if inv == nil then return nil end
  local M = {}
  for r = 1, 3 do
    M[r] = {}
    for c = 1, 3 do
      M[r][c] = L[r][1] * inv[1][c] + L[r][2] * inv[2][c] + L[r][3] * inv[3][c]
    end
  end
  return {x = {M[1][1], M[2][1], M[3][1]}, y = {M[1][2], M[2][2], M[3][2]},
          z = {M[1][3], M[2][3], M[3][3]}, signature = offsets.signature}
end

function invert3(m)
  local a, b, c = m[1][1], m[1][2], m[1][3]
  local d, e, f = m[2][1], m[2][2], m[2][3]
  local g, h, i = m[3][1], m[3][2], m[3][3]
  local det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
  if math.abs(det) < 1e-9 then return nil end
  return {
    {(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det},
    {(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det},
    {(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det},
  }
end

function toLocal(dx, dy, dz)
  local bx, by, bz = BASIS.x, BASIS.y, BASIS.z
  return {dx * bx[1] + dy * by[1] + dz * bz[1],
          dx * bx[2] + dy * by[2] + dz * bz[2],
          dx * bx[3] + dy * by[3] + dz * bz[3]}
end

--[[ Build every local offset from the frame. Cheap; runs on each load.

BUTTONS ARE MIRRORED IN X. createButton reads its x axis the opposite way to
positionToLocal/positionToWorld -- seen in game, where every button came out
flipped left-to-right while the zones, placed through positionToWorld from
the same numbers, were correct. Not documented on the API site; observed.
So button offsets negate x, and zones and slots do not.
]]
BUTTONS = {name = true, role = true, tier = true, faction = true, standing = true,
           buy = true, sell = true, zone_a_label = true, zone_b_label = true,
           reconcile = true, confirm = true, clear = true, restock = true}

function buildOffsets()
  local top = boardTop()
  OFFSETS = {}
  for _, role in ipairs({"meeple", "a", "b", "board"}) do
    local d = captureDelta(role)
    OFFSETS["zone_" .. role] = toLocal(d[1], d[2], d[3])
  end
  for name, xz in pairs(PLACE) do
    if BUTTONS[name] then
      local p = toLocal(xz[1], top + BUTTON_LIFT, xz[2])
      OFFSETS[name] = {-p[1], p[2], p[3]}
    end
  end
  for n = 1, SLOT_COUNT do
    local col = (n - 1) % SLOT_COLS
    local row = math.floor((n - 1) / SLOT_COLS)
    OFFSETS["slot_" .. n] = toLocal(PLACE.slot_first[1] + col * SLOT_STEP_X,
                                    SLOT_LIFT,
                                    PLACE.slot_first[2] + row * SLOT_STEP_Z)
  end
end

function onSave()
  return JSON.encode({basis = BASIS, zone_heights = zoneHeights})
end


-- ------------------------------------------------------------------ setup ---

function onLoad(script_state)
  local data = nil
  if script_state and script_state ~= "" then
    local ok, decoded = pcall(function() return JSON.decode(script_state) end)
    if ok and type(decoded) == "table" then data = decoded end
  end

  local sig = captureSignature()
  if data and data.basis and data.basis.signature == sig then
    BASIS = data.basis
  elseif data and data.offsets and data.offsets.signature == sig then
    BASIS = basisFromOffsets(data.offsets)
  end
  if BASIS == nil then calibrate() end
  if data and type(data.zone_heights) == "table" then
    zoneHeights = data.zone_heights
  end

  buildOffsets()
  findZones()
  repositionZones()
  buildPanel()
  refresh()
end

--[[ A board that has been dragged leaves its zones behind, so move them.

onObjectDrop fires the moment the board is RELEASED, while it is still in the
air -- placing the zones then leaves them floating at the drop height. Waiting
lets the board fall and settle first. A second drop inside the wait restarts
it, so only the final resting position counts. The zones turn with the board
so their edges stay parallel to it.
]]
SETTLE_SECONDS = 1.25
settleTimer = nil

function onObjectDrop(playerColor, obj)
  if obj ~= self then return end
  if settleTimer then Wait.stop(settleTimer) end
  settleTimer = Wait.time(function()
    settleTimer = nil
    if not self.isDestroyed() then repositionZones() end
  end, SETTLE_SECONDS)
end

function repositionZones()
  for _, role in ipairs({"meeple", "a", "b", "board"}) do
    local zone = zoneFor(role)
    local offset = OFFSETS["zone_" .. role]
    if zone and offset then
      -- A zone's scale IS its size, and its position its centre: grow it by
      -- the extra and lift by half, so only the top face moves.
      local scale = zone.getScale()
      if zoneHeights[role] == nil then zoneHeights[role] = scale.y end
      zone.setScale(Vector(scale.x, zoneHeights[role] + ZONE_EXTRA_HEIGHT,
                           scale.z))
      zone.setPosition(self.positionToWorld(offset)
                       + Vector(0, ZONE_EXTRA_HEIGHT / 2, 0))
      zone.setRotation(self.getRotation())
    end
  end
end

function zoneFor(role)
  local guid = ZONE_GUIDS[role]
  if guid == nil or guid == "" then return nil end
  return getObjectFromGUID(guid)
end

--[[ Report any zone that has not been wired up.

The zones are placed by hand in TTS and their GUIDs pasted into ZONE_GUIDS,
so a blank one is a setup step somebody forgot rather than a code fault. Say
which, once, rather than failing silently later.
]]
function findZones()
  local missing = {}
  for _, role in ipairs({"a", "b", "meeple", "board"}) do
    if zoneFor(role) == nil then table.insert(missing, role) end
  end
  if #missing > 0 then
    printToAll("Merchant board: no zone set for " ..
               table.concat(missing, ", ") ..
               " -- place a scripting zone and put its GUID in ZONE_GUIDS.",
               {1, 0.8, 0.3})
  end
end


-- ------------------------------------------------------------------- shop ---

--[[ The merchant currently in the slot, or nil.

Reads GMNotes off whatever is in the meeple zone. In final development these
are plain meeples; the board does not care what the object is, only what its
notes say.
]]
function merchantInSlot()
  local zone = zoneFor("meeple")
  if zone == nil then return nil end
  for _, obj in ipairs(zone.getObjects()) do
    local id = obj.getGMNotes and obj.getGMNotes() or ""
    id = trim(id)
    if id ~= "" and SHOPS[id] then return SHOPS[id], id, obj end
  end
  return nil
end

function trim(s)
  return (string.gsub(s or "", "^%s*(.-)%s*$", "%1"))
end


-- ------------------------------------------------------------------ value ---

-- Whether an object carries every tag of one TRACKED_TAGS set.
function tracked(obj)
  for _, tags in ipairs(TRACKED_TAGS) do
    local all = true
    for _, tag in ipairs(tags) do
      if not obj.hasTag(tag) then
        all = false
        break
      end
    end
    if all then return true end
  end
  return false
end

--[[ What everything in a zone is worth, at buy or sell prices.

Only tracked objects count; anything else in the zone is ignored.

Returns the total and a list of the objects counted, plus a list of anything
it could NOT price. An unpriceable object is never silently worth 0 -- that
is how a player loses a sword to a typo'd name -- so the caller reports it
and refuses to trade.
]]
function zoneValue(role, buying, shop)
  local zone = zoneFor(role)
  local total, counted, unpriced = 0, {}, {}
  if zone == nil then return total, counted, unpriced end

  for _, obj in ipairs(zone.getObjects()) do
    if obj ~= self and not obj.isDestroyed() and tracked(obj) then
      local price = Global.call("priceObject", {
        object = obj, faction = shop and shop.faction or "none",
        buying = buying,
        adjustment_buy = shop and shop.adjustment_buy or 0,
        adjustment_sell = shop and shop.adjustment_sell or 0
      })
      if price == nil then
        local name = obj.getName() or ""
        table.insert(unpriced, name ~= "" and name or obj.getGUID())
      else
        total = total + price
        table.insert(counted, {object = obj, price = price})
      end
    end
  end
  return total, counted, unpriced
end


-- ----------------------------------------------------------------- buttons ---

--[[ Convert visible sizes into the supersampled numbers createButton wants.

A button inherits the board's scale, so a board scaled 3x draws every button
3x larger. Dividing it back out keeps the sizes in LAYOUT meaning the same
thing on any board.
]]
function sharp(font, width, height, extra)
  local k = LAYOUT.SHARPNESS
  local s = (extra or 1) / k / self.getScale().x
  return font * k, width * k, height * k, {s, s, s}
end

function addButton(p)
  self.createButton({
    click_function = p.fn, function_owner = self,
    label = p.label, tooltip = p.tooltip or "",
    position = OFFSETS[p.at], rotation = {0, 0, 0}, scale = p.scale,
    width = p.width, height = p.height, font_size = p.font,
    color = p.color, font_color = p.text or LAYOUT.TEXT
  })
end

--[[ Button indices, by creation order. editButton takes an index, so these
have to stay in step with buildPanel. ]]
BTN = {NAME = 0, ROLE = 1, TIER = 2, FACTION = 3, STANDING = 4, BUY = 5,
       SELL = 6, ZONE_A = 7, ZONE_B = 8, RECONCILE = 9}

function buildPanel()
  self.clearButtons()
  local f, w, h, sc

  --[[ The header is six label-only buttons, each saying one thing. They
  are created in BTN order -- editButton finds them by index. ]]
  local headerScale = LAYOUT.BTN_SCALE * LAYOUT.HEADER_SCALE
  f, w, h, sc = sharp(LAYOUT.HEADER_FONT, LAYOUT.HEADER_W, LAYOUT.HEADER_H,
                      headerScale)
  for _, at in ipairs({"name", "role", "tier", "faction", "standing"}) do
    addButton({fn = "noop", label = "", at = at,
               width = w, height = h, font = f, scale = sc,
               color = LAYOUT.HEADER_BG})
  end
  f, w, h, sc = sharp(LAYOUT.HEADER_FONT, LAYOUT.DISCOUNT_W, LAYOUT.HEADER_H,
                      headerScale)
  for _, at in ipairs({"buy", "sell"}) do
    addButton({fn = "noop", label = "", at = at,
               width = w, height = h, font = f, scale = sc,
               color = LAYOUT.HEADER_BG})
  end

  f, w, h, sc = sharp(LAYOUT.ZONE_FONT, 0, 0, LAYOUT.BTN_SCALE)
  addButton({fn = "noop", label = "Buying: 0g", at = "zone_a_label",
             width = w, height = h, font = f, scale = sc,
             text = LAYOUT.ZONE_TEXT})
  addButton({fn = "noop", label = "Offering: 0g", at = "zone_b_label",
             width = w, height = h, font = f, scale = sc,
             text = LAYOUT.ZONE_TEXT})

  f, w, h, sc = sharp(LAYOUT.BTN_FONT, LAYOUT.RECONCILE_W, LAYOUT.BTN_H,
                      LAYOUT.BTN_SCALE)
  addButton({fn = "reconcileClick", label = "Reconcile", at = "reconcile",
             width = w, height = h, font = f, scale = sc,
             color = LAYOUT.RECONCILE_BG, tooltip = "Settle the trade."})

  f, w, h, sc = sharp(LAYOUT.BTN_FONT, LAYOUT.SMALL_W, LAYOUT.BTN_H,
                      LAYOUT.BTN_SCALE)
  addButton({fn = "restockClick", label = "Restock", at = "restock",
             width = w, height = h, font = f, scale = sc,
             color = LAYOUT.SELL_BG,
             tooltip = "Spawn this merchant's wares onto the slots."})
  addButton({fn = "clearClick", label = "Clear", at = "clear",
             width = w, height = h, font = f, scale = sc,
             color = LAYOUT.BUY_BG,
             tooltip = "Remove every item from the board."})
end

function noop() end

--[[ Redraw the header and the two totals from the live state of the board. ]]
TIER_NAMES = {[0] = "Settlement", [1] = "Town", [2] = "City", [3] = "Capital"}

function refresh()
  local shop, _, meeple = merchantInSlot()
  local function set(index, label, tooltip)
    self.editButton({index = index, label = label, tooltip = tooltip or ""})
  end
  if shop then
    local name = trim(meeple.getName())
    set(BTN.NAME, name ~= "" and name or "Unnamed merchant")
    set(BTN.ROLE, shop.role)
    set(BTN.TIER, string.format("%s - Tier %d",
                                TIER_NAMES[shop.tier] or "?", shop.tier))
    set(BTN.FACTION, Global.call("factionName", shop.faction))
    local band = Global.call("repBand", shop.faction)
    set(BTN.STANDING, band and capitalize(band.name) or "?",
        string.format("Reputation %d", Global.call("repScore", shop.faction)))
    local summary = Global.call("priceSummary", {
      faction = shop.faction,
      adjustment_buy = shop.adjustment_buy,
      adjustment_sell = shop.adjustment_sell
    })
    setPrice(BTN.BUY, "Buy", "buy", summary)
    setPrice(BTN.SELL, "Sell", "sell", summary)
  else
    set(BTN.NAME, "No merchant", "Place a merchant in the slot.")
    set(BTN.ROLE, "")
    set(BTN.TIER, "")
    set(BTN.FACTION, "")
    set(BTN.STANDING, "")
    set(BTN.BUY, "")
    set(BTN.SELL, "")
  end

  local a = zoneValue("a", true, shop)
  local b = zoneValue("b", false, shop)
  self.editButton({index = BTN.ZONE_A, label = string.format("Buying: %dg", a)})
  self.editButton({index = BTN.ZONE_B,
                   label = string.format("Offering: %dg", b)})
end

--[[ "Buy: +15%" / "Sell: -22%": the net change on an item's base price.
Coloured by what it means for the player -- green better, white neutral, red
worse -- which Global has already judged per side. ]]
GOOD_COLORS = {[-1] = "BAD_TEXT", [0] = "TEXT", [1] = "GOOD_TEXT"}

function setPrice(index, title, side, summary)
  self.editButton({index = index, label = title .. ": " .. summary[side .. "_label"],
                   font_color = LAYOUT[GOOD_COLORS[summary[side .. "_good"]]],
                   tooltip = summary[side .. "_tooltip"]})
end

function capitalize(s)
  return (string.gsub(s, "^%l", string.upper))
end

-- Any traffic through a zone changes a total, so redraw. A frame of delay
-- lets the object settle before it is read.
function onObjectEnterZone(zone, obj)
  Wait.frames(refresh, 1)
end

function onObjectLeaveZone(zone, obj)
  Wait.frames(refresh, 1)
end


-- ------------------------------------------------------------ restock/clear ---

--[[ World position of a ware: its slot, lifted STACK_STEP per copy below it. ]]
function slotPosition(slot, layer)
  return self.positionToWorld(OFFSETS["slot_" .. slot])
         + Vector(0, (layer or 0) * STACK_STEP, 0)
end

--[[ Lay out what this merchant has today.

Every stock row is something the merchant MAY carry. Its items list is the
spawn-cell grammar ("Pickaxe|Woodaxe| "): one entry is picked, a blank one
means nothing, and a "!" marks a unique take. Its qty is rolled between lo
and hi, and a 0 means it is out today. Survivors fill the slots in sheet
order, so the first SLOT_COUNT rows that come up win and the rest are not
shown. Copies of one item stack on its slot.

Restock is deliberately spammable: it reads nothing back from the board, so
clicking twice lays out a second round on top of the first.
]]
function restockClick(obj, playerColor)
  if busy then return end
  local shop, id = merchantInSlot()
  if shop == nil then
    broadcastToColor("No merchant in the slot.", playerColor, {1, 0.8, 0.3})
    return
  end

  local wares = {}
  for _, row in ipairs(STOCK[id] or {}) do
    if #wares >= SLOT_COUNT then break end
    local pick = trim(row.items[math.random(#row.items)])
    local n = math.random(row.lo, row.hi)
    if pick ~= "" and n > 0 then
      local unique = string.sub(pick, 1, 1) == "!"
      if unique then pick = trim(string.sub(pick, 2)) end
      table.insert(wares, {item = pick, qty = n, unique = unique})
    end
  end
  if #wares == 0 then
    broadcastToColor(shop.role .. " has nothing to sell today.", playerColor,
                     {1, 0.8, 0.3})
    return
  end

  local queue = {}
  for slot, ware in ipairs(wares) do
    for layer = 0, ware.qty - 1 do
      table.insert(queue, {item = ware.item, unique = ware.unique,
                           slot = slot, layer = layer})
    end
  end
  busy = true
  stocking = {queue = queue, index = 1, placed = 0, shop = shop}
  stockStep()
end

--[[ Clone one ware per step onto its slot.

Sequential because takeObject is async: firing a dozen at once against the
same bag drops objects on the floor. Clones rather than takes, so the
canonical item bag is never depleted -- the same contract spawnCopyFromBag
keeps in global.lua.
]]
function stockStep()
  local run = stocking
  if run.index > #run.queue then
    stocking = nil
    busy = false
    broadcastToAll(string.format("%s lays out %d ware%s.", run.shop.role,
                                 run.placed, run.placed == 1 and "" or "s"),
                   {0.9, 0.85, 0.6})
    Wait.frames(refresh, 2)
    return
  end

  local ware = run.queue[run.index]
  Global.call("spawnCopyFromBagFor", {
    bag = ITEM_BAG, name = ware.item, unique = ware.unique,
    position = slotPosition(ware.slot, ware.layer),
    reply_to = self.getGUID(), reply = "stockPlaced",
  })
end

-- Global's answer to one spawn, by name: a closure cannot cross Global.call.
function stockPlaced(params)
  if stocking == nil then return end
  if params.value then stocking.placed = stocking.placed + 1 end
  stocking.index = stocking.index + 1
  stockStep()
end

--[[ Every clearable item on the board, meeple and held objects excepted.

A player mid-drag owns that object; deleting it out from under them is rude
and leaves TTS holding a destroyed reference.
]]
function boardItems()
  local zone = zoneFor("board")
  local out = {}
  if zone == nil then return out end
  local _, _, meepleObj = merchantInSlot()
  for _, obj in ipairs(zone.getObjects()) do
    if obj ~= self and obj ~= meepleObj and not obj.isDestroyed()
       and obj.held_by_color == nil and tracked(obj) then
      table.insert(out, obj)
    end
  end
  return out
end

function clearClick(obj, playerColor)
  if busy then return end
  local items = boardItems()
  if #items == 0 then
    broadcastToColor("Nothing on the board.", playerColor, {1, 0.8, 0.3})
    return
  end
  for _, o in ipairs(items) do destroyObject(o) end
  broadcastToAll(string.format("Cleared %d item%s from the merchant board.",
                               #items, #items == 1 and "" or "s"),
                 {0.9, 0.85, 0.6})
  Wait.frames(refresh, 2)
end


-- -------------------------------------------------------------- reconcile ---

--[[ Two-step commit.

The first click greys Reconcile and raises a Confirm button that expires on
its own. Three seconds is also long enough for somebody to drag an item out
of a zone, so confirmClick re-reads both totals rather than trusting the
numbers that were on screen when Reconcile was pressed.
]]
function reconcileClick(obj, playerColor)
  if busy then return end
  local shop = merchantInSlot()
  if shop == nil then
    broadcastToColor("No merchant in the slot.", playerColor, {1, 0.8, 0.3})
    return
  end

  local a, aItems, aBad = zoneValue("a", true, shop)
  local b, bItems, bBad = zoneValue("b", false, shop)
  -- Nothing tracked in either zone: not a trade, so not worth a message.
  if #aItems + #aBad + #bItems + #bBad == 0 then return end
  if #aBad > 0 or #bBad > 0 then
    broadcastToColor("Cannot price: " ..
                     table.concat(concatLists(aBad, bBad), ", "),
                     playerColor, {1, 0.5, 0.5})
    return
  end
  if a > b then
    printToAll(string.format("You cannot afford this purchase; missing %dg "
                             .. "in gold value.", a - b), {1, 0.5, 0.5})
    return
  end

  self.editButton({index = BTN.RECONCILE, click_function = "noop",
                   color = LAYOUT.GREY_BG, font_color = LAYOUT.DIM_TEXT})
  local f, w, h, sc = sharp(LAYOUT.BTN_FONT, LAYOUT.SMALL_W, LAYOUT.BTN_H,
                            LAYOUT.BTN_SCALE)
  addButton({fn = "confirmClick",
             label = string.format("Confirm?\n%dg change", b - a),
             at = "confirm",
             width = w, height = h, font = f, scale = sc,
             color = LAYOUT.CONFIRM_BG, text = {0.1, 0.08, 0.02},
             tooltip = "Commit the trade."})
  confirmTimer = Wait.time(cancelConfirm, CONFIRM_SECONDS)
end

function cancelConfirm()
  confirmTimer = nil
  -- The Confirm button is always the last one added.
  local buttons = self.getButtons() or {}
  if #buttons > 0 and buttons[#buttons].label
     and string.find(buttons[#buttons].label, "Confirm") then
    self.removeButton(buttons[#buttons].index)
  end
  self.editButton({index = BTN.RECONCILE, click_function = "reconcileClick",
                   color = LAYOUT.RECONCILE_BG, font_color = LAYOUT.TEXT})
end

function confirmClick(obj, playerColor)
  if busy then return end
  if confirmTimer then
    Wait.stop(confirmTimer)
    confirmTimer = nil
  end

  local shop = merchantInSlot()
  if shop == nil then
    broadcastToColor("The merchant has left.", playerColor, {1, 0.5, 0.5})
    cancelConfirm()
    return
  end

  -- Re-read: three seconds is long enough for the board to have changed.
  local a, aItems, aBad = zoneValue("a", true, shop)
  local b, bItems, bBad = zoneValue("b", false, shop)
  if #aBad > 0 or #bBad > 0 or a > b then
    broadcastToColor("The trade changed -- start again.", playerColor,
                     {1, 0.5, 0.5})
    cancelConfirm()
    return
  end

  busy = true
  local sold = {}
  for _, entry in ipairs(bItems) do
    table.insert(sold, entry.object.getName() or "?")
    destroyObject(entry.object)
  end
  local bought = {}
  for _, entry in ipairs(aItems) do
    table.insert(bought, entry.object.getName() or "?")
  end

  local change = b - a
  broadcastToAll(string.format(
    "%s: bought %s for %dg; sold %s for %dg; change %dg.",
    shop.role,
    #bought > 0 and table.concat(bought, ", ") or "nothing", a,
    #sold > 0 and table.concat(sold, ", ") or "nothing", b, change),
    {0.9, 0.85, 0.6})

  cancelConfirm()
  if change > 0 then
    payChange(change)
  else
    busy = false
    Wait.frames(refresh, 2)
  end
end

--[[ Spawn the change owed, in as few coins as the gold bag can manage.

It lands in the offering zone's top-left corner, so it is counted as the
player's offer until they pick it up -- Reconciling again just makes change
for it. ]]
function payChange(amount)
  Global.call("spawnGoldAt", {
    amount = amount,
    position = changeSpot(),
    reply_to = self.getGUID(), reply = "changePaid",
  })
end

--[[ The offering zone's top-left corner, inset by CHANGE_INSET, in world
units. Worked in CAPTURE's orientation (-x left, +z top) and turned through
the board's frame like everything else, so it follows the board. ]]
function changeSpot()
  local zone = zoneFor("b")
  local d = captureDelta("b")
  -- A zone's scale IS its size.
  local size = zone and zone.getScale() or Vector(0, 0, 0)
  local p = toLocal(d[1] - size.x / 2 + CHANGE_INSET, boardTop() + DROP_HEIGHT,
                    d[3] + size.z / 2 - CHANGE_INSET)
  return self.positionToWorld(p)
end

function changePaid()
  busy = false
  Wait.frames(refresh, 2)
end

function concatLists(a, b)
  local out = {}
  for _, v in ipairs(a) do table.insert(out, v) end
  for _, v in ipairs(b) do table.insert(out, v) end
  return out
end
