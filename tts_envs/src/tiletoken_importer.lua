--[[ Tile/Token Importer: mass-import items from the generated data bank.

This is the source for the in-game bag nicknamed "Tile/Token Importer"
(GUID 85a721). tools/sync_items_data.py inlines the data and writes the result
to .tts/objects/ for the extension to push.

ITEM_DATA and ITEM_SETS are inlined above by tools/sync_items_data.py. They live
HERE rather than in Global because this script is their only consumer, and
object scripts do not share Global's scope.

Workflow:
  1. edit data/tiles.xlsx (items, skills or statuses sheet)
  2. run master_sync.cmd          (validates, regenerates this script)
  3. Ctrl+Alt+L in VS Code        (pushes it to the bag in-game)
  4. click a set button on the bag

The import CLONES a template object, so every property you are not overriding
-- thickness, scale, grid snapping, tint -- comes along for free. Only the image
URLs, name, description and GMNotes are stamped per item.

Templates sit loose in this bag, found by GMNotes: each row's `template` column
names the one it is cloned from. The defaults are
  TEMPLATE_TILE    a Custom Tile  (has a back face: image_bottom)
  TEMPLATE_TOKEN   a Custom Token (single face, no back)
and any number more may be added. A template must be the TTS type its rows'
tts_type claims; the import checks that before cloning.

None is ever consumed: the importer takes one out, clones from it, and puts it
straight back. "Take out all" skips them. See src/lib/template_import.lua.

Import is APPEND-ONLY by design. Clicking twice imports twice; delete the old
copies by hand. A dead or typo'd image URL just yields an untextured object --
eyeball the result.
]]

--[[ BEGIN SHARED template_import.lua -- do not edit ]]
--[[ END SHARED template_import.lua ]]

--[[ Button panel geometry.

Three fixed columns; rows grow downward with the longer set list. Positions are
object-local {x, y, z}. TTS rasterises button text at font_size then shrinks the
button by scale, so big font + small scale = sharper text. SHARPNESS is that
multiplier and every other number here is in VISIBLE units -- same trick as
LAYOUT in global.lua.
]]
PANEL = {
  SHARPNESS = 4,

  --[[ Columns, and where the grid sits relative to the bag.

  These are OBJECT-LOCAL units: TTS multiplies them by the bag's own scale, and
  a bag is only about 1 unit across, so numbers that suit a card come out tiny
  here. Everything below is sized for a bag-sized object.

  +z is toward the bag's front, so the grid hangs BELOW it on the table and the
  bag itself stays clear.
  ]]
  COL_X = {-3.1, 0, 3.1},   -- tokens, tiles, commands
  HEADER_Z = 1.6,           -- first row below the bag
  ROW_START_Z = 2.5,
  ROW_STEP = 0.85,
  LIFT = 0.25,               -- just above the table surface

  -- BTN_SCALE shrinks the whole button; BTN_W/H are pre-shrink pixels. Visible
  -- size is roughly (W or H) * SCALE / SHARPNESS, so these give a button about
  -- 2.8 x 0.7 local units -- readable without covering the table.
  BTN_W = 1500,
  BTN_H = 380,
  BTN_FONT = 170,
  BTN_SCALE = 0.75,

  HEADER_FONT = 190,
  HEADER_COLOR = {1, 1, 1},
  HEADER_BG = {0, 0, 0, 0},     -- transparent: a label, not a control

  TOKEN_COLOR = {0.24, 0.38, 0.58},
  TILE_COLOR = {0.26, 0.5, 0.32},
  CMD_COLOR = {0.45, 0.3, 0.5},
  TEXT_COLOR = {1, 1, 1},
}

-- Where "Take out all" lays the items down.
TAKEOUT = {
  PER_ROW = 10,

  -- A flat gap between laid-out objects, in world units, added to whatever the
  -- object itself measures. Roomy enough to read and pick up, not packed: a
  -- 2.0 tile lands on a 3.25 pitch.
  MARGIN = 1.25,

  -- The button grid hangs below the bag (+z), so lay items out to the SIDE and
  -- run rows AWAY from it (-z) rather than over the panel.
  START_OFFSET = 5,  -- how far to the side the first row sits
  ROW_DIR = -1,       -- rows march away from the buttons
  DROP_HEIGHT = 1.5,
}

