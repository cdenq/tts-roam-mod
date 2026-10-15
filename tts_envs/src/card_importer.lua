--[[ Card Importer: clone one card per event intro, generic card and origin.

Unlike the Tile/Token Importer, this script holds NO data. Cards are dumb
objects that carry only an id in GMNotes; Global owns EVENT_DATA, renders every
card from it (onObjectSpawn / onLoad -> renderCard) and handles every click
(function_owner = Global on each button). So:

  importing  = clone the row's template, stamp GMNotes, clear memo
  rendering  = Global's job, automatic, forever after

Keeping the data in Global is what makes a text fix cheap: edit the sheet, sync,
push, and every card already on the table re-renders. Baking data into each
card would mean re-importing for every typo.

CARD_SETS and CARD_SET_ORDER are read from Global at load time -- they are
generated into Global by tools/sync/sync_events_data.py alongside EVENT_DATA.

Templates sit loose in this bag, each a Card whose GMNotes is the value the
`template` column names (event_intro, generic, origins) -- any value works.
event_intro and origins templates are generic cards (sync_card_templates.py),
so import the generic set first and keep those cards in this bag.
A row with face_url / back_url gets that art instead of the template's.
They are never consumed: the importer takes one out, clones from it, and puts
it straight back. "Take out all" skips them. See src/lib/template_import.lua.

Import is APPEND-ONLY. Clicking twice imports twice; delete the old copies by
hand.
]]

--[[ BEGIN SHARED template_import.lua -- do not edit ]]
--[[ END SHARED template_import.lua ]]

--[[ Button panel geometry -- same scheme as the Tile/Token Importer.

Object-local units, multiplied by the bag's own scale. +z is the bag's front, so
the grid hangs below it and the bag stays clear. TTS rasterises button text at
font_size then shrinks by scale, so big font + small scale = sharper text;
SHARPNESS is that multiplier and everything else is in VISIBLE units.
]]
PANEL = {
  SHARPNESS = 4,
  COL_X = {-3.1, 3.1},      -- sets, commands
  HEADER_Z = 1.6,
  ROW_START_Z = 2.5,
  ROW_STEP = 0.85,
  LIFT = 0.25,

  BTN_W = 1500,
  BTN_H = 380,
  BTN_FONT = 170,
  BTN_SCALE = 0.75,

  HEADER_FONT = 190,
  HEADER_COLOR = {1, 1, 1},
  HEADER_BG = {0, 0, 0, 0},

  SET_COLOR = {0.3, 0.34, 0.6},
  CMD_COLOR = {0.45, 0.3, 0.5},
  TEXT_COLOR = {1, 1, 1},
}

-- Where "Take out all" lays the cards down.
TAKEOUT = {
  PER_ROW = 8,
  MARGIN = 0.4,
  START_OFFSET = 6,   -- to the SIDE, clear of the button grid
  ROW_DIR = -1,       -- rows march away from the buttons
  DROP_HEIGHT = 1.5,
}

PROGRESS_EVERY = 10

-- How far to the side of the template each clone spawns. Cards MERGE INTO A
-- DECK on contact, so a clone landing on the template would destroy it; this
-- keeps them apart until the clone is bagged.
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

--[[ Read the card index out of Global.

TTS sandboxes each script's tables: handing a table from Global.getVar() to
another object's script raises "Attempt to perform operations with resources
owned by different scripts". So Global flattens the index to a string
(cardIndexText) and this parses it back into tables owned by THIS script.

One call per import, not one per card. Returns:
  order  {setName, ...}                         in sheet order
  sets   {setName = {row, ...}}                 rows per set, in sheet order
         row = {id =, name =, template =, face =, back =}  what one clone is stamped from
or nil when Global has no index (sync not run, or Global not pushed).
]]
function cardIndex()
  local ok, text = pcall(function() return Global.call("cardIndexText") end)
  if not ok or type(text) ~= "string" or text == "" then return nil end

  local order, sets = {}, {}
  for line in string.gmatch(text, "[^\n]+") do
    local setName, id, template, face, back, title = string.match(line,
      "^([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t(.*)$")
    if setName and id then
      if sets[setName] == nil then
        sets[setName] = {}
        table.insert(order, setName)
      end
      table.insert(sets[setName], {
        id = id, name = (title ~= "" and title) or id, template = template,
        face = face, back = back})
    end
  end
  if #order == 0 then return nil end
  return order, sets
end

