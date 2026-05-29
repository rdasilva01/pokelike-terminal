# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Python automation library for [pokelike.xyz](https://pokelike.xyz/), a Pokémon roguelike web game. Scripts connect to an already-open Chrome window, detect the current game screen, parse its state into JSON, and execute actions on behalf of the player via a terminal UI.

## Setup

### Chrome — required before running anything

Chrome must be launched with remote debugging enabled. The launcher does this automatically, but if needed manually:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug
```

### Python dependencies

```
pip install playwright rich
python -m playwright install chromium
```

## Running

```
python launcher.py    # launches Chrome + interactor in one shot
python interactor.py  # interactor only (Chrome must already be open)
```

## Terminal UI (interactor)

- **↑↓** — navigate menu
- **Enter** — execute selected item
- **Letter shortcuts** — execute directly (N, Z, B, R, P, J, Q…)
- **P** — reload the browser page (works on all screens)
- **R** — re-parse current screen state
- **J** — view raw parsed JSON (any key to return)
- **D** — open Pokédex overlay (available on main menu and map screens)
- **Q / Esc** — quit

The UI auto-refreshes state every 0.5 seconds (`AUTO_REFRESH_INTERVAL` in `interactor.py`). Cursor position is preserved after actions; only resets when the screen type changes.

## Pokédex overlay (`show_pokedex`)

Full-screen overlay accessible via `D` from the main menu or map screen. Loads all 1350 species in one JS round-trip using `getPokemonLocations` and `getSpeciesTypes` game globals plus `pkrl_species_list` and `poke_dex` from localStorage.

**Search mode** (default): type to filter by name prefix, ↑↓ to scroll. Each entry shows types, normal-mode routes, and battle tower tiers.

**Route mode** (Tab to toggle): ◀▶ to cycle through routes and tower tiers in play order, ↑↓ to scroll that location's Pokémon list.

Tower floor tiers map to internal R×M× codes (3 rounds × 3 maps):
- Early → R1M1, R1M2
- Early-Middle → R1M3, R2M1
- Middle → R2M1, R2M2
- Middle-Late → R2M2, R2M3, R3M1
- Late → R3M2, R3M3

## Architecture

```
launcher.py         # finds Chrome, launches it with debug port, then starts interactor
browser.py          # connect_to_chrome() — CDP connection to open Chrome tab
screen_detector.py  # ScreenType enum + detect(page) — identifies screen by DOM fingerprint
parsers/
  base.py           # AbstractParser — parse(page) -> dict
  main_menu.py      # MainMenuParser
  map_screen.py     # MapParser — team, bag, badges, nodes
  battle.py         # BattleParser
  catch_pokemon.py  # CatchPokemonParser
  item_select.py    # ItemSelectParser
  item_equip.py     # ItemEquipParser
  trade_offer.py    # TradeOfferParser
  pokemon_received.py
  starter_select.py
  champion.py       # ChampionParser
models/
  screens.py        # TypedDicts for each screen's state dict
interactor.py       # Rich TUI — render loop, menu builders, key handling, show_pokedex
config.py           # TARGET_URL, CDP port constants
```

**Data flow:** `browser.py` → `screen_detector.detect()` → `Parser.parse()` → JSON dict → TUI menu → action

## DOM notes (pokelike.xyz)

- Buttons use class `btn-primary`. Their `textContent` is **title case** ("Normal Mode", "Battle Tower") even though CSS renders them uppercase — always match against title case in code.
- Gen selector buttons use class `gen-btn`; active gen has class `gen-btn--active`.
- The game uses `text-transform: uppercase` CSS, so visual text ≠ DOM text.
- Screen detection uses `page.locator("text=...")` which does case-insensitive substring matching.
- Clicking is done via `page.evaluate()` JS to avoid Playwright locator timeouts.

## Adding a New Screen Parser

1. Add a `ScreenType` value in `screen_detector.py`.
2. Add a detection fingerprint in `detect()` — find a unique DOM element for that screen.
3. Create `parsers/<screen_name>.py` subclassing `AbstractParser`.
4. Add a `TypedDict` in `models/screens.py`.
5. Register the parser in `PARSER_MAP` and add a menu builder in `MENU_BUILDERS` in `interactor.py`.
