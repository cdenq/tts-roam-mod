# ROAM

Co-op RPG board game set in the Root universe, built in Tabletop Simulator.
Content is authored in spreadsheets, compiled to Lua by Python syncs, and
pushed into TTS through the VS Code "Tabletop Simulator Lua" extension.

- design (settled) -> `internal/agent/taxonomy.md`
- open work -> `internal/plans/auto_TODO.md`
- art / image source -> Google Drive link in `assets/README.txt`

# Setup

- VS Code with the TTS Editor extension
- open TTS, load the save
- `Ctrl+Alt+L` once to pull objects into `.tts/objects/`
- `Ctrl+Shift+P` -> `TTS Editor: Show Output` for the in-game error log
- Python 3 + `openpyxl` (syncs read xlsx); `pillow` + `numpy` for map tile art

# Directory

```
ROAM/
├── internal/                 # gitignored working docs + art sources
│   ├── agent/
│   │   ├── taxonomy.md       # settled game design
│   │   └── *_artguide.md     # art specs for agents (map tiles + landmarks, meeples)
│   ├── plans/
│   │   └── auto_TODO.md      # open work; read before changes
│   └── asset_generation/     # Luminari font, meeples_clean.psd (meeple source), meeple_shapes/ (generated), old meeple art
├── assets/
│   ├── README.txt            # link to art folder
│   ├── maptiles/             # generated: <region>/ tiles, backs/, manifest.csv
│   └── meeples/              # generated: base/ advanced/ custom/ special/ character/ denizens/, manifest.csv
├── .tts/                     # MANAGED BY EXTENSION, do not edit
│   ├── bundled/              # ignore
│   └── objects/              # staging; OVERWRITTEN by Ctrl+Alt+L
└── tts_envs/                 # EDIT IN HERE
    ├── data/                 # every authored dataset
    │   ├── cards.xlsx        # scenario_intro, generic, scenario_options, scenario_outcomes
    │   ├── origins.xlsx      # origins
    │   ├── tiles.xlsx        # items, skills, statuses, lootbox_table, _values
    │   ├── tokens.xlsx       # tokens, landmarks, factions, loot_table, stats_table, _values
    │   ├── shops.xlsx        # shops, stock
    │   ├── asset_variables.csv # art knobs for build_map_tiles.py + build_gems.py + build_cards.py + build_landmarks.py + meeple colours
    │   └── gold_variables.csv # every hand-authored gold number
    ├── src/                  # hand-written Lua
    │   ├── global.lua        # cards, rendering, spawning, rep, pricing
    │   ├── card_importer.lua # Card Importer bag (4b808d)
    │   ├── tiletoken_importer.lua # TileToken Importer bag (85a721)
    │   ├── merchant_board.lua # Merchant Board, nicknamed "Shop" (ecde97)
    │   ├── change_converter.lua # Change Converter bag (305b4a)
    │   ├── maptile_manager.lua # Maptile Manager bag (b77050)
    │   └── lib/template_import.lua # shared, pasted into both importers
    ├── generated/            # build output, reference/diffing only
    ├── tools/                # Python syncs + offline Lua test harness
    │   ├── datasets.py       # where every sheet lives; edit here to move one
    │   ├── spawn_cells.py    # spawn-cell grammar + staged_path()
    │   ├── lua_inline.py     # pastes src/lib/ into object scripts
    │   ├── refresh_master_reload.py, debug.py # write master_reload.lua / debug.lua
    │   ├── sync/sync_*.py    # xlsx -> Lua, one per target, run by master_sync.cmd
    │   ├── build/            # art generators (manual, not in master_sync)
    │   │   ├── build_map_tiles.py, build_gems.py, build_cards.py, build_landmarks.py
    │   │   ├── build_meeple_shapes.py, build_meeples.py # meeple PSD -> shapes -> coloured PNGs
    │   │   ├── build_insects.py  # code-drawn enemy insects -> the PSD's Enemy group
    │   │   ├── meeple_brush.py, meeple_smooth.py # brush-pen details, clean outlines
    │   │   ├── meeple_split_eyes.py # gives a PSD layer's eyes their own colour slots (iris, pupil)
    │   │   └── scaffold_maptile_xlsx.py # adds a maptile.xlsx row per generated image
    │   ├── test_*.lua        # offline harness, stubs TTS API
    │   └── bin/lua54.exe     # harness interpreter (5.4; TTS is 5.2)
    ├── master_sync.cmd       # rebuild everything + run tests
    ├── ship.sh               # Git Bash: git add . + commit + push (`./tts_envs/ship.sh "msg"`)
    ├── master_reload.lua     # generated; Execute Code -> live-apply Global
    └── debug.lua             # generated; Execute Code -> dump what Global sees
```

Never hand-edit `generated/`, `.tts/objects/`, `master_reload.lua`, `debug.lua`.

## Where to edit

| change | file |
| --- | --- |
| event cards, generic (art-only) cards | `data/cards.xlsx` |
| origin cards | `data/origins.xlsx` |
| items / skills / statuses | `data/tiles.xlsx` |
| lootbox contents | `data/tiles.xlsx` `lootbox_table` |
| meeples, factions, enemy loot | `data/tokens.xlsx` |
| merchants + stock | `data/shops.xlsx` |
| any gold number | `data/gold_variables.csv` |
| dropdown vocab | `_values` sheet of the workbook |
| map tile URLs, biome text, draw odds | `data/maptile.xlsx` |
| map tile + gem + landmark art, meeple colours | `data/asset_variables.csv` |
| meeple shapes (outline + line work) | `internal/asset_generation/meeples_clean.psd` |
| card logic / rendering | `src/global.lua` |
| object behaviour | `src/<object>.lua` |

# Workflow

1. edit `data/` or `src/`
2. `./tts_envs/master_sync.cmd` — runs every sync, then tests
3. push (table below)
4. check in game

| changed | push with |
| --- | --- |
| `src/global.lua`, `cards.xlsx`, `origins.xlsx`, lootboxes | focus `master_reload.lua` + `Ctrl+Shift+E` |
| one object's script | focus its `.tts/objects/*.lua` -> `TTS Editor: Update Object` |
| both, or unsure | `Ctrl+Alt+S` Save and Play (save the game first) |

