@echo off
REM Rebuild data + script, run offline tests, then refresh the runnable scripts.
cd /d "%~dp0"
REM sync_gold runs FIRST: it writes base_gold/gmnotes into tiles.xlsx and
REM spawngold into origins.xlsx and tiles.xlsx!lootbox_table, which every
REM sync below then reads.
python tools/sync/sync_gold.py || exit /b 1
REM sync_origin_text runs after sync_gold (which writes spawngold) and
REM before sync_origins_data (which reads effect into ORIGIN_DATA).
python tools/sync/sync_origin_text.py || exit /b 1
python tools/sync/sync_events_data.py || exit /b 1
python tools/sync/sync_card_importer.py || exit /b 1
python tools/sync/sync_items_data.py || exit /b 1
python tools/sync/sync_lootbox_data.py || exit /b 1
python tools/sync/sync_origins_data.py || exit /b 1
REM Hand-written object script: no generated data, but staged here so a
REM Ctrl+Alt+L cannot silently revert it, and checked for Lua 5.3+ syntax
REM that the 5.4 test harness would otherwise let through to the game.
python tools/sync/sync_change_converter.py || exit /b 1
REM Merchant board: inlines shops.xlsx and validates every ware name
REM against tiles.xlsx, so a renamed item fails here rather than becoming
REM an unpriceable object on the board.
python tools/sync/sync_merchant_board.py || exit /b 1
REM Maptile Manager: inlines data/maptile.xlsx (image URLs, descriptions, weights).
REM Images without a url are skipped and counted, so this never blocks the build.
python tools/sync/sync_maptile_manager.py || exit /b 1
REM ...and again LAST to splice ECONOMY, because sync_events_data.py rebuilds
REM Global.lua from src/global.lua and would wipe an earlier splice.
python tools/sync/sync_gold.py --splice-only || exit /b 1
python tools/refresh_master_reload.py || exit /b 1
python tools/debug.py || exit /b 1
"%~dp0tools/bin/lua54.exe" tools/test_events.lua
