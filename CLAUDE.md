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

### Global keys (all screens)
- **↑ ↓** — navigate menu / move between rows
- **← →** — move between columns (grid screens) or navigate strip
- **Enter** — execute selected item
- **Letter shortcuts** — execute directly (N, Z, B, R, P, J, Q…)
- **P** — reload the browser page
- **J** — view raw parsed JSON (any key to return)
- **D** — open Pokédex overlay (main menu and map screens)
- **Q** — quit
- **Esc** — cancel current mode (swap / bag-pick on map); does NOT quit

### Grid navigation (screens with 2D layouts)
Several screens use 2D grid navigation instead of a flat list:

| Screen | Left/Right | Up/Down |
|--------|-----------|---------|
| Main menu | Switch column (modes ↔ gens/starters) or strip | Move within column |
| Map (normal) | Navigate action strip | Navigate accessible nodes |
| Map (swap/item) | Move between team columns; navigate strip | Move between team rows; enter/exit strip |
| Battle | Navigate action strip (left/right = up/down) | — |
| Catch / Item select | Move between cards; navigate strip | Switch card row ↔ strip |
| Team full | Move between columns within grid | Move between rows; enter/exit strip |
| Starter select | — | Up/Down (left/right also work) |

### Map screen modes
- **Normal**: nodes on top row (← → cycles), utility actions on bottom row (← →)
- **Swap / Item-pick**: left team panel becomes a navigable 3×2 grid; strip shows Cancel/Quit only
- **Bag**: strip shows bag items (flat navigation)

### Utils menu (U key on map or catch/item/trade/team-full screens)

| Toggle | Key | Default | Effect |
|--------|-----|---------|--------|
| Level Path | U | ON | Highlights highest-score path to boss in `MapGraphWidget` |
| Follow Path | F | OFF | Auto-clicks next node in best path (skips boss) |
| Autoswap | A | OFF | Reorders team by type matchup before entering a trainer/boss node |
| Prio. First Catch | C | OFF | +10 bonus to catch nodes in path scoring |
| Prio. Heal | H | OFF | +10 bonus to pokecenter nodes in path scoring |
| Poke. Recommend | R | ON | Highlights best catch choice based on upcoming 3 boss types; defaults cursor to it |
| Debug | G | — | Overlay showing path scores + catch recommendation breakdown with per-boss weights |

All toggle states are stored as 1-element lists (`[bool]`) on the `PokelikeApp` instance so closures can mutate them.

The UI auto-refreshes state every **0.1 seconds** (`AUTO_REFRESH_INTERVAL` in `interactor.py`). A DOM hash pre-check skips full re-parses when nothing changed. `_force_parse` is set after any action to guarantee a fresh parse on the next cycle.

## Pokédex overlay

Full-screen overlay accessible via `D` from the main menu or map screen. Loads all 1350 species in one JS round-trip.

**Search mode** (default): type to filter by name prefix, ↑↓ to scroll. Each entry shows types, normal-mode routes, and battle tower tiers.

**Route mode** (Tab to toggle): ◀▶ to cycle through routes and tower tiers in play order, ↑↓ to scroll that location's Pokémon list.

## Architecture

```
launcher.py           # finds Chrome, launches it with debug port, then starts interactor
browser.py            # connect_to_chrome() — CDP connection to open Chrome tab
screen_detector.py    # ScreenType enum + detect(page) — single JS round-trip fingerprint
parsers/
  base.py             # AbstractParser — parse(page) -> dict
  main_menu.py        # MainMenuParser
  map_screen.py       # MapParser — 2 CDP calls total (team + everything else merged)
  battle.py           # BattleParser
  catch_pokemon.py    # CatchPokemonParser
  item_select.py      # ItemSelectParser
  item_equip.py       # ItemEquipParser
  trade_offer.py      # TradeOfferParser
  pokemon_received.py # PokemonReceivedParser
  starter_select.py   # StarterSelectParser
  champion.py         # ChampionParser
  team_full.py        # TeamFullParser — team full / release screen
models/
  screens.py          # TypedDicts for each screen's state dict
interactor.py         # Textual TUI — widgets, render loop, menu builders, key handling
config.py             # TARGET_URL, CDP port constants
```