- `master_reload.lua` = built Global + `onLoad()` call. Applies to the live
  table, no world reload, hand-made table changes survive. Fastest loop
- Execute Code runs in Global's scope only. Object scripts have no live-apply;
  `Update Object` or Save and Play
- `Ctrl+S` is not a push

## Push order matters

- `Ctrl+Alt+L` **wipes `.tts/objects/` and refills it from the game**,
  clobbering anything synced but not pushed
- **sync -> push.** Never sync -> pull
- pull only to pick up in-game edits, then re-sync
- an object with an **empty script is invisible to the extension**. To
  bootstrap a new scripted object: give it a one-line script in TTS by hand,
  `Ctrl+Alt+L`, add its sync, run sync
- staged filenames are `<nickname>.<guid>.lua`; renaming in game renames the
  file. Syncs resolve by GUID (`staged_path`), never by name

## master_sync.cmd order

- `sync_gold` first — writes `base_gold`/`spawngold` INTO `data/`
- `sync_origin_text` — rewrites "Gain N gold." prose to match `spawngold`
- `sync_events_data` — rebuilds Global from `src/global.lua` + cards.xlsx
- `sync_card_importer`, `sync_items_data`, `sync_lootbox_data`,
  `sync_landmark_data`, `sync_origins_data`, `sync_change_converter`, `sync_merchant_board`
- `sync_gold --splice-only` — re-splices `ECONOMY` (events sync wiped it)
- `refresh_master_reload`, `debug`, then `test_change_converter.lua`, `test_events.lua`
- any failure stops the chain

# Offline Generation

Map tile images. Run in Git Bash from the repo root. Not part of `master_sync.cmd`.

```bash
cd "/c/Users/Owner/Data/D/Board Games/ROAM/tts_envs"
python tools/build/build_map_tiles.py --region forest --shape back cross tee straight corner deadend --density 1-4 --variants 1
```

| flag | sets | values | omitted = |
| --- | --- | --- | --- |
| `--region` | which regions | any region name in `asset_variables.csv`, e.g. `forest` `marsh` `settlement` (space-separated) | every region |
| `--shape` | structural variants | `back` (the deck backs of the chosen regions) `cross` `tee` `straight` `corner` `deadend` `none`, or one orientation e.g. `corner_ES` | region's `patterns` + its deck's `back` |
| `--density` | density range | `3`, `1-4`, `"1\|3\|5"` (quote a list) | region's `densities` |
| `--variants` | looks per orientation | `1`, `2`, `3`… (draws `_1` to `_N`) | region's `variants` |
| `--prune` | cleanup | — | off |

- flags override `data/asset_variables.csv` for this run only
- output: `assets/maptiles/<region>/<region>_<shape>_<edges><n>_d<density>.png`,
  `assets/maptiles/backs/<deck>_back.png` (5, one per event deck); rows upserted into `manifest.csv`
  (its `file` column is the path under `assets/maptiles/`)
- nothing is deleted unless `--prune`: removes images the CSV (no flags) doesn't describe
- one image ≈ 1 s; full CSV run (27 regions × 15 shapes × densities 1-3 + backs)
  ≈ 1,240 images ≈ 20 min -- prefer `--region` while iterating

Examples:

```bash
python tools/build/build_map_tiles.py                                         # everything the CSV describes
python tools/build/build_map_tiles.py --region forest --shape back            # just the forest back
python tools/build/build_map_tiles.py --region forest --shape corner_ES --density 1-5
python tools/build/build_map_tiles.py --region city plains --shape tee --variants 2
python tools/build/build_map_tiles.py --prune                                 # rebuild all + clear leftovers
```

