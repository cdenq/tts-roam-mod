--[[ Branching event cards.

Card identity and state live on the object, so both survive saves and reloads:
  GMNotes  permanent entry node, e.g. "EV1". Set once by a tagger, never changed.
  memo     JSON card memory: {at = <node id>, picks = {...}}

`picks` is the history. Each entry records a decision the card has already
resolved:
  {node = "EV1", option = 2, label = "Sneak across", outcome = "EV1_sneak_fail"}

The roll happens once, the first time an option is clicked, and is then LOCKED
IN for the session -- revisiting that node replays the same outcome instead of
rerolling. Only the X button clears it.
]]

--[[ Card face layout -- tune the template here.

Positions are card-local units, {x, y, z}:
  x  left(-) / right(+) across the face
  y  HEIGHT ABOVE THE FACE -- raise LIFT if text clips into the card art
  z  up(-) / down(+) the face; a standard TTS card runs about -1.4 .. 1.4

TTS rasterises button text at font_size then shrinks the button by scale, so
big font + small scale = same visible size, more pixels, sharper text.
SHARPNESS is that multiplier. Every other number below is in VISIBLE units.
]]
LAYOUT = {
  SHARPNESS = 4,           -- supersample factor for all button text
  CARD_TOP = -1.4,         -- top edge of the card face in local z
  CARD_BOTTOM = 1.4,       -- bottom edge
  LIFT = 0.25,              -- how far every element floats above the face

  ID_Z = -1.34,            -- "EV1", centred
  ID_FONT = 45,
  ID_COLOR = {0, 0, 0},

  TITLE_Z = -1.18,         -- "Abandoned Toll Bridge", centred under the id
  TITLE_FONT = 76,
  TITLE_COLOR = {1, 1, 1},

  --[[ Description, pinned by its TOP edge rather than its centre.

  A TTS button centres on its position, so a tall block grows upward too. Left
  at a fixed centre, a long description creeps toward the title while a short
  one leaves a gap -- which reads as an inconsistent blank line between the
  title and the body. renderCard offsets by half the block's height so the TOP
  stays put and only the bottom moves.

  DESC_TOP_Z is where the first line sits. DESC_LINE_H is one line of wrapped
  text at DESC_FONT; raise it if lines overlap, lower it if they look loose.
  ]]
  DESC_TOP_Z = -0.9,
  DESC_LINE_H = 0.085,
  DESC_X = 0,              -- centred box; the TEXT inside is still left aligned
  DESC_FONT = 58,
  DESC_COLOR = {0.93, 0.93, 0.93},
  DESC_WRAP = 37,          -- characters per line before wrapping

  --[[ Origin card art (card_image), a decal between the title and the text.
  The image is STRETCHED to IMAGE_W x IMAGE_H, so author art at that ratio.
  If it shows upside down or mirrored, change the y of IMAGE_ROT to 0. ]]
  IMAGE_Z = -0.55,         -- centre of the image
  -- The origin art runs 1.05-1.20 wide per 1 tall (1.14 on average).
  IMAGE_W = 1.14,
  IMAGE_H = 1.0,
  --[[ Observed, not documented: a scripted decal 0.2 above a card does not
  render, at 0.36 (what the Decal Tool stamps) it does. It sits above LIFT,
  but the image spans IMAGE_Z +/- IMAGE_H/2, clear of every text button. ]]
  IMAGE_LIFT = 0.36,
  IMAGE_ROT = {90, 180, 0},
  --[[ The decal's z scale. Not documented; observed: at z = 1 a decal 0.2
  above the card is invisible, at 15 it shows. The Decal Tool itself stamps
  z around 15, so match it. ]]
  IMAGE_DEPTH = 15,
  IMAGE_DESC_TOP_Z = 0.03, -- where the text starts when there is an image

  -- Options start 66% down the card and descend from there.
  OPTION_START_PCT = 0.66,
  OPTION_SPACING = 0.3,
  OPTION_SCALE = 0.7,     -- shrink buttons a further 33%
  OPTION_FONT = 70,
  OPTION_WIDTH = 950,
  OPTION_HEIGHT = 175,
  OPTION_COLOR = {0.17, 0.17, 0.17},
  OPTION_TEXT = {1, 1, 1},

  -- A chosen option on the review screen, and the ones not taken.
  TAKEN_COLOR = {0.35, 0.75, 0.35},
  TAKEN_TEXT = {0, 0, 0},
  UNTAKEN_TEXT = {0.65, 0.65, 0.65},

  -- Corner controls, present on every screen.
  RESET_X = 0.95,          -- red X, BOTTOM right
  RESET_Z = 1.4,
  RESET_SCALE = 0.35,      -- size of the X button specifically
  RESET_COLOR = {0.75, 0.15, 0.15},
  BACK_X = -0.875,          -- "<", top left
  BACK_Z = -1.34,
  BACK_SCALE = 0.5,       -- size of the < button specifically
  BACK_COLOR = {0.22, 0.22, 0.26},
  -- "o", mirrored from "<" across the card's centre line.
  SPAWN_X = 0.875,
  SPAWN_Z = -1.34,
  SPAWN_SCALE = 0.5,
  SPAWN_COLOR = {0.2, 0.6, 0.25},
  CORNER_FONT = 70,
  CORNER_SIZE = 170,
}

--[[ Where spawned rewards come from.

Every category works the same way: a weighted name list per slot, looked up by
exact object name inside one bag. Adding a category means adding a row here and
the matching columns on scenario_outcomes -- no new code.
]]
SPAWN_SOURCES = {
  {key = "items", bag = "c98e54", label = "item"},
  {key = "status", bag = "72ed8a", label = "status"},
  {key = "meeple", bag = "ccfa1b", label = "meeple"},
}
GOLD_BAG = "f0d3ab"

-- Where spawned objects land, as a world offset from the card.
SPAWN_PLACEMENT = {
  first = {0, 10, 0},   -- first object, straight up from the card
  step = 5,             -- each later object goes this much higher
}

-- Font/size/scale triple for one button at the requested visible size.
-- `extra` shrinks a button further (option buttons use OPTION_SCALE).
function sharp(font, width, height, extra)
  local k = LAYOUT.SHARPNESS
  local e = extra or 1
  local s = e / k
  return font * k, width * k, height * k, {s, s, s}
end

-- z position of the nth option button, measured as a fraction down the card.
function optionZ(n)
  local L = LAYOUT
  local span = L.CARD_BOTTOM - L.CARD_TOP
  local start = L.CARD_TOP + span * L.OPTION_START_PCT
  return start + (n - 1) * L.OPTION_SPACING
end

-- ---------------------------------------------------------------- memory ---

-- Read a card's memory, always returning a usable table.
function getMemory(obj)
  local raw = obj.memo
  if not raw or raw == "" then return {at = nil, picks = {}} end
  local ok, data = pcall(function() return JSON.decode(raw) end)
  if not ok or type(data) ~= "table" then
    -- An older card stored a bare node id; treat it as the current node.
    return {at = raw, picks = {}}
  end
  data.picks = data.picks or {}
  return data
end

function setMemory(obj, mem)
  obj.memo = JSON.encode(mem)
end

-- The decision already made at `nodeId`, or nil if this card has not been
-- there yet. This is what locks an outcome in for the session.
function recordedPick(mem, nodeId)
  for _, p in ipairs(mem.picks) do
    if p.node == nodeId then return p end
  end
  return nil
end

-- Which node the card is currently showing.
function currentNode(obj)
  local mem = getMemory(obj)
  if mem.at and EVENT_DATA[mem.at] then return mem.at end
  local g = obj.getGMNotes()
  if g and g ~= "" and EVENT_DATA[g] then return g end
  return nil