-- Yield to TTS every this many objects so a 500-item run keeps the game
-- responsive. The reference importer gets away with one trailing wait(3); that
-- does not hold at this scale.
PROGRESS_EVERY = 25

-- How far to the side of the template each clone spawns, so a fresh clone can
-- never land on the object it was cloned from.
CLONE_OFFSET = 4


-- ------------------------------------------------------------------ setup ---

function onLoad()
  buildPanel()
end

function sharp(font, width, height, extra)
  local k = PANEL.SHARPNESS
  local s = (extra or 1) / k
  return font * k, width * k, height * k, {s, s, s}
end

function rowZ(n)
  return PANEL.ROW_START_Z + (n - 1) * PANEL.ROW_STEP
end

function addButton(label, tooltip, fn, col, row, color)
  local f, w, h, sc = sharp(PANEL.BTN_FONT, PANEL.BTN_W, PANEL.BTN_H,
                            PANEL.BTN_SCALE)
  self.createButton({
    click_function = fn, function_owner = self,
    label = label, tooltip = tooltip,
    position = {PANEL.COL_X[col], PANEL.LIFT, rowZ(row)},
    rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f,
    color = color, font_color = PANEL.TEXT_COLOR
  })
end

function addHeader(label, col)
  local f, w, h, sc = sharp(PANEL.HEADER_FONT, PANEL.BTN_W, PANEL.BTN_H,
                            PANEL.BTN_SCALE)
  self.createButton({
    click_function = "noop", function_owner = self,
    label = label, tooltip = "",
    position = {PANEL.COL_X[col], PANEL.LIFT, PANEL.HEADER_Z},
    rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f,
    color = PANEL.HEADER_BG, font_color = PANEL.HEADER_COLOR
  })
end

function noop() end

--[[ Build the 3-column grid.

Set buttons are generated from ITEM_SETS, so adding a set to the CSV makes a
button appear after the next sync -- there is no in-game text to maintain.

A click_function must be a named global, so one wrapper per set is defined
dynamically into the global table and the button refers to it by name.
]]
function buildPanel()
  self.clearButtons()

  addHeader("TOKENS", 1)
  addHeader("TILES", 2)
  addHeader("COMMANDS", 3)

  local plan = {
    {type = "token", col = 1, color = PANEL.TOKEN_COLOR},
    {type = "tile", col = 2, color = PANEL.TILE_COLOR},
  }
  for _, p in ipairs(plan) do
    for i, setName in ipairs(ITEM_SETS[p.type] or {}) do
      local fn = "import_" .. p.type .. "_" .. string.gsub(setName, "%W", "_")
      local t, s = p.type, setName
      _G[fn] = function() importSet(t, s) end
      addButton(setName, "Import the " .. setName .. " " .. p.type .. " set",
                fn, p.col, i, p.color)
    end
  end

  addButton("Import all tokens", "Import every token set",
            "importAllTokens", 3, 1, PANEL.CMD_COLOR)
  addButton("Import all tiles", "Import every tile set",
            "importAllTiles", 3, 2, PANEL.CMD_COLOR)
  addButton("Take out all", "Lay every item out in a grid (templates stay in)",
            "takeOutAll", 3, 3, PANEL.CMD_COLOR)
  addButton("Diff with master bag",
            "Take each item's master copy out, into the slot Take out all "
            .. "will put this bag's copy in", "diffWithMaster", 3, 4,
            PANEL.CMD_COLOR)
end

function importAllTokens() importSet("token", nil) end
function importAllTiles() importSet("tile", nil) end


-- ----------------------------------------------------------------- import ---

--[[ Rows for one TTS object kind, optionally narrowed to one set.
nil set = all of that kind.

NOTE this filters on `tts_type` (tile/token -- the TTS object), not `type`
(weapon/armor/consumable/tool/material -- the game-mechanical kind). The button
grid is organised by what gets cloned, so tts_type is the right axis here.
]]
function rowsFor(ttsType, setName)
  local out = {}
  for _, it in ipairs(ITEM_DATA) do
    if it.tts_type == ttsType and (setName == nil or it.set == setName) then
      table.insert(out, it)
    end
  end
  return out