**Data flow:** `browser.py` → `screen_detector.detect()` → `Parser.parse()` → JSON dict → TUI widget → action

### Custom screen layouts (interactor.py)

Each special screen has a dedicated Textual widget instead of the default ActionMenu:

| Screen | Widget | Layout |
|--------|--------|--------|
| Main menu | `MainMenuPanel` | Mode cards (left) + gen/starter column (right) + strip |
| Map | `TeamGridPanel` + `MapGraphWidget` + strip | Team 3×2 · graph · bag/boss · node strip |
| Battle | `BattlePanel` → two `BattleSidePanel` | YOUR TEAM · RIVAL (each 3×2) + strip |
| Catch | `CatchPokemonPanel` | Horizontal cards + strip |
| Item select | `ItemSelectPanel` | Horizontal cards + strip |
| Team full | `TeamFullPanel` | Incoming label + 2×3 grid + strip |

### Type-effectiveness scoring (`interactor.py`)

Three helper functions drive both Autoswap and Poke. Recommend:

- `_autoswap_score(pokemon_types, poke_type)` — our Pokémon's attack effectiveness vs the trainer. Multiplies across all of the trainer's types (dual-type = 2.0×0.5 = 1.0).
- `_defense_score(pokemon_types, poke_type)` — damage multiplier the trainer deals to us. Multiplies across every (trainer_type × our_type) combination.
- `_catch_recommend_score(pokemon_types, boss_types)` — weighted resistance sum vs the next 3 bosses: `Σ (1 / _defense_score) × weight` with weights 3/2/1. Higher = better catch.

### Map state fields

`MapParser.parse()` returns `upcoming_boss_types: list[str]` — the types of the current stage's boss plus the next two, fetched from `GYM_LEADERS[currentMap..+2]` in one JS call. The interactor caches this as `self._upcoming_boss_types` and uses it on the catch screen.

### Performance

- `MapParser` uses **2 `page.evaluate()` calls**: `_parse_team()` (DOM + localStorage in one JS shot) and `_parse_static()` (header, boss, bag, badges, nodes, upcoming boss types — all merged).
- `_dom_hash()` runs one cheap JS call per cycle; identical hash + same screen = skip full parse.
- `_force_parse` flag is set after any action to guarantee a fresh parse on the next cycle regardless of hash.

## DOM notes (pokelike.xyz)

- Buttons use class `btn-primary`. Their `textContent` is **title case** ("Normal Mode", "Battle Tower") even though CSS renders them uppercase — always match against title case in code.
- Gen selector buttons use class `gen-btn`; active gen has class `gen-btn--active`.
- The game uses `text-transform: uppercase` CSS, so visual text ≠ DOM text.
- Screen detection uses a single `page.evaluate()` JS call checking DOM fingerprints in priority order.
- Clicking is done via `page.evaluate()` JS to avoid Playwright locator timeouts.
- Team full screen: `.swap-prompt` is the unique fingerprint; last `.poke-card` in `.screen.active` is the incoming pokemon; the rest are the current team.
- **Always scope catch-screen selectors to `.screen.active`** — inactive screens remain in the DOM (e.g. a shiny card from a rejected shiny event keeps its `.poke-choice-wrap`). The catch parser, screen detector fingerprint, click action, and DOM hash all use `.screen.active .poke-choice-wrap`.

## Adding a New Screen Parser

1. Add a `ScreenType` value in `screen_detector.py`.
2. Add a detection fingerprint in `detect()` — find a unique DOM element for that screen (checked before any existing fingerprint it might conflict with).
3. Create `parsers/<screen_name>.py` subclassing `AbstractParser`. Use a single `page.evaluate()` that returns all needed data in one JS round-trip.
4. Add a `TypedDict` in `models/screens.py`.
5. Register the parser in `PARSER_MAP` and add a menu builder in `MENU_BUILDERS` in `interactor.py`.
6. For a rich layout: create a Widget subclass, add it to `compose()`, hide it in `on_mount()`, wire `display` in the `_rebuild()` display-switching block, and add an `elif is_<screen>:` rebuild branch that returns early.