Card fronts + backs (one pair per gem in `card.gems`, see [Card frame art](#card-frame-art)):

```bash
cd "/c/Users/Owner/Data/D/Board Games/ROAM/tts_envs"
python tools/build/build_gems.py     # only if gem art changed; cards read assets/gems/
python tools/build/build_cards.py    # every gem in card.gems + every deck_* -> assets/cards/<name>_front.png + _back.png
python tools/build/build_cards.py origin   # one card, others untouched
```

Landmark standees (see [Landmark art](#landmark-art)):

```bash
cd "/c/Users/Owner/Data/D/Board Games/ROAM/tts_envs"
python tools/build/build_landmarks.py <landmark ..> --size <1-4 ..>
```

| arg | sets | values | omitted = |
| --- | --- | --- | --- |
| `landmark` | which landmark types | any `landmark_size` key: `guildhall` `building` `cave` `tree` `mineral_node` `fishing_spot` `herb` `tracks` `marquise_keep` `eyrie_roost` `otter_tradepost` `knave_camp` `alliance_burrow` `lizard_garden` `guild_tower` `caravan` `beehive` `shrine` `warehouse` `bank` `eyrie_tower` `marquise_barracks` `alliance_barracks` `otter_barracks` (space-separated) | every landmark |
| `--size` | which sizes | `1` `2` `3` `4` (space-separated) | every size with a width in the CSV |
| `--prune` | cleanup | — | off |

```bash
python tools/build/build_landmarks.py                         # everything the CSV describes (~20 s)
python tools/build/build_landmarks.py building --size 4       # just the capital hall
python tools/build/build_landmarks.py cave guildhall          # all sizes of two landmarks
python tools/build/build_landmarks.py --prune                 # rebuild all + clear leftovers
```

Meeples (see [Meeple art](#meeple-art)):

```bash
cd "/c/Users/Owner/Data/D/Board Games/ROAM/tts_envs"
python tools/build/build_insects.py                        # redraw the enemy insects into meeples_clean.psd (~35 s); then the two below
python tools/build/build_meeple_shapes.py                  # after editing meeples_clean.psd (all layers, ~45 s)
python tools/build/build_meeple_shapes.py denizen_beaver   # just the layers you changed
python tools/build/build_meeples.py                        # after any meeple_* row change (~10 s)
python tools/build/build_meeples.py custom/custom_beaver   # one PNG; manifest + preview still cover all
python tools/build/build_meeples.py --prune                # also delete PNGs no meeple_skin row describes
```

# Systems

## Importers (shared)

Card Importer and TileToken Importer both run `src/lib/template_import.lua`:
clone a template from inside the bag per data row, stamp fields, drop clone in
the bag.

- each imported sheet has a `template` column = **GMNotes** of a template
  object in the bag. Name of the template object does not matter
- one bag can hold many templates; each row picks one
- templates are never consumed
- tag every template `Template` by hand, or `Take out all` takes it too.
  Importer strips the tag from clones
- importer checks all needed templates exist before cloning; missing = red
  chat error, nothing imported
- sync fails on a blank template or one equal to an object's GMNotes
- **import is append-only** — clicking twice imports twice
- buttons are generated from the data: new `set`/`region` = new button after sync
  - Card Importer: card sets | `Import all`, `Take out all`
  - TileToken Importer: token sets | tile sets | `Import all tokens`,
    `Import all tiles`, `Take out all`
  - geometry in each script's `PANEL` table, object-local units x bag scale

## Spawning

- generic core in `global.lua`: `rollSpawn`, `spawnFrom`, `spawnCopyFromBag`
- consumers: event outcomes, origins, lootboxes, token loot, merchant restock
- runtime bags (`SPAWN_SOURCES`): items `c98e54`, status `72ed8a`,
  meeple `ccfa1b`; gold `f0d3ab`
- importers do NOT fill these. Move imported tiles/tokens into the runtime
  bag by hand (intended)
- lookup is by exact object **name** (`findInBag`)
- spawn-cell grammar, shared everywhere (`tools/spawn_cells.py`):

  | cell | rolls |
  | --- | --- |
  | `Ration\|Rope\|Ration` | Ration 2/3, Rope 1/3 (repeats raise odds) |
  | `Ration\|Rope\| \|` | Ration 1/4, Rope 1/4, nothing 2/4 |
  | `!Key\|!Key\|Box` | Key 2/3 TAKEN from bag (unique), Box 1/3 cloned |

- `spawngold`: flat (`5`) or range (`1-5`); blank = none
- columns `spawn1..5`, `spawnstatus1..3`, `spawnmeepleN`, `spawnlandmark1..3`, `spawncard`; one roll per cell
- `spawnlandmarkN`: a landmark from bag `6a6425` by exact name, checked against tokens.xlsx `landmarks`
- `spawncard` (scenario_outcomes): a card from bag `32e095` by exact name; same grammar (`A|B`, `!` = take
  the card out instead of cloning it). Not checked at sync: the names live only in that bag
- every name checked against `tiles.xlsx` / `tokens.xlsx` at sync

## Event cards (cards.xlsx)

Card Importer `4b808d`. Cards carry only an id; Global renders and handles
every click.

| sheet | one row per | key |
| --- | --- | --- |
| `scenario_intro` | card: `template`, `region`, `title`, `flavor`, `face_url`, `back_url` | `scenario_id` (`EV1`) |
| `generic` | art-only card: `template`, `set` (= region), `title`, `description` (= flavor), `face_url`, `back_url`; no options needed | `id` (`CB1`) |
| `scenario_options` | button: `label`, `tooltip`, `outcomes` | `scenario_id` + `option` |
| `scenario_outcomes` | landing: `title`, `flavor`, `effect`, spawns | `scenario_id` + `outcome_key` |

- node id = `<scenario_id>_<outcome_key>` (`EV1_pay_through`), built by sync
- `outcomes` = `|`-separated keys, repeats raise odds
- `region` = the event deck (`settlement` `woodland` `opencountry` `waterside`
  `scarred`, see `internal/agent/taxonomy.md` "Event decks"): one importer button per
  deck, and the biomes that draw from it. Map-tile biomes (`forest`, `marsh`...)
  are a different list
- `face_url` / `back_url`: replace the template's art at import (empty = keep
  it). `generic` rows point at `assets/cards/` on GitHub
  (`https://raw.githubusercontent.com/cdenq/tts-roam-mod/main/assets/cards/<file>`)
- `generic` rows use `set` `generic` -> one importer button for the set
- GMNotes = `scenario_id` (permanent); memo = current node (empty = intro)
- object name is cosmetic; GMNotes is authoritative
- `EVENT_DATA` lives in Global -> text fix = edit, sync, push; cards on the
  table re-render without re-import
- push BOTH Global and the bag after a scenario change (or `Ctrl+Alt+S`)
- sync fails on: unknown `scenario_id`, duplicate key, option -> missing
  outcome, intro with no options (generic rows exempt), tab/newline in a
  title, whitespace in a url. Warns on
  unreachable outcomes
- cards **merge into a deck on contact** (absorbed one is destroyed);
  importer locks the template and clones off to the side
- bag reads Global's card list as flattened text (`cardIndexText()`) because
  TTS sandboxes each script's tables

## Origins

- `origins.xlsx`, one row per origin card; ids `O…` (must not collide with `EV…`)
- renders like an event card; one button spawns everything it grants
  (`spawn*`, `spawngold`, `spawnmeeple1`); card is NOT consumed
- `gold_tier` -> `spawngold` computed by `sync_gold`; prose rewritten to match

## Items (tiles)

TileToken Importer `85a721`. Data is inlined into the bag's own script.

- sheets `items`, `skills`, `statuses` share headers, read as one table
- xlsx, not csv: `_values` drives dropdowns AND sync validation. Add a row
  there to extend a vocabulary
- `name` is the key; must be unique across tiles and tokens
- `tts_type` = TTS object (`tile` has a back, `token` does not). `type` =
  game kind

| column | values |
| --- | --- |
| `type` | weapon, armor, consumable, goods, skill |
| `subtype` | weapon: category; armor: weight/trinket/misc; consumable: food, drink, potion, bandage, repair kit, rune, augment, lootbox; goods: treasure, quest, junk, material, misc, contraband; skill: profession, general |
| `subsubtype` | weapon: variant (`1H Axe`, `2H Fire Heart`); armor: slot; material: kind (`ore`); profession skill: gathering/crafting |
| `tier` | 0–3 |

- **derived, never authored** (sheet formulas + `sync_items_data.py`):
  `stat`, `damage_range`, `damage_type`, `base_gold`, `Item-Cooldown` /
  `Item-Uses` tags, `Contraband` tag (subtype `contraband`), memo seed
- weapon `subsubtype` must start `1H`/`2H`; hands are read from it
- `cooldown` / `uses`: any item may carry them. Memo seed `CD: 0 | Use: 5`
  (CD counts time remaining; fresh = 0)
- `description` composed from fields + `effect`/`flavor`; `\n` = line break
  (`/n` caught as typo)
- `gmnotes` -> GMNotes, `memo` -> memo. On contraband = the buyer's
  `faction_id` (required; sync fails otherwise)
- blank `image_front`/`image_back` = inherit template image; tokens ignore back
- clone keeps template thickness/scale/tint
- templates: `TEMPLATE_TILE` (Custom Tile), `TEMPLATE_TOKEN` (Custom Token);
  one template cannot serve both tile and token rows
- USE button / grey-out / end-day: **not built** (see TODO)

## Lootboxes

- item row: `type=consumable`, `subtype=lootbox`
- contents: one row per box on `tiles.xlsx` `lootbox_table`, keyed by
  `item_id` + `name`
- standard spawn cells; `gold_adjust` `1` = `spawngold` computed by
  `sync_gold`, `0` = hand-owned (left as typed)
- may contain another lootbox
- table lives in Global (Global draws the Open button)

## Tokens (meeples)

People, not things. Import through TileToken Importer, appended to the same
data (so names must not clash with tiles).

| column | notes |
| --- | --- |
| `token_id` | `TK1`…, prefilled; row is real once it has a `name` |
| `role` | shop, quest, flavor, combat |
| `subtype` | from `sub_<role>` on `_values`; blank for shop/flavor |
| `affiliation` | neutral, enemy, friendly |
| `faction` | `faction_id` from `factions`; blank = none |
| `tier` | 0–3; on shops = settlement size |
| `exp` | exp worth |
| `loot_table` | `loot_id`; blank on friendly (cannot be killed) |
| `stats_table` | `stats_id`; combat only. Draft, nothing reads it |
| `gmnotes` | on a shop token = `shop_id` |

- description generated: affiliation/role/subtype, faction, tier/exp,
  effect, flavor
- new role with subtypes = new `sub_<role>` column + matching named range
- `factions`: `faction_id`, `name`, `default_rep` (starting rep), `short` (name used in effect text: `Party gains 1 Dynasty reputation`)
- `loot_table`: same columns/grammar as `lootbox_table`

### Landmarks

`tokens.xlsx` sheet `landmarks`: places on the map (caves, shrines, camps).
Same bag, importer and name space as `tokens` -- a name may not repeat across
the two sheets.

| column | notes |
| --- | --- |
| `landmark_id` | `LM1`…, prefilled; a row is real once it has a `name` |
| `template` | GMNotes of the template in the bag (prefilled `landmark_template`) |
| `tts_type` | always `token` |
| `set` | importer button (prefilled `landmarks`) |
| `name` | in-game name; `findInBag` key; usable in `spawnmeepleN` |
| `faction` | `faction_id`; blank = `none` |
| `tier` | 0–3 |
| `effect` | composed into the description |
| `gmnotes` | -> GMNotes. The landmark's KIND (`cave`, `fishing_node`), shared by landmarks that behave alike; keys `maptile.xlsx` `landmark_table` |
| `image_front` | the token's face |

- imports as role `landmark`; description: `Landmark` / faction / `Tier N` / effect
- behaviour: Global `renderLandmark` (on spawn, reload, leaving a bag, and after a spawn stamp) looks the GMNotes kind
  up in `LANDMARK_DATA` and draws its action buttons. Memo is read, never written. No row = left alone
- like tokens, move imported landmarks into the meeple bag `ccfa1b` by hand

## Shops (Merchant Board)

Board `ecde97` ("Shop"). `shops.xlsx` inlined into the board by
`sync_merchant_board.py`.

- drop a merchant meeple in the slot zone; its GMNotes = `shop_id`
- shop `tier` + `faction` come from that meeple's token row (exactly one
  per shop)
- `shops`: `shop_id`, `shop_role_display` (blank = placeholder row),
  `adjustment_buy`, `adjustment_sell`, `contraband_buyer` (`yes` / blank)
- `stock`: `shop_id`, `item` (name or spawn cell), `qty` (`2`, `1-3`;
  `0-1` = sometimes absent)
- 16 slots (2x8). Restock rolls every row, fills in sheet order, extras
  dropped. Spammable, stateless
- Zone A = buying (buy price), Zone B = offering (sell price). Reconcile when
  A <= B, change paid in coins
- Zone B refusals (named, left in place): ordinary merchants refuse
  `Contraband`-tagged items; a contraband buyer takes only gold + contraband
  whose GMNotes = its faction
- `TBD:<tier> <kind>` in `stock` = placeholder; warned, never shown
- prices: `base x pct x rep x party x adjustment` (buy and sell separate);
  rep and pricing live in Global
- zones repositioned on board drop, not polled

## Maptile Manager

Bag `b77050`. Draws overworld tiles from the generated art (Offline Generation)
once their images are uploaded. Data: `data/maptile.xlsx`, inlined by
`tools/sync/sync_maptile_manager.py` (in `master_sync.cmd`).

Panel:

```
[ Draw ]  [ Draw specific ]  [ Spawn guildhall ]
             [ Advanced ]
[ Region ]   [ Biome ]          (Advanced toggles this grid; open/closed is saved)
[ Pattern ]  [ Orientation ]
[ Density ]  [ Force: Off ]
[ Force: N ] [ Force: E ] [ Force: S ] [ Force: W ]
```

- panel geometry (`PANEL`) is in world units; buttons cancel the bag's uneven scale, so text is
  never stretched, and sit just above the bag's base

- left-click a setting = next, right-click = back; every setting starts `Random`; Force starts Off, no edges
- the `↺` beside each setting puts it back to `Random` (Region also resets Biome, Pattern also
  resets Orientation; ignored while Force overrides Pattern/Orientation)
- Biome only offers the chosen deck's biomes (locked to Random while Deck is
  Random); Orientation only the chosen pattern's rotations (locked while
  Pattern is Random). Changing Deck/Pattern resets the dependent one
- Orientation label shows a box-drawing glyph of the roads (`┼`, `├`, ...)
- `Force: On/Off` overrides Pattern + Orientation (greyed, clicks ignored). Each `Force: N/E/S/W`
  edge has three states: left-click = **must** have a road there (green), right-click = must
  **not** (red), the same click again = either way (blue). The other click switches green <-> red.
  All grey while Force is off, but still clickable
- Draw specific picks evenly among every pattern+rotation that fits (green N + E: corner NE, tees
  NES and NEW, the cross; red N, E, S + green W: only the dead end open to the W), then rolls
  deck/biome/density as usual. Nothing fits = a message, no tile. Draw ignores Force. Saved
- the edge letter is the tile's own edge: `N` = a road leaving the new tile's north side
- the Deck setting is labelled `Region`. Each setting's tooltip lists its options, or says
  what unlocks / overrides it
- Draw = everything Random. Draw specific = rolls only what is still Random
- roll order deck -> biome -> pattern -> orientation -> density, each from its
  `weights` pool, so a deck with more biomes is not drawn more. Free rolls:
  the same tile can come twice
- settings survive save/load
- a biome on the `tiers` sheet (`city`) rolls a hidden tier after it is drawn (`tier:<biome>`
  weights). The tier only picks the tile's GMNotes biome (`settlement` / `town` / `city`) and the
  tileset whose images it uses (same names: `settlement` / `town` / `city`); it is stored and shown nowhere
- the guildhall (starter tile) is never drawn and never offered by Biome. Spawn guildhall rolls a
  random guildhall image from `guildhall:pattern`, `guildhall:density` and optional
  `guildhall:orientation:<pattern>` (else `orientation:<pattern>`)

A drawn tile is a copy of the bag's template (Custom Tile, GMNotes
`maptile_template`, tagged `Template`), placed beside the bag (`SPAWN`):

| field | value |
| --- | --- |
| name | the biome name from `biome_descriptions`, e.g. `Deepwood` |
| description | `[effect]`, blank line, `"flavor"` from `biome_descriptions` |
| GMNotes | biome id, e.g. `forest` -- every lookup keys on it |
| memo | `d=<density>\|explore=<left>\|rendered=<0/1>` |
| images | front = rolled image url, back = its deck's back url. Spawns face down (`SPAWN.ROTATION` z = 180) |
| tags | `Maptile`, `Region:<deck>`, `Biome:<biome>` (ids, e.g. `Region:woodland`, `Biome:forest`; a tiered city is tagged by its GMNotes, `Biome:town`) |

Buttons on the tile (owned by the manager; re-rendered on load from GMNotes + memo):
- `Explore: N` -- N from the `density` sheet. Click = swap it for four choices (spends nothing); picking one
  spends 1 and brings `Explore: N-1` back (gone at 0). Each choice broadcasts one short line: the spawned landmark's name, `Event!`, or `Nothing...` (`EXPLORE_SAYS` in `src/maptile_manager.lua`; the reason for a data miss goes to `log`):
  - `Resources` / `Landmarks` -- roll the biome's `exploration` weights for that category; a `landmark`
    outcome clones one from its pool out of bag `6a6425` onto the tile's centre, memo stamped from
    `explore_outcomes` (GMNotes left as the landmark's own kind)
  - `Experiences` -- takes the top card of the tile's region bag (`EVENT_BAGS` in `src/maptile_manager.lua`:
    woodland `9b1bd8`, waterside `7abfaf`, opencountry `12d32e`, settlement `3d7a98`, scarred `3e737b`) face up
    onto the tile. Bags hold single cards, never decks; never shuffled by script; a drawn card leaves its bag
  - `Wander` -- one of the other three at random
  - a fifth choice on biomes listed on `explore_special` (guildhall: `Eat`) -- spends an explore and broadcasts `Maptile special action used.`; Wander never picks it
  - untouched for 5 s (`EXPLORE.CHOICE_TIMEOUT`), the choices close and `Explore: N` returns. Not saved: a reload shows `Explore: N` again
- `?` -- toggles the tile's hover tooltip (name + description). Tiles spawn with it off; grey text =
  off, black = on. State is the object's own `tooltip`, saved by TTS, not the memo
- `Render` -- "Lock-in this maptile as the explored part of the world." Once (memo `rendered=1` removes the button); locks the tile (`setLock(true)`, saved with it); takes the region's top event card (as Experiences) and spawns the biome's `maptile_table` row onto the tile's centre, each slot's copy stamped from its `_gmnotes` / `_memo` columns, through Global
  (`Global.call("spawnFromFor", {guid, spawn})` -> `spawnFrom`, same bags as every other spawn)

### `data/maptile.xlsx`

| sheet | one row per | columns |
| --- | --- | --- |
| `settlement` `woodland` `opencountry` `waterside` `scarred` | image of that deck | `biome` `pattern` `orientation` `density` `image` `file` **`url`** |
| `backs` | deck | `deck` `name` `image` `file` **`url`** |
| `biome_descriptions` | biome | `biome` `deck` `name` `effect` `flavor` |
| `maptile_table` | biome (GMNotes) | `gmnotes` + spawn cells (`spawnN`, `spawnmeepleN`, `spawnlandmark1..3`, `spawngold`); names checked against tiles/tokens. Landmarks go in `spawnlandmarkN` (bag `6a6425`), not `spawnmeepleN` -- the sync fails on a landmark in a meeple cell | `<spawncol>_gmnotes` / `<spawncol>_memo` (e.g. `spawnlandmark1_memo`) stamp that slot's copy; blank = keep its own, `{biome}` = the row's biome. A stamp on an empty spawn column fails the sync |
| `explore_outcomes` | Explore outcome | `outcome` `category` (`resource` / `poi` / `event`) `kind` (`landmark` / `nothing`) `name` `landmarks` (pool, `a\|b\|b`; checked against tokens.xlsx `landmarks`) `gmnotes` `memo` (stamped on the spawned landmark, blank = leave; `{biome}` = the tile's biome). `flavor` is no longer read (explores broadcast short fixed lines) |
| `exploration` | biome | `biome` + one weight column per resource / poi outcome (`fishing` ... `resource_none`, `camp` ... `poi_none`); relative odds within each category, blank/0 = never. A new outcome = a new row there + a new column here; weight on a landmark outcome with no landmarks fails the sync |
| `explore_special` | biome with a fifth Explore choice | `biome` `label` (button text) `tooltip` -- hand-filled; most biomes have no row. `flavor` is no longer read |
| `landmark_table` | landmark kind (GMNotes) | `gmnotes` (lowercase snake_case) `actions` (`inspect\|enter`: keys of `LANDMARK_ACTIONS` in `src/global.lua`, which hold each action's label + click function) `notes`. `sync_landmark_data.py` -> `LANDMARK_DATA` in Global; warns on a kind no landmark carries, or one carried with no row. New kind = a row; new action = code |
| `tiers` | biome + tier | `biome` `tier` `gmnotes` `tileset` -- gmnotes = the biome the tile becomes (needs its own `biome_descriptions` row, kept out of the pools); tileset = whose images it uses; a tileset that is not a biome has image rows only |
| `density` | density stage | `density` `explorations` |
| `weights` | roll | `param` `pool` -- `deck`, `biome:<deck>`, `pattern`, `orientation:<pattern>`, `density`, `guildhall:*`, `tier:<biome>`; repeat an entry to make it likelier (`1\|1\|2\|2\|3`) |

- rows come from `python tools/build/scaffold_maptile_xlsx.py` (one per generated
  image). Re-run after generating new art: adds rows, never overwrites a filled cell
- only images with a `url` can be drawn; the sync counts the rest
- `url` = `https://raw.githubusercontent.com/cdenq/tts-roam-mod/main/assets/maptiles/` + `file`.
  Push the PNG before it can load in game
- Google Drive: a share link (`/file/d/<id>/view`) is rewritten to
  `uc?export=download&id=<id>` automatically. The file must be shared "anyone with the link"
- offline test: `tts_envs/tools/bin/lua54.exe tts_envs/tools/test_maptile_manager.lua ".tts/objects/Maptile Manager.b77050.lua"`

## Gold

- `gold_variables.csv` is the only hand-authored gold. Everything is a
  fraction of `gold_anchor`
- `sync_gold.py` writes INTO `data/` (`base_gold`, `spawngold`). Hand-typed
  values that disagree are kept as `OVERRIDE kept`
- **after changing the gold numbers, run `python tools/sync/sync_gold.py --force`**
  (a stale value looks like a hand override)
- Change Converter `305b4a`: coins = objects tagged `Gold`, GMNotes = value.
  Cash-up (fewest coins) / Break-down. Hand-written, no data

## Map tile art

Code-drawn storybook tiles. Manual step, not part of `master_sync.cmd`.

- how to run: see [Offline Generation](#offline-generation)
- writes `assets/maptiles/<region>/<region>_<pattern>_<edges><n>_d<density>.png`
  (`forest/forest_tee_NES1_d3.png`), `assets/maptiles/backs/<deck>_back.png`,
  `assets/maptiles/manifest.csv`
- knobs in `data/asset_variables.csv` (`group,key,value,notes`):
  - `global` rows: size, supersample, seed, palette, path/frame sizes,
    `back_font` (path from repo root, `internal/asset_generation/Luminari-Regular.ttf`), `back_gem_size`, `density_scale`,
    and feature/wall tuning: `river_anchor`, `river_width`, `canyon_width`, `lake_land`, `wharf_land`, `pond_size`,
    `falls_size`, `pit_size`, `pool_count`/`pool_size`, `mud_count`/`mud_size`,
    `spring_count`/`spring_size`, `reed_size`, `field_width`/`field_height`,
    `menhir_spacing`/`menhir_size`, `stake_spacing`/`stake_size` (sizes are
    `lo-hi` in design units; a tile is 1024 wide)
  - one block per region: `variants`, `patterns`, `densities`, `ground`,
    `deck`, `clearing`, `spacing`, `fields`, `grass`, `icons`
- density = how crowded the scatter is, stages d1 (sparse) .. d5 (dense).
  Stage multiplies the region's `spacing` by its `density_scale` entry
  (d3 = 1.0). Seeds ignore density: same roads, different tree count
- backs are per EVENT DECK, not per region: each region's `deck` (settlement,
  woodland, opencountry, waterside, scarred) picks one. A `deck_<id>` group
  holds `name` (ribbon text, exactly as typed), `gem` (from `assets/gems/`)
  and `colour`. New deck = new `deck_<id>` group + point regions at it
  - new region = copy a block, rename the group. `gem`/`gem_colour` are
    reserved for gems, not regions
- regions: forest, plains, city, mountain, guildhall, riverside, marsh, hills,
  blossomgrove, mushroomhollow, deepwood, heath, ashland, ruins, quarry,
  lumbercamp, farmstead, orchard, settlement, town, lakeshore, briarthicket,
  wildflowermeadow, canyon, waterfallcliffs, standingstones, battlefield, hotsprings, lilypond,
  otterwharf, drownedwood, watermill, beaverdam, barrows, slagworks, blightwood, cliffside,
  coldmountain, hillcentral, battlefieldmountain, battlefieldwaterside
- `icons` = `painter:weight:lo-hi` joined by `|`. Painters: tree, pine, bush,
  mountain, house, tent, blossom, fruit, oak, heather, deadtree, charred,
  stump, rock, hill, reeds, mushroom, ruinwall, column, crane, logpile,
  haystack, gnarled, briar, flowers, menhir, cart, spears, warbanner, townhouse, coldpeak, coldpine,
  blightcap, blighttree, mangrove, barrow, cave, furnace, slagheap, barrel, crate, sword, helmet,
  catapult (also: stake = palisade;
  wallblock + tower = stone wall; guildhall, windmill, statue =
  centrepieces; barge, raft, lodge, watermill = placed by a feature, afloat, no shadow)
- optional walled-town keys (settlement, town, city use them; leave out elsewhere):
  - `town_radius` — `icons` stay inside this circle (0 = off)
  - `wall` — `palisade` = ring of stakes at `town_radius`, gates where roads
    cross; `menhirs` = ring of standing stones; `stone` = crenellated rampart with a tower each
    side of every gate and one every `global.tower_gap_count` blocks (`rampart_*`, `tower_size` globals); `none`
  - `outer_icons` / `outer_spacing` — scatter outside the wall
  - `centerpiece` (`guildhall`, `windmill`, `statue`) + `centerpiece_size` — one big
    building just north of the plaza; scatter keeps clear of it
- other optional keys (any region):
  - `feature` — ground feature under the roads: `river` (with plank bridges;
    always crosses the N/S edges at `global.river_anchor`, through a gap in the
    frame, so N-S stacked river tiles join; E-W neighbours don't), `pools` (marsh water + lily pads),
    `pit` (terraced quarry pit), `lake` (one continuous lake over
    everything but a `lake_land` strip along the roads; the roads run through it as causeways), `canyon` (ravine +
    rope bridges; the river rule mirrored to the east side), `falls` (corner cliff + waterfall + pool), `mud`
    (battlefield), `springs` (steaming stone-ringed pools), `ponds` (lily-covered ponds in 1-4 of
    the corners that fit, each a random size up to `pond_size`), `wharf` (the `lake` with a wider `wharf_land` strip, a
    jetty, a barge and a raft), `flood` (the ground colour is the
    water: ripples, floating leaves, roads become boardwalks), `millrace` (river + watermill on the
    bank), `dam` (river + stick dam, pond and lodge upstream), `holes` (dug pits with spoil rims),
    `blight` (diseased and rotten ground blotches), `cliffs` (roads on ledges, rock faces dropping
    to a valley; `cliff_width`, `cliff_height`), `bighill` (one hill under the clearing,
    `bighill_size`), `none`. Grass never draws on a feature
  - `mud` — count of battlefield mud patches drawn on top of any feature (e.g. a battlefield on a river)
  - `speckle` — ground flecks `#colour:count|#colour:count` (petals, ash, spores)
  - `layout` — `scatter` (default) or `rows` (orchard grid)
  - `required` — `painter:COUNT:lo-hi`, always placed first at every density
    (e.g. `house:1:90-110` on lumbercamp, quarry, orchard)
- every distinct rotation is its own image, so tiles are never rotated in TTS:

  | pattern | orientations | images |
  | --- | --- | --- |
  | `none` | — | 1 |
  | `deadend` | N, E, S, W | 4 |
  | `corner` | NE, ES, SW, NW | 4 |
  | `straight` | NS, EW | 2 |
  | `tee` | NES, ESW, NSW, NEW | 4 |
  | `cross` | NESW | 1 |

- `variants` = looks per orientation (`_NES1`, `_NES2`…). 1 = one of each shape
- full set per region (no `none`): 15 tiles + 1 back

- paths exit at the exact edge midpoint, so neighbours join
- deterministic: same CSV = same images. Reroll everything with `global.seed`,
  one region with its `seed_offset`
- names don't depend on `variants`; lowering it deletes the extra files
- art changed -> re-upload those PNGs (TTS caches by URL, so use a new URL)

## Meeple art

Hand-painted meeples, split into colour-free **shapes** and coloured by data,
so any shape can come out in any colour. Manual step, not part of
`master_sync.cmd`. Style rules: `internal/agent/meeple_artguide.md`.

```
internal/asset_generation/meeples_clean.psd   one layer per shape; paint in any colours
  -> python tools/build/build_meeple_shapes.py [layer ...]     (~45 s for all)
internal/asset_generation/meeple_shapes/<layer>/   alpha + one mask per colour slot (generated)
  -> python tools/build/build_meeples.py [file ...] [--prune]  (~10 s)
assets/meeples/<folder>/<file>.png + manifest.csv, internal/asset_generation/meeples_preview.png
```

- shapes: every PSD layer is split into colour slots, then finished (outline
  smoothed for the TTS side wall; `brush=yes` shapes get brush-pen details).
  Slots: `body` (largest colour), `ink` (#231f20 when it is not the body),
  `accent1..` (the rest, largest first). Gradient art (the badgers) keeps its
  sheen as a `tone` map that tints any body colour
- knobs in `data/asset_variables.csv`:
  - `meeple` rows: `canvas` (1536), `brush_strength`, `brush_blotch`
  - `meeple_colour` rows: named colours (`ink`, `denizen`, `marquise`, `eyrie`, ...)
  - `meeple_shape` rows: one per PSD layer, `species=<x> class=<big|base|short|special> [brush=yes]`.
    A layer without a row (or a row without a layer) fails the build
  - `meeple_skin` rows: one per output PNG, key = `<folder>/<file>` (path under `assets/meeples/`, no `.png`).
    `body=<colour>` required; `shape=<layer>` (default: the file name);
    `ink=` / `accent1=` ... override a slot (unset slots keep their painted colour);
    `tone=off` flattens a gradient shape. Colours are `meeple_colour` names or `#rrggbb`
- output folders (every shape gets its normal colours; all but special, character and enemies also get a yellow denizen):

  | folder | what | shapes |
  | --- | --- | --- |
  | `base/` | faction warriors, normal colours | `faction_*` |
  | `advanced/` | hirelings, normal colours (incl. the Root stoat, porcupine, duck) | `hireling_*` |
  | `custom/` | not from Root, their own colours | `custom_*` (beaver, bristle, red panda, squirrel) |
  | `special/` | one-offs; no denizen version | `special_*` (stag, bear, boar, snake, penguin, guildmaster) |
  | `character/` | vagabonds; no denizen version | `vb_*` |
  | `enemies/` | insects (enemies); no denizen version | `enemy_*` (ant, stag beetle, spider, scorpion, mantis, antlion, wasp, mosquito) |
  | `denizens/` | every base/advanced/custom shape again in denizen yellow, as `denizen_<shape>` | |

- new colour of an existing meeple = one row: `meeple_skin,custom/purple_cat,shape=faction_cat body=corvid,`
- new shape = a layer in `meeples_clean.psd` (right group, 1536 canvas, feet on
  the bottom row; layer name `<faction|hireling|custom|special|vb>_<species>`) + a `meeple_shape` row
  + a normal `meeple_skin` row + (unless special/vb) a `denizens/denizen_<shape>` row, then run both scripts
- enemy insects are NOT painted in the PSD: `tools/build/build_insects.py` draws them by code into its
  `Enemy` group (replacing only those layers, verifying the rest, previous PSD kept as `meeples_clean.psd.bak`).
  `--png DIR` previews without touching the PSD. New insect: a function there + `meeple_shape` / `meeple_skin`
  rows + a `tokens.xlsx` row (set `enemies`). Style: `meeple_artguide.md` section 12
  `internal/` is gitignored: back the PSD up before editing
- size lives in the shape (its pixels on the shared 1536 canvas), never in the skin
- needs `psd-tools` and `scikit-image` (`pip install psd-tools scikit-image`)

## Gem art

Code-drawn storybook gems on transparent PNGs, for cards. Same style helpers
as the map tiles. Manual step, not part of `master_sync.cmd`.

- `python tools/build/build_gems.py` — every colour (~7 s); `... ruby` — one colour
- writes `assets/gems/<colour>_<cut><n>.png` + `manifest.csv`. Every colour gets every cut
- knobs in `data/asset_variables.csv`:
  - `gem` rows: `out_size`, `variants`, `cuts`, `size` (lo-hi % of canvas,
    rolled per image), `seed_offset`, `wobble`, `facet_jitter`, `facet_line`, `glint`
  - `gem_colour` rows: one per colour, key = name used in filenames
  - also uses `global` `supersample`, `seed`, `ink`, `paper`, grain/tint
- cuts: round, oval, cushion, emerald, pear, marquise, heart, trillion, cabochon
- deterministic like the tiles; reroll with `gem.seed_offset`

## Card frame art

Card fronts + backs composed around a gem, after `assets/reference/City_*.png`.
Manual step, not part of `master_sync.cmd`. Run `build_gems.py` first.
How to run: see [Offline Generation](#offline-generation).

- writes `assets/cards/<name>_front.png` + `<name>_back.png` + `manifest.csv` (~1 s)
- front = grunge ground, band near the top with the gem on it, text panel; back = band across the middle, gem standing on it
- knobs in `data/asset_variables.csv` `card` rows:
  - `gems`: `|` list of `name=gem` pairs, gems from `assets/gems/manifest.csv`, e.g. `origin=ruby_heart1|spell0=diamond_cabochon1`.
    One card per pair, files named `<name>_front/back.png`. Unknown gem fails the build;
    a name dropped from the list has its files deleted
- plus one card per event deck (`deck_<id>` rows, shared with the maptile backs), named by deck id
  (`woodland_front.png`) and wearing that deck's `gem`
  - layout (units of a 750-wide card): `out_w`/`out_h`, `panel_box`, `front_band`/`back_band`,
    `front_gem_y`/`_long`/`_max_h`, `back_gem_y`/`_long`/`_max_h` (gems are never rotated;
    `_max_h` keeps tall gems inside the card)
  - look: `seed_offset`, `bg`, `bg_grunge`, `vignette`, `panel`, `panel_grunge`, `band_edge`/`band_mid`

## Landmark art

Code-drawn storybook landmarks on transparent PNGs, for TTS stand-up tokens.
Same style helpers as the map tiles. Manual step, not part of `master_sync.cmd`.
How to run: see [Offline Generation](#offline-generation).

- writes `assets/landmarks/<landmark>_s<size>.png` + `manifest.csv` (upserted)
- sizes 1-4: bigger AND more detailed per size. All sizes share one 1024 canvas
  with the base on the same line, so at one TTS scale size 4 stands taller
- knobs in `data/asset_variables.csv`:
  - `landmark` rows: `out_size`, `seed_offset`, `margin` (gap under the base)
  - `landmark_size` rows: key = landmark, value = width per size `w1|w2|w3|w4`
    (design units of the 1024 canvas). Blank slot = size not drawn: `|||760` = size 4 only
  - `landmark_scale` rows: height multiplier on top of the size class; one value (`1.5`) or per size (`|||1.2`, blank = 1)
  - `landmark_colour` rows: colours only landmarks use (brick, marble, ore, fey, ...);
    also uses `global` palette (`stone`, `timber`, `cat_banner`, `bird_banner`, `glow`, ...)
- landmarks (no people or creatures drawn; they are places):

  | landmark | sizes | what |
  | --- | --- | --- |
  | `guildhall` | 1-4 | lodge -> gabled hall -> winged hall -> towers + clock |
  | `building` | 1-4 | straw hut, log cabin, stone town house, capital hall (stone + brick) |
  | `cave` | 1-4 | burrow -> outcrop -> fanged crag -> cliff with torches + eyes |
  | `tree` `mineral_node` `fishing_spot` `herb` `tracks` `beehive` | 1 | gathering nodes |
  | `marquise_keep` `eyrie_roost` | 4 | faction strongholds |
  | `otter_tradepost` `alliance_burrow` `lizard_garden` | 1 | faction outposts: stilt stall over water, hill burrow, walled shrine garden |
  | `knave_camp` | 1-2 | bandit camp: one patched tent -> two tents, fence, strongbox |
  | `guild_tower` | 1-4 | Guild tower in guildhall materials (stone base, timber-framed plaster, slate, teal banners): lookout -> crenellated -> slate spire -> + side turret |
  | `eyrie_tower` | 1-4 | Eyrie tree-tower: stump hut -> braced deck + perch -> slim tower + banners -> + side turret, nest |
  | `marquise_barracks` | 1-4 | Marquisate: guardhouse -> timber-framed hall -> + watchtower -> two towers + portcullis gatehouse |
  | `alliance_barracks` | 1-4 | Alliance guerrilla post, dug in: hatch in a turf mound -> log-revetted dugout -> + dead-tree lookout, stakes -> two dugouts, thatched hide |
  | `otter_barracks` | 1-4 | Riverfolk mercenary hall on a dock: kiosk + price board -> pavilion + boat -> + upper floor, wide board -> + coin tower, wings |
  | `caravan` `shrine` | 1 | base class: covered wagon + waymark post (fast travel); wayside shrine to a nameless god |
  | `warehouse` `bank` | 1 | big class: plank storehouse with hoist; stone counting house with vault door + coin sign |

- new landmark = a painter in `build_landmarks.py` `PAINTERS` + a `landmark_size` row
- deterministic; reroll everything with `landmark.seed_offset`

# Tests + debug

- `tools/test_events.lua`, run last by `master_sync.cmd`: stubs TTS, runs the
  real built Global (rendering, branching, rolls, spawning, card index)
- `tools/test_change_converter.lua`, run by `master_sync.cmd` before it: cash-up,
  break-down, `checkBreakdowns`, coin counting, against `src/change_converter.lua`
- Global looks broken -> check `.tts/objects/Global.lua` byte size; a stale
  pull is the usual cause
- harness is Lua 5.4, TTS is 5.2 (MoonSharp): 5.3+ syntax passes tests and
  fails in game. Change Converter + Merchant Board syncs reject it; other
  scripts are unchecked
- `debug.lua`: focus + `Ctrl+Shift+E` prints every object Global sees and
  per card whether it rendered