end

-- The TTS object type each tts_type must be cloned from.
local OBJECT_TYPE = {tile = "Custom_Tile", token = "Custom_Token"}

--[[ Vet a template, once per run, before anything is cloned from it.

Sync cannot catch a wrong template: the sheet is in the repo, the template is
in the game. A tile set cloned from a Custom Token would silently drop every
image_back, so check here rather than producing 200 wrong objects.

getCustomObject() is the template's own parameter table; every clone starts
from it, so an empty URL on a row inherits the template's image.
]]
local function prepareItemTemplate(template, rows)
  local ttsType = rows[1].tts_type
  local expect = OBJECT_TYPE[ttsType]
  if template.name ~= expect then
    return nil, "is a " .. tostring(template.name) .. " but its rows say " ..
                ttsType .. " (expected " .. tostring(expect) .. ")"
  end
  local base = template.getCustomObject()
  if base == nil then
    return nil, "is not a custom object, so its image cannot be read"
  end
  return {base = base, ttsType = ttsType}
end

local function stampItem(clone, it, ctx)
  --[[ setCustomObject replaces the WHOLE parameter table, so start from the
  template's own table and override only what the row provides. An empty URL
  therefore inherits the template's image -- which is the point: give a tile
  template a shared back face and a sheet with only front URLs gives every
  tile that same back for free. ]]
  local p = {}
  for k, v in pairs(ctx.base) do p[k] = v end
  if it.image_front ~= "" then p.image = it.image_front end
  -- Tokens have no back face; the generator already warned about the value.
  if ctx.ttsType == "tile" and it.image_back ~= "" then
    p.image_bottom = it.image_back
  end
  clone.setCustomObject(p)

  -- Item rows only: tokens.xlsx rows carry a role, and meeples are matched by name.
  local name = it.name
  if it.role == nil then
    -- nil when Global predates NAME_COLORS: import plain rather than fail.
    name = Global.call("itemDisplayName", {name = it.name, tier = it.tier, subtype = it.subtype}) or it.name
  end
  clone.setName(name)
  clone.setDescription(it.description)
  clone.setGMNotes(it.gmnotes)

  --[[ Live per-instance state, and the tags Global renders from.

  memo is seeded READY ("CD: 0 | Use: 5"), never spent -- CD counts time
  remaining, so a fresh item is 0 and jumps to the full duration when used.
  Both are generated from whether cooldown/uses are set, so the tag can never
  disagree with the numbers.

  Global looks for Item-Cooldown / Item-Uses to draw the USE button and the
  greyed-out overlay; the GM "end day" button decrements every Item-Cooldown
  it can find. See plans/auto_TODO.md -- that rendering is NOT built yet.
  ]]
  clone.memo = it.memo
  --[[ addTag is a newer TTS API. Guard it so an older build degrades to
  "no tags" rather than erroring out of the whole import -- the memo still
  carries the state, so nothing is lost but the tag itself. ]]
  if clone.addTag ~= nil then
    for _, tag in ipairs(it.tags or {}) do
      clone.addTag(tag)
    end
  elseif #(it.tags or {}) > 0 and not ctx.warnedTags then
    ctx.warnedTags = true
    printToAll("This TTS build has no addTag(); items keep their memo but "
               .. "carry no tags.", {1, 0.8, 0.3})
  end
  return true
end

function importSet(itemType, setName)
  local rows = rowsFor(itemType, setName)
  if #rows == 0 then
    broadcastToAll("No items for " .. itemType ..
                   (setName and (" set " .. setName) or "") ..
                   ". Run master_sync.cmd?", {1, 0.8, 0.3})
    return
  end
  runTemplateImport({
    rows = rows, noun = itemType,
    label = setName or ("all " .. itemType .. "s"),
    prepare = prepareItemTemplate, stamp = stampItem,
  })
end


-- --------------------------------------------------------------- take out ---

-- Lays items out beside the bag; see runTakeOut in src/lib/template_import.lua.
function takeOutAll()
  runTakeOut("item")
end

-- See runDiffWithMaster in src/lib/template_import.lua.
function diffWithMaster()
  runDiffWithMaster("item")
end