end

function entryNode(obj)
  local g = obj.getGMNotes()
  if g and g ~= "" and EVENT_DATA[g] then return g end
  return nil
end

-- --------------------------------------------------------------- drawing ---

function renderCard(obj)
  --[[ A card's GMNotes id resolves against TWO tables: event nodes (EV-prefixed)
  and origins (O-prefixed). Origins render here rather than through a separate
  path so there is one card system, not two. ]]
  local gm = obj.getGMNotes and obj.getGMNotes() or nil
  if gm ~= nil and gm ~= "" and ORIGIN_DATA ~= nil and ORIGIN_DATA[gm] ~= nil then
    return drawOrigin(obj, gm)
  end

  local nodeId = currentNode(obj)
  if not nodeId then return false end
  local mem = getMemory(obj)
  -- `review` means: showing a node this card has already resolved, so the
  -- options are history, not live choices.
  local review = mem.reviewing and recordedPick(mem, nodeId) ~= nil
  drawNode(obj, nodeId, mem, review)
  return true
end

--[[ An ORIGIN card: a starting choice that specialises a character.

Unlike an event node it has no branches and no memory -- one button spawns
everything the origin grants, and the card is NOT consumed, so it stays on the
table as a record of what was chosen. Once used, Begin and the effect are
gone for good (memo.taken; see originTakeClick).
]]
function drawOrigin(obj, originId)
  local origin = ORIGIN_DATA[originId]
  local L = LAYOUT
  obj.clearButtons()
  obj.clearInputs()

  local f, w, h, sc

  f, w, h, sc = sharp(L.ID_FONT, 0, 0)
  obj.createButton({
    click_function = "noop", function_owner = Global,
    label = originId,
    position = {0, L.LIFT, L.ID_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, font_color = L.ID_COLOR
  })

  f, w, h, sc = sharp(L.TITLE_FONT, 0, 0)
  obj.createButton({
    click_function = "noop", function_owner = Global,
    label = origin.name,
    position = {0, L.LIFT, L.TITLE_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, font_color = L.TITLE_COLOR
  })

  -- Effect then flavour, as one block anchored by its top edge like a node's
  -- description. Flavour is quoted, matching how item tiles render.
  --[[ Flavour first and unquoted, then a blank line, then the effect in
  brackets. The order is deliberate: an origin reads as a piece of history that
  happens to have consequences, rather than a rules entry with decoration. ]]
  --[[ Each block is wrapped SEPARATELY and rejoined with a blank line.
  wrapLines iterates over %S+, so it throws away any newline already in the
  string -- wrapping the joined text would collapse the gap. ]]
  local parts = {}
  if origin.flavor ~= nil and origin.flavor ~= "" then
    table.insert(parts, leftAlign(origin.flavor, L.DESC_WRAP))
  end
  local taken = getMemory(obj).taken
  if not taken and origin.effect ~= nil and origin.effect ~= "" then
    table.insert(parts, leftAlign("[" .. origin.effect .. "]", L.DESC_WRAP))
  end
  local text = table.concat(parts, "\n\n")
  local lines = 1
  for _ in string.gmatch(text, "\n") do lines = lines + 1 end

  local hasImage = origin.image ~= nil and origin.image ~= ""
  setOriginImage(obj, hasImage and origin.image or nil)
  local descTop = hasImage and L.IMAGE_DESC_TOP_Z or L.DESC_TOP_Z

  -- A taken origin with no flavour has nothing left to say: no button at all.
  if text ~= "" then
    f, w, h, sc = sharp(L.DESC_FONT, 0, 0)
    obj.createButton({
      click_function = "noop", function_owner = Global,
      label = text,
      position = {L.DESC_X, L.LIFT,
                  descTop + (lines - 1) * L.DESC_LINE_H / 2},
      rotation = {0, 0, 0}, scale = sc,
      width = w, height = h, font_size = f, font_color = L.DESC_COLOR
    })
  end

  -- One button, which grants everything, until it has been used.
  if not taken and spawnHasAnything(origin.spawn) then
    f, w, h, sc = sharp(L.OPTION_FONT, L.OPTION_WIDTH, L.OPTION_HEIGHT,
                        L.OPTION_SCALE)
    obj.createButton({
      click_function = "originTakeClick", function_owner = Global,
      label = "Begin", tooltip = "Take everything this origin grants.",
      -- The 4th and last slot of the option grid, so it sits at the bottom of
      -- the card rather than directly under the text.
      position = {0, L.LIFT, optionZ(4)}, rotation = {0, 0, 0}, scale = sc,
      width = w, height = h, font_size = f,
      color = L.OPTION_COLOR, font_color = L.OPTION_TEXT
    })
  end
  return true
end

ORIGIN_IMAGE_DECAL = "origin_card_image"

--[[ Put the origin's art on the card as a decal, or take it off when `url` is
nil. Only our own decal is touched, so any others on the card survive.
setDecals replaces the whole list, which makes re-rendering idempotent. ]]
function setOriginImage(obj, url)
  if obj.getDecals == nil then return end
  --[[ onObjectSpawn fires while the card is still spawning, and decals set then
  are lost when the spawn completes (buttons survive, decals do not). Wait it
  out and apply them to the finished object. ]]
  if obj.spawning or obj.loading_custom then
    Wait.condition(
      function()
        if not obj.isDestroyed() then setOriginImage(obj, url) end
      end,
      function()
        return obj.isDestroyed() or not (obj.spawning or obj.loading_custom)
      end)
    return
  end
  local keep = {}
  for _, d in ipairs(obj.getDecals() or {}) do
    if d.name ~= ORIGIN_IMAGE_DECAL then table.insert(keep, d) end
  end
  if url ~= nil then
    local L = LAYOUT
    table.insert(keep, {
      name = ORIGIN_IMAGE_DECAL, url = url,
      position = {0, L.IMAGE_LIFT, L.IMAGE_Z},
      rotation = L.IMAGE_ROT,
      scale = {L.IMAGE_W, L.IMAGE_H, L.IMAGE_DEPTH},
    })
  end
  obj.setDecals(keep)
end

--[[ Grant an origin's contents. The card is deliberately NOT destroyed.

Once something has spawned, memo records it as taken and the card redraws
without Begin or the effect -- memo survives a reload, so they stay gone.
If nothing spawned (all of it missing from its bag) Begin stays to retry. ]]
originSpawning = {}

function originTakeClick(obj)
  local gm = obj.getGMNotes and obj.getGMNotes() or nil
  local origin = gm and ORIGIN_DATA and ORIGIN_DATA[gm]
  if origin == nil or getMemory(obj).taken then return end
  local guid = obj.getGUID()
  -- Spawning is async: a second click before it finishes would spawn twice.
  if originSpawning[guid] then return end
  originSpawning[guid] = true
  spawnFrom(obj, origin.spawn, function(report)
    originSpawning[guid] = nil
    if obj.isDestroyed() or #report.spawned == 0 then return end
    local mem = getMemory(obj)
    mem.taken = true
    setMemory(obj, mem)
    renderCard(obj)
  end)
end

function drawNode(obj, nodeId, mem, review)
  local node = EVENT_DATA[nodeId]
  local L = LAYOUT
  obj.clearButtons()
  obj.clearInputs()

  local f, w, h, sc

  -- id, then title on the next line, both centred
  f, w, h, sc = sharp(L.ID_FONT, 0, 0)
  obj.createButton({
    click_function = "noop", function_owner = Global,
    label = entryNode(obj) or "",
    position = {0, L.LIFT, L.ID_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, font_color = L.ID_COLOR
  })
  f, w, h, sc = sharp(L.TITLE_FONT, 0, 0)
  obj.createButton({
    click_function = "noop", function_owner = Global,
    label = node.title,
    position = {0, L.LIFT, L.TITLE_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, font_color = L.TITLE_COLOR
  })

  --[[ Description, anchored by its TOP edge.

  A TTS button is centred on its position, so a block of text grows upward as
  well as downward. With a fixed position that means the gap under the title
  changes with the line count -- an 8-line description creeps up toward the
  title while a 5-line one leaves a visible hole, which reads as an
  inconsistent blank line.

  Offsetting by half the block's height pins the TOP of the text instead, so
  every card starts at the same place and only the bottom moves.
  ]]
  --[[ Flavour first, then a blank line, then the effect in brackets -- the
  same shape an origin card uses.

  Each block is wrapped SEPARATELY and rejoined: wrapLines iterates over %S+ and
  throws away any newline already in the string, so wrapping the joined text
  would collapse the gap between them.
  ]]
  local descParts = {}
  if node.flavor ~= nil and node.flavor ~= "" then
    table.insert(descParts, leftAlign(node.flavor, L.DESC_WRAP))
  end
  if node.effect ~= nil and node.effect ~= "" then
    table.insert(descParts, leftAlign("[" .. node.effect .. "]", L.DESC_WRAP))
  end
  local descText = table.concat(descParts, "\n\n")

  local descLines = 1
  for _ in string.gmatch(descText, "\n") do descLines = descLines + 1 end
  local descZ = L.DESC_TOP_Z + (descLines - 1) * L.DESC_LINE_H / 2

  f, w, h, sc = sharp(L.DESC_FONT, 0, 0)
  obj.createButton({
    click_function = "noop", function_owner = Global,
    label = descText,
    position = {L.DESC_X, L.LIFT, descZ}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f, font_color = L.DESC_COLOR
  })

  -- options
  local taken = review and recordedPick(mem, nodeId) or nil
  for i, opt in ipairs(node.options) do
    local isTaken = taken and taken.option == i
    local color = L.OPTION_COLOR
    local textColor = L.OPTION_TEXT
    local fn = "optionClick"..i

    if review then
      if isTaken then
        color = L.TAKEN_COLOR
        textColor = L.TAKEN_TEXT
        fn = "replayClick"          -- jump straight to the locked outcome
      else
        textColor = L.UNTAKEN_TEXT  -- not taken: inert
        fn = "noop"
      end
    end

    f, w, h, sc = sharp(L.OPTION_FONT, L.OPTION_WIDTH, L.OPTION_HEIGHT, L.OPTION_SCALE)
    obj.createButton({
      click_function = fn, function_owner = Global,
      label = opt.label, tooltip = opt.tooltip,
      position = {0, L.LIFT, optionZ(i)}, rotation = {0, 0, 0}, scale = sc,
      width = w, height = h, font_size = f,
      color = color, font_color = textColor
    })
  end

  drawCorners(obj, nodeId, mem)
end

--[[ Corner controls.

X (clear memory) is on every screen. "<" (see scenario) only appears once the
card has moved past the intro: on the entry node with no decisions made there
is nothing to go back to.
]]
function drawCorners(obj, nodeId, mem)
  local L = LAYOUT
  local f, w, h, sc = sharp(L.CORNER_FONT, L.CORNER_SIZE, L.CORNER_SIZE, L.RESET_SCALE)
  obj.createButton({
    click_function = "resetClick", function_owner = Global,
    label = "X", tooltip = "Reset card memory.",
    position = {L.RESET_X, L.LIFT, L.RESET_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f,
    color = L.RESET_COLOR, font_color = {1, 1, 1}
  })

  if isIntroScreen(obj, nodeId, mem) then return end

  f, w, h, sc = sharp(L.CORNER_FONT, L.CORNER_SIZE, L.CORNER_SIZE, L.BACK_SCALE)
  obj.createButton({
    click_function = "backClick", function_owner = Global,
    label = "<", tooltip = "See scenario.",
    position = {L.BACK_X, L.LIFT, L.BACK_Z}, rotation = {0, 0, 0}, scale = sc,
    width = w, height = h, font_size = f,
    color = L.BACK_COLOR, font_color = {1, 1, 1}
  })

  -- "o" only where there is actually something to hand out.
  if hasSpawn(nodeId) then
    f, w, h, sc = sharp(L.CORNER_FONT, L.CORNER_SIZE, L.CORNER_SIZE, L.SPAWN_SCALE)
    obj.createButton({
      click_function = "spawnClick", function_owner = Global,
      label = "o", tooltip = "Spawn in the associated item, if any.",
      position = {L.SPAWN_X, L.LIFT, L.SPAWN_Z}, rotation = {0, 0, 0}, scale = sc,
      width = w, height = h, font_size = f,
      color = L.SPAWN_COLOR, font_color = {1, 1, 1}
    })
  end
end

-- The intro is the entry node with nothing decided yet. Once the card has a
-- history, showing the entry node is a review screen, not the intro.
function isIntroScreen(obj, nodeId, mem)
  return nodeId == entryNode(obj) and #mem.picks == 0
end

-- Wrap to `width`, then pad each line so the block is left aligned inside a
-- centred button.
--[[ Wrap a description for display.

An earlier version padded every line with trailing spaces out to the width of
the longest one, to fake left alignment inside a centred button. That is what
made the gap under the title look inconsistent from card to card: the padding
changed the block's measured width, and a TTS button centres on its own text,
so each card's description settled at a slightly different height.

Plain wrapping is predictable. ]]
function leftAlign(text, width)
  return table.concat(wrapLines(text, width), "\n")
end

function wrapLines(text, width)
  local lines, line = {}, ""
  for word in string.gmatch(text, "%S+") do
    if line == "" then
      line = word
    elseif #line + #word + 1 <= width then
      line = line.." "..word
    else
      table.insert(lines, line)
      line = word
    end
  end
  if line ~= "" then table.insert(lines, line) end
  return lines
end

function wrapText(text, width)
  return table.concat(wrapLines(text, width), "\n")
end

function noop() end

-- ---------------------------------------------------------------- spawns ---

-- Does this node hand out anything at all?
-- True when a spawn table would hand out anything. GENERIC.
function spawnHasAnything(spawn)
  if not spawn then return false end
  --[[ A slot of nothing but blanks (" | | ") is a real slot that can only
  roll nothing, and spawngold=0 pays nothing in spawnPlanStep -- so neither
  counts as a reward. Otherwise the card shows a button that does nothing.
  Mirrored by spawn_gives_anything() in tools/spawn_cells.py. ]]
  for _, src in ipairs(SPAWN_SOURCES) do
    for _, slot in ipairs(spawn[src.key] or {}) do
      for _, entry in ipairs(slot) do
        local name = parseSpawnEntry(entry)
        if name ~= nil and name ~= "" then return true end
      end
    end
  end
  return spawn.gold ~= nil and spawn.gold[2] > 0
end

-- Card-specific wrapper.
function hasSpawn(nodeId)
  local node = EVENT_DATA[nodeId]
  return spawnHasAnything(node and node.spawn)
end

-- Uniform pick over a weighted slot: repeats in the list raise the odds.
function rollSlot(slot)
  return slot[math.random(#slot)]
end

-- Roll a gold amount. {5, 5} is flat; {1, 5} rolls in range.
function rollGold(gold)
  if not gold then return 0 end
  local lo, hi = gold[1], gold[2]
  if lo == hi then return lo end
  return math.random(lo, hi)
end

--[[ Decide everything this node hands out, without spawning any of it.

Returns a plan: {{category = "items", name = "Ration"}, ...} plus a gold total.
Keeping the roll separate from the spawning makes it testable offline and lets
the button report what it would do before step 3 wires up the bags.
]]
--[[ Roll a spawn table into a plan. GENERIC -- knows nothing about cards.

`spawn` is the shape the data build produces:

    {items  = {{"Ration", "Rope", "", "", ""}, {"Rope"}},
     status = {{"Blessed"}},
     gold   = {1, 5}}

Each entry in `items`/`status` is one SLOT, rolled once. Repeating a name in a
slot raises its odds; an EMPTY entry is a real outcome meaning "nothing drops",
so "Ration|Rope| | | " gives each item 1/5 and nothing 3/5.

Any system with a table of this shape can use the whole spawn pipeline --
quest cards, shop menus, loot tables. Build one, call this, hand the plan to
spawnPlanStep. Nothing below here is card-specific.
]]
function rollSpawn(spawn)
  local plan = {picks = {}, gold = 0}
  if not spawn then return plan end

  for _, src in ipairs(SPAWN_SOURCES) do
    for _, slot in ipairs(spawn[src.key] or {}) do
      local picked = rollSlot(slot)
      if picked ~= nil and picked ~= "" then
        local name, unique = parseSpawnEntry(picked)
        table.insert(plan.picks,
                     {category = src.key, bag = src.bag, name = name,
                      unique = unique})
      end
    end
  end
  plan.gold = rollGold(spawn.gold)
  return plan
end

-- Card-specific: find the node's spawn table, then roll it generically.
function rollSpawnPlan(nodeId)
  local node = EVENT_DATA[nodeId]
  return rollSpawn(node and node.spawn)
end

-- Human-readable summary of a plan, for the chat line.
function describePlan(plan)
  local parts = {}
  for _, p in ipairs(plan.picks) do
    table.insert(parts, p.name)
  end
  if plan.gold > 0 then
    table.insert(parts, plan.gold.." gold")
  end
  if #parts == 0 then return "nothing" end
  return table.concat(parts, ", ")
end

--[[ Item name colors, as BBCode hex. Mirrors taxonomy.md "Item name colors".

A subtype color beats the tier color; tier 0 and untiered rows stay plain.
Names are stamped colored at import, so every lookup by name goes through
plainName() -- the sheet, ECONOMY and LOOTBOX all key on the plain name.
]]
NAME_COLORS = {
  tier = {[1] = "50C050", [2] = "4A9EE8", [3] = "A86CE0"},
  subtype = {contraband = "E05050", quest = "E8C040"},
}

-- Global.call shape: {name =, tier =, subtype =} -> the name to stamp.
function itemDisplayName(args)
  local color = NAME_COLORS.subtype[args.subtype or ""] or NAME_COLORS.tier[args.tier or -1]
  if color == nil then return args.name end
  return "[" .. color .. "]" .. args.name .. "[-]"
end

function plainName(name)
  local plain = string.gsub(name or "", "%[%x%x%x%x%x%x%]", "")
  plain = string.gsub(plain, "%[%-%]", "")
  return plain
end

--[[ Find a named entry inside a bag.

bag.getObjects() lists the CONTENTS without taking anything out; each entry has
a .name and a .guid used to take that specific object. Returns the entry, or
nil when the bag holds nothing by that name.
]]
--[[ A "!" in front of a spawn entry marks a UNIQUE drop.

The spawner TAKES that item out of the canonical bag rather than cloning it, so
only one can exist at a time and a later roll for it finds nothing. Putting it
back makes it available again -- deliberate, so a quest item handed in can drop
for the next party.

The marker is PER REFERENCE: the same item can be unique from one source and
ordinary from another. "!Key|!Key|Box" gives Key 2/3 as a unique take, Box 1/3
as a normal clone.
]]
UNIQUE_PREFIX = "!"

-- Split a spawn entry into its real name and whether it is a unique drop.
function parseSpawnEntry(entry)
  if entry ~= nil and string.sub(entry, 1, 1) == UNIQUE_PREFIX then
    return string.sub(entry, 2), true
  end
  return entry, false
end

function findInBag(bag, name)
  for _, entry in ipairs(bag.getObjects()) do
    if plainName(entry.name) == name then return entry end
  end
  return nil
end

--[[ Put a copy of a named bag object onto the table.

The bag is a normal container, so taking an object REMOVES it. To keep the bag
stocked: take the original out above the bag, clone the clone to the target,
then drop the original back in. The original is briefly visible over its own
bag, never at the world origin.

`done` is called with true/false once the copy exists, so callers can sequence
several spawns without them racing each other.
]]
function spawnCopyFromBag(bagGuid, name, position, done, unique)
  local bag = getObjectFromGUID(bagGuid)
  if not bag then
    printToAll("Spawn bag "..bagGuid.." not found.", {1, 0.5, 0.5})
    if done then done(false) end
    return
  end

  local entry = findInBag(bag, name)
  if not entry then
    --[[ For a unique drop an absent entry is the EXPECTED end state once the
    item has been claimed, not a fault -- say so differently. ]]
    if unique then
      printToAll('"'..name..'" is already in play -- only one exists.',
                 {0.8, 0.8, 0.9})
    else
      printToAll('"'..name..'" is not in bag '..bagGuid..".", {1, 0.8, 0.3})
    end
    if done then done(false) end
    return
  end

  --[[ Unique: take the object straight to its destination and do NOT restock
  the bag, so the next roll finds nothing. Everything else is cloned and the
  original put back. ]]
  if unique then
    bag.takeObject({
      guid = entry.guid,
      position = position,
      smooth = false,
      callback_function = function() if done then done(true) end end
    })
    return
  end

  local original = bag.takeObject({
    guid = entry.guid,
    position = offsetPosition(bag.getPosition(), 0, 3, 0),
    smooth = false
  })

  -- Wait for the original to finish spawning before cloning it.
  Wait.condition(
    function()
      original.clone({position = position, snap_to_grid = false})
      -- and put the original straight back so the bag keeps its stock
      Wait.frames(function()
        bag.putObject(original)
        if done then done(true) end
      end, 2)
    end,
    function() return original ~= nil and not original.spawning end
  )
end

-- Offset a world position without relying on Vector arithmetic: getPosition()
-- may return a plain table depending on TTS version.
function offsetPosition(p, dx, dy, dz)
  local x = p.x or p[1]
  local y = p.y or p[2]
  local z = p.z or p[3]
  return {x + dx, y + dy, z + dz}
end

--[[ Work through a plan one pick at a time.

Spawning is asynchronous, so this recurses on the callback rather than looping;
firing them all at once would race over the same bag. Each object goes higher
than the last so nothing clips into anything else.
]]
function spawnPlanStep(obj, plan, index, placed, report)
  if index > #plan.picks then
    -- items and status are down; gold continues the same y sequence
    if plan.gold and plan.gold > 0 then
      local queue = goldQueue(obj, plan.gold, report)
      spawnGoldStep(obj, queue, 1, placed, report, function(finalPlaced)
        finishSpawn(obj, plan, finalPlaced, report)
      end)
    else
      finishSpawn(obj, plan, placed, report)
    end
    return
  end

  local pick = plan.picks[index]
  local P = SPAWN_PLACEMENT
  local target = offsetPosition(obj.getPosition(),
                                P.first[1],
                                P.first[2] + placed * P.step,
                                P.first[3])

  -- pick.unique comes from a "!" prefix on the spawn entry.
  -- pick.unique comes from a "!" prefix on the spawn entry: take, do not clone.
  spawnCopyFromBag(pick.bag, pick.name, target, function(ok)
    if ok then
      table.insert(report.spawned, pick.name)
      placed = placed + 1
    else
      table.insert(report.missing, pick.name)
    end
    Wait.frames(function()
      spawnPlanStep(obj, plan, index + 1, placed, report)
    end, 3)
  end, pick.unique)
end

--[[ Announce what a spawn produced, then hand back to the caller.

`report.headline` lets a caller replace the default card-style prefix -- a
lootbox uses it for "<player> opens <chest>: ". `report.onDone` fires once
everything is out, which is where a lootbox destroys itself.
]]
function finishSpawn(obj, plan, placed, report)
  local id = obj.getGMNotes() or "card"
  local said = {}
  for _, n in ipairs(report.spawned) do table.insert(said, n) end
  if (report.gold or 0) > 0 then table.insert(said, report.gold.." gold") end

  if report.headline then
    -- "<player> opens <chest>: Ration, Rope, 3 gold"
    printToAll(report.headline ..
               (#said > 0 and table.concat(said, ", ") or "nothing"),
               {0.9, 0.85, 0.6})
  else
    if #said > 0 then
      printToAll(id..": spawned "..table.concat(said, ", ")..".", {0.5, 0.9, 0.6})
    end
    if #said == 0 and #report.missing == 0 then
      printToAll(id..": nothing to spawn.", {0.8, 0.8, 0.8})
    end
  end

  if #report.missing > 0 then
    printToAll(id..": MISSING from bag -- "..table.concat(report.missing, ", ")..".",
               {1, 0.8, 0.3})
  end

  if report.onDone then report.onDone() end
end

--[[ Gold denominations, read from the gold bag at spawn time.

Each coin object in GOLD_BAG carries its value in GMNotes ("1", "5", ...).
Reading them per click means adding a 10-piece to the bag just works, with no
code change. Returns a list sorted high to low, ready for the greedy split.
]]
function goldDenominations(bag)
  local seen, denoms = {}, {}
  for _, entry in ipairs(bag.getObjects()) do
    -- TTS has used both spellings for this field across versions; the
    -- description is a last resort for coins labelled there instead.
    local raw = entry.gm_notes or entry.gmNotes or entry.memo or ""
    local v = tonumber(raw)
    if v and v > 0 and not seen[v] then
      seen[v] = entry
      table.insert(denoms, v)
    end
  end
  table.sort(denoms, function(a, b) return a > b end)
  return denoms, seen
end

--[[ Fewest coins that add up to `amount`.

Greedy from the largest denomination down. With ordinary coin sets (1/5/10)
greedy is optimal. Returns the counts plus whatever could not be made, so the
caller can report a shortfall rather than silently paying the wrong amount.
]]
function splitGold(amount, denoms)
  local counts, left = {}, amount
  for _, d in ipairs(denoms) do
    local n = math.floor(left / d)
    if n > 0 then
      counts[d] = n
      left = left - n * d
    end
  end
  return counts, left
end

--[[ Spawn the coins for `amount`, continuing the shared y sequence.

`placed` is how many objects have already been put down, so gold stacks above
the items and status tiles rather than inside them.
]]
function spawnGoldStep(obj, queue, index, placed, report, done)
  if index > #queue then
    if done then done(placed) end
    return
  end
  local coin = queue[index]
  local P = SPAWN_PLACEMENT
  local target = offsetPosition(obj.getPosition(),
                                P.first[1],
                                P.first[2] + placed * P.step,
                                P.first[3])
  spawnCopyFromBag(GOLD_BAG, coin.name, target, function(ok)
    if ok then
      placed = placed + 1
      report.gold = (report.gold or 0) + coin.value
    else
      table.insert(report.missing, coin.name)
    end
    Wait.frames(function()
      spawnGoldStep(obj, queue, index + 1, placed, report, done)
    end, 3)
  end)
end

-- Build the list of coins to spawn for `amount`, largest first.
function goldQueue(obj, amount, report)
  local bag = getObjectFromGUID(GOLD_BAG)
  if not bag then
    printToAll("Gold bag "..GOLD_BAG.." not found.", {1, 0.5, 0.5})
    return {}
  end
  local denoms, byValue = goldDenominations(bag)
  if #denoms == 0 then
    printToAll("No gold denominations in bag "..GOLD_BAG..
               " (coins need their value in GM Notes).", {1, 0.8, 0.3})
    return {}
  end

  local counts, short = splitGold(amount, denoms)
  local queue = {}
  for _, d in ipairs(denoms) do
    for i = 1, (counts[d] or 0) do
      table.insert(queue, {name = byValue[d].name, value = d})
    end
  end
  if short > 0 then
    printToAll("Could not make "..short.." gold from the available coins.", {1, 0.8, 0.3})
  end
  return queue
end

-- "o": roll what this outcome gives, then put it on the table.
--[[ Roll a spawn table and put the results on the table, above `obj`.

THE GENERIC ENTRY POINT. Any system can call this with its own spawn table:

    spawnFrom(someObject, {items = {{"Ration"}}, gold = {1, 5}})

Objects appear above `obj` and climb so they do not clip. `obj` only supplies
a position -- it does not have to be a card.
]]
-- `onDone(report)` is optional and fires once everything is out.
function spawnFrom(obj, spawn, onDone)
  local plan = rollSpawn(spawn)
  local report = {spawned = {}, missing = {}, gold = 0}
  if onDone then report.onDone = function() onDone(report) end end
  spawnPlanStep(obj, plan, 1, 0, report)
end

-- Card-specific: the "o" button on an event card.
function spawnClick(obj)
  local nodeId = currentNode(obj)
  if not nodeId then return end
  spawnFrom(obj, EVENT_DATA[nodeId] and EVENT_DATA[nodeId].spawn)
end

-- ---------------------------------------------------------------- clicks ---

--[[ Resolve one option.

The outcome is rolled ONCE and then locked in: if this card has already made a
decision at this node, the stored outcome is replayed instead of rerolling.
]]
function chooseOption(obj, index)
  local nodeId = currentNode(obj)
  if not nodeId then return end
  local node = EVENT_DATA[nodeId]
  local opt = node.options[index]
  if not opt then return end

  local mem = getMemory(obj)
  local prior = recordedPick(mem, nodeId)
  local pick

  if prior and prior.option == index then
    pick = prior.outcome                    -- locked in, replay it
  else
    pick = opt.outcomes[math.random(#opt.outcomes)]
    if prior then
      prior.option = index                  -- different choice at a seen node
      prior.label = opt.label
      prior.outcome = pick
    else
      table.insert(mem.picks, {
        node = nodeId, option = index, label = opt.label, outcome = pick
      })
    end
  end

  mem.at = pick
  mem.reviewing = false
  setMemory(obj, mem)
  renderCard(obj)
  broadcastToAll(obj.getGMNotes()..": "..opt.label.." -> "..EVENT_DATA[pick].title,
                 {0.8, 0.9, 1})
end

function optionClick1(obj) chooseOption(obj, 1) end
function optionClick2(obj) chooseOption(obj, 2) end
function optionClick3(obj) chooseOption(obj, 3) end
function optionClick4(obj) chooseOption(obj, 4) end
function optionClick5(obj) chooseOption(obj, 5) end
function optionClick6(obj) chooseOption(obj, 6) end

-- Green button on the review screen: go to the outcome already rolled.
function replayClick(obj)
  local nodeId = currentNode(obj)
  if not nodeId then return end
  local mem = getMemory(obj)
  local prior = recordedPick(mem, nodeId)
  if not prior then return end
  mem.at = prior.outcome
  mem.reviewing = false
  setMemory(obj, mem)
  renderCard(obj)
end

-- "<" shows the entry scenario again, as history rather than a live choice.
function backClick(obj)
  local entry = entryNode(obj)
  if not entry then return end
  local mem = getMemory(obj)
  mem.at = entry
  mem.reviewing = true
  setMemory(obj, mem)
  renderCard(obj)
end

-- "X" wipes the card's memory, including every locked-in roll.
function resetClick(obj)
  obj.memo = ""
  renderCard(obj)
  broadcastToAll((obj.getGMNotes() or "card").." memory cleared.", {1, 0.8, 0.6})
end

-- ------------------------------------------------------------- economy ---

--[[ Reputation and pricing. ECONOMY is generated by tools/sync_gold.py.

REP is the only piece of live state here: everything else is derived from
ECONOMY, which is data. It is per PARTY, not per player -- a merchant's
opinion is of the vagabonds collectively -- and keyed by faction.

  REP = {marquisate = -12, riverfolk = 30}

A faction with no entry sits at its DEFAULT, not at zero: the two great
powers tolerate vagabonds, everyone else assumes you work for them.

Priced through Global rather than on each board because TTS sandboxes a
script's tables -- an object script cannot read ECONOMY. Boards reach it with
Global.call("priceFor", {...}), which keeps one pricing authority and means a
reputation change needs no re-sync anywhere.
]]
REP = REP or {}

--[[ Where a faction starts before anything has happened.

FACTIONS is generated from the factions sheet of data/shops.xlsx by
tools/sync_merchant_board.py: the two great powers tolerate vagabonds,
everyone else assumes you work for one of them.
]]
FACTIONS = FACTIONS or {}

function repScore(faction)
  if faction == nil or faction == "" then return 0 end
  local v = REP[faction]
  if v ~= nil then return v end
  local f = FACTIONS[faction]
  return f and f.default_rep or 0
end

function factionName(faction)
  local f = FACTIONS[faction or ""]
  return f and f.name or tostring(faction)
end

--[[ The band a score falls in: the LAST band whose minimum it meets.

ECONOMY.rep is ordered ascending by sync_gold.py, which also refuses to build
if it is not, so a linear walk is correct and needs no sort here.
]]
function repBand(faction)
  if ECONOMY == nil or ECONOMY.rep == nil then return nil end
  local score = repScore(faction)
  local band = ECONOMY.rep[1]
  for _, b in ipairs(ECONOMY.rep) do
    if score >= b.min then band = b end
  end
  return band
end

function adjustRep(faction, delta)
  if faction == nil or faction == "" or delta == nil then return end
  local before = repScore(faction)
  REP[faction] = before + delta
  local band = repBand(faction)
  printToAll(string.format("%s reputation %+d (now %d, %s)", faction, delta,
                           REP[faction], band and band.name or "?"),
             {0.8, 0.85, 1})
end

--[[ What an object is worth before any margin -- its INTRINSIC value.

Two kinds of money exist and they are valued differently:

  a coin   tagged Gold, face value in GMNotes, worth exactly that either way
  an item  priced by NAME against ECONOMY.prices

Returns nil for anything unpriceable, which the caller must handle rather
than coerce to 0 -- a nil price on a sell is how somebody loses a sword.
]]
GOLD_TAG = "Gold"

function objectValue(obj)
  if obj == nil then return nil end
  if obj.hasTag and obj.hasTag(GOLD_TAG) then
    local v = tonumber(obj.getGMNotes and obj.getGMNotes() or "")
    if v and v > 0 then return math.floor(v), true end
    return nil
  end
  if ECONOMY == nil or ECONOMY.prices == nil then return nil end
  local name = plainName(obj.getName and obj.getName() or "")
  local v = ECONOMY.prices[name]
  if v == nil then return nil end
  return v, false
end

--[[ What a thing costs, or fetches, at a given merchant.

  player buys:  base x (1 + buy_pct  + rep_buy  + party + adjustment_buy)
  player sells: base x (1 + sell_pct + rep_sell + party + adjustment_sell)

Every term is an OFFSET (-0.25 = 25% less) and they ADD, so the tooltip's
lines sum to the net. The bracket never drops below 0: a price can fall to
nothing, never below it.

rep_buy / rep_sell come from the party's reputation band with the merchant's
faction; adjustment_buy / adjustment_sell are the shop's own, from shops.xlsx.

Buying and selling are NOT symmetrical: the same sword costs buy_pct and
fetches sell_pct, and the gap between them is where gold leaves the game.
Coins are the exception -- money is face value in both directions, or
changing a note at a merchant would cost you a quarter of it.

args = {name =, value =, faction =, buying =, adjustment_buy =,
        adjustment_sell =, is_gold =}
`value` overrides the name lookup, for a caller that already has it.
]]
--[[ Price modifiers the PARTY carries -- a guild writ, a blessing, a
haggler's skill. Each entry is {label =, buy =, sell =}, buy and sell being
offsets like every other price term (-0.1 = 10% cheaper).

Nothing populates this yet: it is the hook the party board will fill. The
board's tooltip shows them summed as one Party Adjustment line.
]]
PARTY_PRICE_MODS = PARTY_PRICE_MODS or {}

--[[ Every offset on a price at one merchant, base margins included.

Returns the net buy and sell offsets (summed, NOT yet clamped), and `parts`:
the four sources a player reads -- the standard margin, who they are to this
faction, what the party brings, and this shop's own adjustment -- as one
{buy, sell} each. Every party mod is summed into the single party entry.
]]
function priceFactors(args)
  local parts = {standard = {buy = ECONOMY.buy_pct, sell = ECONOMY.sell_pct},
                 faction = {buy = 0, sell = 0},
                 party = {buy = 0, sell = 0},
                 shop = {buy = args.adjustment_buy or 0,
                         sell = args.adjustment_sell or 0}}
  -- Unaligned traders hold no grudges: their faction line is always +0%.
  local band = repBand(args.faction)
  if args.faction and args.faction ~= "none" and band then
    parts.faction = {buy = band.buy, sell = band.sell}
  end
  for _, mod in ipairs(PARTY_PRICE_MODS) do
    parts.party.buy = parts.party.buy + (mod.buy or 0)
    parts.party.sell = parts.party.sell + (mod.sell or 0)
  end
  local buy, sell = 0, 0
  for _, key in ipairs({"standard", "faction", "party", "shop"}) do
    buy, sell = buy + parts[key].buy, sell + parts[key].sell
  end
  return {buy = buy, sell = sell, parts = parts}
end

-- A summed offset as the multiplier a price is scaled by, floored at 0.
function priceMultiplier(offset)
  return math.max(0, 1 + offset)
end

function priceFor(args)
  if ECONOMY == nil then return nil end
  local base = args.value
  if base == nil and args.name then base = (ECONOMY.prices or {})[args.name] end
  if base == nil then return nil end
  if args.is_gold then return base end

  local f = priceFactors(args)
  local out = base * priceMultiplier(args.buying and f.buy or f.sell)
  --[[ Summed offsets are not exact in floating point: -0.25 + 0.3 is
  0.0499..., so 100 x that floors to 104, not 105. Snap to the nearest
  millionth before rounding so only real fractions round. ]]
  out = math.floor(out * 1e6 + 0.5) / 1e6
  -- Round in the house's favour, as a merchant would.
  if args.buying then return math.ceil(out) end
  return math.floor(out)
end

--[[ Price an OBJECT, resolving coin-vs-item itself. Returns nil if unpriceable.

This is what a board calls per object in a zone, so it does the tag check and
the name lookup in one place rather than making every caller repeat it.
]]
function priceObject(args)
  local obj = args.object or getObjectFromGUID(args.guid or "")
  if obj == nil then return nil end
  local base, isGold = objectValue(obj)
  if base == nil then return nil end
  return priceFor({value = base, faction = args.faction,
                   buying = args.buying,
                   adjustment_buy = args.adjustment_buy,
                   adjustment_sell = args.adjustment_sell,
                   is_gold = isGold})
end

--[[ Table-shaped wrappers for object scripts.

Global.call passes exactly ONE argument, so a board cannot reach a positional
function like spawnCopyFromBag(bag, name, position, done). These adapt the
shape without duplicating the logic.

A closure does not survive Global.call -- it belongs to the caller's script --
so callers name their callback instead: reply_to = their GUID, reply = a
global function on them. It is invoked as obj.call(reply, {value = ...}).
]]
local function replyTo(args)
  if args.reply == nil then return nil end
  return function(value)
    local owner = getObjectFromGUID(args.reply_to)
    if owner ~= nil and not owner.isDestroyed() then
      owner.call(args.reply, {value = value})
    end
  end
end

function spawnCopyFromBagFor(args)
  spawnCopyFromBag(args.bag or SPAWN_SOURCES[1].bag, args.name, args.position,
                   replyTo(args), args.unique)
end

-- spawnFrom for an object script: {guid = the object to spawn above, spawn = a spawn table}.
function spawnFromFor(args)
  local obj = getObjectFromGUID(args.guid)
  if obj == nil or obj.isDestroyed() then return end
  spawnFrom(obj, args.spawn)
end

-- Same as above, but from the meeple bag: tokens live there, not with items.
function spawnMeepleFromBagFor(args)
  spawnCopyFromBag(args.bag or spawnSourceBag("meeple"), args.name,
                   args.position, replyTo(args), args.unique)
end

function spawnSourceBag(key)
  for _, src in ipairs(SPAWN_SOURCES) do
    if src.key == key then return src.bag end
  end
  return nil
end

--[[ Pay `amount` in coins at a world position, fewest coins first.

goldQueue works out the denominations; spawning is sequential because
takeObject is async and a dozen at once against one bag drops objects on the
floor. Coins are CLONED -- spawnCopyFromBag puts the original back -- so the
gold bag is never depleted by paying somebody out.
]]
function spawnGoldAt(args)
  local done = replyTo(args)
  local amount = math.floor(args.amount or 0)
  if amount <= 0 then
    if done then done(0) end
    return
  end
  local queue = goldQueue(nil, amount, nil)
  if #queue == 0 then
    if done then done(0) end
    return
  end
  goldAtStep(queue, 1, 0, args.position, done)
end

function goldAtStep(queue, index, placed, position, done)
  if index > #queue then
    if done then done(placed) end
    return
  end
  local coin = queue[index]
  -- Fan the coins out so they do not stack into one pile.
  local spot = Vector(position) + Vector((placed % 6) * 0.7, 0.4,
                                         math.floor(placed / 6) * 0.7)
  spawnCopyFromBag(GOLD_BAG, coin.name, spot, function(ok)
    goldAtStep(queue, index + 1, placed + (ok and 1 or 0), position, done)
  end)
end

--[[ The board's Buy / Sell buttons, one shape per side:

  <side>_label    the net offset as text, "+15%" / "-22%"
  <side>_good     1 / 0 / -1: better, neutral or worse for the player
  <side>_tooltip  the four sources, each coloured the same way

The two sides colour in OPPOSITE directions: a higher price is good when
selling and bad when buying.
]]

-- An offset as text, up to two decimals: -0.25 -> "-25%", 0.3125 -> "+31.25%".
-- Zero reads "+0%": neutral counts as positive.
local function change(offset)
  local p = offset * 100
  if math.abs(p) < 0.005 then return "+0%" end
  local text = string.gsub(string.format("%+.2f", p), "%.?0+$", "")
  return text .. "%"
end

-- -1, 0 or 1, judged on the same rounding change() prints.
local function sign(offset)
  if math.abs(offset * 100) < 0.005 then return 0 end
  return offset < 0 and -1 or 1
end

-- How an offset on `side` lands for the player: 1 better, 0 neutral, -1 worse.
local function good(offset, side)
  local s = sign(offset)
  return side == "buy" and -s or s
end

local GOOD_TAGS = {[-1] = "[E05050]", [0] = "[FFFFFF]", [1] = "[50C050]"}

local function tinted(offset, side)
  return GOOD_TAGS[good(offset, side)] .. change(offset) .. "[-]"
end

local HEADINGS = {
  buy = "Net change in final asking price of items and spells you buy.",
  sell = "Net change in final fetched price of items and spells you sell.",
}

local function sideTooltip(parts, side)
  return table.concat({
    HEADINGS[side],
    "",
    "--Breakdown--",
    "Default Global: " .. tinted(parts.standard[side], side),
    "Reputation Adjustment: " .. tinted(parts.faction[side], side),
    "Party Adjustment: " .. tinted(parts.party[side], side),
    "Merchant Adjustment: " .. tinted(parts.shop[side], side),
  }, "\n")
end

function priceSummary(args)
  if ECONOMY == nil then
    return {buy_label = "?", buy_good = 0, buy_tooltip = "No economy data.",
            sell_label = "?", sell_good = 0, sell_tooltip = "No economy data."}
  end
  local f = priceFactors(args)
  local out = {}
  for _, side in ipairs({"buy", "sell"}) do
    -- The label shows what the clamp lets through: never below -100%.
    local net = math.max(-1, f[side])
    out[side .. "_label"] = change(net)
    out[side .. "_good"] = good(net, side)
    out[side .. "_tooltip"] = sideTooltip(f.parts, side)
  end
  return out
end


-- ---------------------------------------------------------------- events ---

--[[ REP is the only thing Global persists. Everything else is either data
(regenerated by a sync) or lives on the objects themselves (a card's memo). ]]
function onSave()
  return JSON.encode({rep = REP})
end

function onLoad(script_state)
  if script_state and script_state ~= "" then
    local ok, saved = pcall(function() return JSON.decode(script_state) end)
    if ok and type(saved) == "table" and type(saved.rep) == "table" then
      REP = saved.rep
    end
  end

  -- Save & Play reloads the world, so re-render everything already on the
  -- table. Labeling is deliberate and lives in the bag taggers, so an
  -- unlabeled card stays blank on purpose.
  for _, obj in ipairs(getAllObjects()) do
    renderCard(obj)
    renderLootbox(obj)
  end
end

function onObjectSpawn(obj)
  renderCard(obj)
  renderLootbox(obj)
end

function onObjectLeaveContainer(container, obj)
  Wait.frames(function()
    renderCard(obj)
    renderLootbox(obj)
  end, 1)
end

-- ------------------------------------------------------------ lootboxes ---

--[[ A lootbox is an item that is CONSUMED to spawn a table of other items.

LOOTBOX is generated into this script by tools/sync_lootbox_data.py and keyed
by item NAME, which is what can be read off an object with no lookup. An item
only appears there when tiles.xlsx marks it type=consumable, subtype=lootbox,
so the presence of a name in the table IS the test for "openable".
]]
--[[ The Open button lives on the BACK of the tile, not the face.

A button is clickable only from the side it faces ("Buttons can not be clicked
from their back side" -- API, createButton). Hanging it under the tile and
rolling it 180 degrees about Z therefore does two jobs at once: it faces
downward, so a face-up box cannot be opened by a stray click, and its label
reads upright once the player presses F and the tile is flipped.

LIFT is negative for that reason -- position is relative to the object's
centre, so -LIFT is below the face.
]]
LOOTBOX_BUTTON = {
  LIFT = -0.1,
  ROLL = 180,
  FONT = 200,
  WIDTH = 1400,
  HEIGHT = 500,
  SCALE = 0.35,
  COLOR = {0.45, 0.33, 0.18},
  TEXT = {1, 0.95, 0.85},
}

function lootboxFor(obj)
  if obj == nil or LOOTBOX == nil then return nil end
  local name = obj.getName and plainName(obj.getName()) or nil
  if name == nil or name == "" then return nil end
  return LOOTBOX[name], name
end

-- Draw the Open button on a lootbox. Harmless on anything else.
function renderLootbox(obj)
  local loot = lootboxFor(obj)
  if loot == nil then return false end

  local B = LOOTBOX_BUTTON
  local k = LAYOUT.SHARPNESS
  obj.clearButtons()
  obj.createButton({
    click_function = "lootboxOpenClick", function_owner = Global,
    label = "Open", tooltip = "Flip the box to open it.",
    position = {0, B.LIFT, 0}, rotation = {0, 0, B.ROLL},
    scale = {B.SCALE / k, B.SCALE / k, B.SCALE / k},
    width = B.WIDTH * k, height = B.HEIGHT * k, font_size = B.FONT * k,
    color = B.COLOR, font_color = B.TEXT
  })
  return true
end

--[[ Open a lootbox: spawn its table, announce what came out, destroy the box.

The box is ALWAYS destroyed, even when nothing spawned -- a chest that survives
a failed roll would be reopenable for free.
]]
function lootboxOpenClick(obj, playerColor)
  local loot, name = lootboxFor(obj)
  if loot == nil then return end

  local who = Player[playerColor] and Player[playerColor].steam_name
  if who == nil or who == "" then who = tostring(playerColor) end

  local plan = rollSpawn(loot)
  local report = {spawned = {}, missing = {}, gold = 0}

  -- Hand finishSpawn the line to print instead of its card-style one, then
  -- destroy the box once everything is out.
  report.headline = who .. " opens " .. name .. ": "
  report.onDone = function()
    if obj ~= nil and not obj.isDestroyed() then obj.destruct() end
  end
  spawnPlanStep(obj, plan, 1, 0, report)
end

-- ------------------------------------------------- importer accessors ---

--[[ Data for the Card Importer bag, as STRINGS.

TTS sandboxes each script's tables: handing a table from Global.getVar() to
another object's script raises "Attempt to perform operations with resources
owned by different scripts". So the importer never reads EVENT_DATA or
CARD_SETS directly -- it calls these, which flatten to plain strings.

Format is one record per line, fields separated by \t:
  <set>\t<node id>\t<template>\t<title>
That is enough for the importer to build its buttons, pick each card's
template (by GMNotes) AND name each clone, without a second call per card.
Title goes last: the importer's pattern lets the last field hold anything.
]]
function cardIndexText()
  local out = {}
  for _, setName in ipairs(CARD_SETS and CARD_SET_ORDER or {}) do
    for _, id in ipairs(CARD_SETS[setName] or {}) do
      local node = EVENT_DATA[id]
      local title = (node and node.title ~= "" and node.title) or id
      local template = (node and node.template) or ""
      table.insert(out, setName .. "\t" .. id .. "\t" .. template .. "\t" .. title)
    end
  end

  --[[ Origins are cards too, so they ride the same index and the same
  importer. They form their own set, which gives the Card Importer bag its own
  button for them with no new machinery. ]]
  for _, id in ipairs(ORIGIN_ORDER or {}) do
    local o = ORIGIN_DATA and ORIGIN_DATA[id]
    local title = (o and o.name ~= "" and o.name) or id
    local template = (o and o.template) or ""
    table.insert(out, "origin\t" .. id .. "\t" .. template .. "\t" .. title)
  end

  return table.concat(out, "\n")
end

-- ------------------------------------------------- items: USE / cooldown ---

--[[ PLACEHOLDER. None of this is wired up yet -- see plans/auto_TODO.md.

The shape is settled, so this records it rather than leaving a blank:

  An interactive item is a `tool`. The importer stamps it with tags derived
  from its CSV numbers, and seeds memo READY:

    Item-Cooldown   has a recharge period.  memo "CD: 0"      (0 = ready)
    Item-Uses       has limited charges.    memo "Use: 5"     (0 = spent)

  An item can carry both, memo "CD: 0 | Use: 5".

  Global owns the rendering, exactly as it owns card rendering: onObjectSpawn /
  onLoad -> renderItem, and the USE button is function_owner = Global. That is
  what lets a balance change be a CSV edit + sync with no re-import.

  ITEM_INDEX below is how Global learns an item's cooldown DURATION: memo holds
  the live number, the index holds the maximum. Keyed by object name, which the
  importer sets from the CSV and which is already the key findInBag uses.

  Rules:
    - USE is drawn only when the item is AVAILABLE (CD == 0 and Use > 0)
    - when unavailable, draw a semi-transparent black overlay instead, so
      there is never a dead button
    - clicking USE sets CD to its duration and/or decrements Use by 1
    - the GM "end day" button decrements CD on every Item-Cooldown object it
      can find, floors at 0, and re-renders

  Known limits to design around:
    - getAllObjects() is table-level only, so cooldowns on items inside bags or
      decks will not tick. An item in a bag is arguably not in play.
    - uses are NOT rechargeable: at 0 the item stays greyed out forever.
]]

-- Cooldown/uses maxima by item name. Populated by the item sync once the
-- rendering is built; empty until then.
ITEM_INDEX = ITEM_INDEX or {}

-- Parse "CD: 0 | Use: 5" into numbers. Missing parts come back nil.
function itemState(obj)
  local memo = obj.memo or ""
  local cd = tonumber(string.match(memo, "CD:%s*(%d+)"))
  local uses = tonumber(string.match(memo, "Use:%s*(%d+)"))
  return cd, uses
end

-- True when the item can be used right now.
function itemAvailable(obj)
  local cd, uses = itemState(obj)
  if cd ~= nil and cd > 0 then return false end
  if uses ~= nil and uses <= 0 then return false end
  return true
end

-- Draw an item's USE button / greyed overlay. NOT CALLED YET.
function renderItem(obj)
  if obj == nil then return false end
  if not (obj.hasTag and (obj.hasTag("Item-Cooldown") or obj.hasTag("Item-Uses"))) then
    return false
  end
  -- TODO(plans/auto_TODO.md): draw USE when itemAvailable(obj), otherwise the
  -- semi-transparent black overlay.
  return false
end

-- Spend a use and/or start the cooldown. NOT WIRED TO A BUTTON YET.
function itemUseClick(obj)
  -- TODO(plans/auto_TODO.md): set CD to ITEM_INDEX[name].cooldown, decrement
  -- Use by 1, write memo back, re-render.
end

-- GM "end day": tick every cooldown down by one. NOT WIRED TO A BUTTON YET.
function endDay()
  -- TODO(plans/auto_TODO.md): for each object with Item-Cooldown, decrement CD
  -- (floor 0), write memo back, re-render.
end