function buildPanel()
  self.clearButtons()

  local order, sets = cardIndex()

  addHeader("CARD SETS", 1)
  addHeader("COMMANDS", 2)

  if order == nil then
    addButton("no data", "Global has no card index -- run master_sync.cmd and "
              .. "push the Global script", "noop", 1, 1, {0.5, 0.2, 0.2})
  else
    -- A click_function must be a named global, so one wrapper per set is
    -- defined dynamically and the button refers to it by name.
    for i, setName in ipairs(order) do
      local fn = "import_" .. string.gsub(setName, "%W", "_")
      local s = setName
      _G[fn] = function() importSet(s) end
      local n = #(sets[setName] or {})
      addButton(setName .. " (" .. n .. ")",
                "Import the " .. n .. " " .. setName .. " cards",
                fn, 1, i, PANEL.SET_COLOR)
    end
  end

  addButton("Import all", "Import every card set", "importAll", 2, 1,
            PANEL.CMD_COLOR)
  addButton("Take out all", "Lay every card out in a grid (templates stay in)",
            "takeOutAll", 2, 2, PANEL.CMD_COLOR)
  addButton("Diff with master bag",
            "Take each card's master copy out, into the slot Take out all "
            .. "will put this bag's copy in", "diffWithMaster", 2, 3,
            PANEL.CMD_COLOR)
end

function importAll() importSet(nil) end


-- ----------------------------------------------------------------- import ---

--[[ Rows to import: one set, or every set when setName is nil. All of it
comes from the single cardIndex() call, so the import needs no further traffic
with Global.
]]
local function rowsFor(setName)
  local order, sets = cardIndex()
  if order == nil then return nil end
  local out = {}
  for _, s in ipairs(order) do
    if setName == nil or s == setName then
      for _, row in ipairs(sets[s] or {}) do table.insert(out, row) end
    end
  end
  return out
end

-- A card is the only thing Global's renderer draws on.
local function prepareCardTemplate(template)
  local tag = template.type
  if tag ~= "Card" then
    return nil, "is a " .. tostring(tag) .. ", expected a Card"
  end
  return {}
end

--[[ Identity and state:
  name         the authored title ("The Bell Line"), so the card reads properly
               in search, hands and bag listings
  GMNotes      the permanent id -- what Global renders from
  memo         branch state, empty on a fresh card (= start at the intro)
  description  cleared: the card's text is DRAWN from Global's data, so a
               description inherited from the template would be stale
               duplicate text in the hover tooltip
Everything else (size, and face/back unless the row names them -- see
restyleCard) comes from the template.

The NAME is cosmetic and the ID is authoritative: Global renders from GMNotes,
so renaming a card never changes what it shows. Global's onObjectSpawn renders
each clone on the way through; that work is wasted on a card heading straight
into the bag, but harmless.
]]
local function stampCard(clone, row)
  clone.setName(row.name)
  clone.setGMNotes(row.id)
  clone.setDescription("")
  clone.memo = ""
  return true
end

--[[ Swap a clone's art for the row's face_url / back_url.

A card's images live in its CustomDeck entry, and CardID (deck key * 100 +
index) picks its cell on a sheet. A new face is one image, so the entry
becomes a 1x1 sheet and the card cell 0. Edits a getData() copy: the library
respawns the clone from it. Returns nil when the row keeps the template's art.
]]
local function restyleCard(data, row)
  if row.face == "" and row.back == "" then return nil end
  for key, deck in pairs(data.CustomDeck or {}) do
    if row.face ~= "" then
      deck.FaceURL = row.face
      deck.NumWidth = 1
      deck.NumHeight = 1
      data.CardID = tonumber(key) * 100
    end
    if row.back ~= "" then
      deck.BackURL = row.back
      deck.UniqueBack = false
    end
    return data
  end
  error("template has no CustomDeck entry to put the art in")
end

function importSet(setName)
  local rows = rowsFor(setName)
  if rows == nil then
    broadcastToAll("Global has no card index. Run master_sync.cmd and push the "
                   .. "Global script first.", {1, 0.5, 0.5})
    return
  end
  if #rows == 0 then
    broadcastToAll("No cards for " .. tostring(setName) .. ".", {1, 0.8, 0.3})
    return
  end
  runTemplateImport({
    rows = rows, noun = "card", label = setName or "all sets",
    prepare = prepareCardTemplate, restyle = restyleCard, stamp = stampCard,
  })
end


-- --------------------------------------------------------------- take out ---

-- Lays cards out beside the bag; see runTakeOut in src/lib/template_import.lua.
function takeOutAll()
  runTakeOut("card")
end

-- See runDiffWithMaster in src/lib/template_import.lua.
function diffWithMaster()
  runDiffWithMaster("card")
end
