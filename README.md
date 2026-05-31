# pokelike-terminal

A Python terminal UI for automating [pokelike.xyz](https://pokelike.xyz/), a Pokémon roguelike web game.

Connects to an open Chrome window via CDP, detects the current game screen, parses its state, and lets you navigate the game from a fully keyboard-driven terminal interface.

## Features

- **Auto-detects 15+ game screens** — main menu, map, battle, catch, items, trades, team full, champion, and more
- **Rich custom layouts** per screen — not just a menu list but purpose-built panels for each screen type
- **2D grid navigation** — arrow keys navigate spatially (rows × columns) on map, battle, catch, item select, team full, and main menu screens
- **10 Hz refresh** with DOM hash caching — only re-parses when something actually changed
- **Map screen**: team panel (3×2 with HP/types/items) · node graph · bag · boss info · node carousel
- **Battle screen**: YOUR TEAM vs RIVAL side-by-side, each as a 3×2 grid with HP bars
- **Main menu**: game mode cards · generation selector · starter picker — all keyboard navigable
- **Pokémon swap** via the team panel grid (navigate with arrows, Enter to pick)
- **Bag equip mode** — pick item from bag, apply to Pokémon
- **Pokédex overlay** — search all 1350 species or browse by route/tower tier
- Raw JSON viewer for full parsed game state
- Auto-clicks starter select, badge screen, game over, and evolution screens
- Launches Chrome automatically via `launcher.py`

### Utils menu (U on map or catch/item/trade screens)

| Toggle | Key | Default | Description |
|--------|-----|---------|-------------|
| Level Path | U | ON | Highlights the highest-score path to the boss |
| Follow Path | F | OFF | Auto-clicks the next node in the best path |
| Autoswap | A | OFF | Reorders team by type matchup before battles |
| Prio. First Catch | C | OFF | Boosts catch nodes in path scoring |
| Prio. Heal | H | OFF | Boosts Pokémon Center nodes in path scoring |
| Poke. Recommend | R | ON | Highlights the best catch based on next 3 bosses |
| Debug | G | — | Shows path scores and catch recommendation breakdown |

## Requirements

- Python 3.11+
- Google Chrome

```
pip install playwright rich
python -m playwright install chromium
```

## Setup

### Windows

Chrome must run with remote debugging enabled. `launcher.py` does this automatically. To do it manually:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug
```

### Ubuntu 22.04

```bash
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable
pip install playwright rich
python -m playwright install chromium
```

## Usage

```
python launcher.py    # launches Chrome + terminal UI in one shot
python interactor.py  # terminal UI only (Chrome must already be open on pokelike.xyz)
```

## Terminal controls

### Global

| Key | Action |
|-----|--------|
| ↑ ↓ | Navigate rows / move up-down |
| ← → | Navigate columns / move left-right |
| Enter | Execute selected item |
| Letter shortcuts | Execute directly (N, Z, B, P, J, Q…) |
| P | Reload browser page |
| J | View raw parsed JSON |
| D | Open Pokédex overlay |
| Q | Quit |
| Esc | Cancel current mode (swap / item-pick on map) |

### Grid navigation

Most screens use spatial 2D navigation:

- **Main menu** — ← → switches between the mode column and the gen/starter column; ↑ ↓ moves within each column; reach the bottom strip with ↓ from either column
- **Map (normal)** — ← → cycles accessible nodes; ↓ enters the action strip; ↑ returns to nodes
- **Map (swap / item-pick)** — the team panel becomes a 3×2 grid; ← → moves columns, ↑ ↓ moves rows, ↓ from last row enters the Cancel/Quit strip
- **Battle** — ← → navigates the action strip
- **Catch / Item select** — ← → moves between cards; ↓ enters strip; ↑ returns to cards
- **Team full** — 2×3 grid of team members; ↓ from last row enters strip
- **Starter / Wild Pokémon** — ← → also acts as ↑ ↓

## Pokédex overlay

Press **D** from the main menu or map screen.

**Search mode** — type any characters to filter all 1350 species by name. Each result shows types, normal-mode spawn locations, and battle tower tiers. Backspace to edit, ↑ ↓ to scroll.

**Route mode** — press **Tab** to switch. Use ← → to cycle through every route and tower floor in play order; ↑ ↓ to scroll that location's Pokémon list.

Press **Esc** to close the overlay.

## Screens implemented

| Screen | Custom layout | Parsed data |
|--------|--------------|-------------|
| Main menu | Mode cards + gen/starter column + strip | Selected gen, available gens, logged-in user |
| Starter select | Horizontal cards | Name, level, types, move per starter |
| Map | Team grid + graph + bag/boss + node strip | Stage/boss, team HP/moves/types, bag, badges, all nodes |
| Battle | Two side-panels (3×2 each) + strip | Both teams: HP, active/fainted, continue-ready |
| Catch Pokémon | Horizontal cards + strip | Choices: level, types, shiny/caught flags, stats, move — recommended card highlighted in green |
| Item select | Horizontal cards + strip | Item names and descriptions |
| Item equip / Move tutor | Scrollable list | Per-Pokémon equip or teach options |
| Trade offer | Default list | Trade members with types and level |
| Pokémon received | Default list | Name, level, types, move, shiny flag |
| Team full | 2×3 grid + strip | Incoming Pokémon + current team |
| Champion | Default list | Win title, run count, full winning team |
| Game over | — | Auto-clicks Try Again |

## Project structure

```
launcher.py           # finds Chrome, launches with debug port, starts interactor
browser.py            # CDP connection to open Chrome tab
screen_detector.py    # identifies current screen — single JS round-trip
parsers/              # one parser per screen, each using minimal CDP calls
models/screens.py     # TypedDicts for each screen's state
interactor.py         # Textual TUI — widgets, layouts, grid nav, Pokédex overlay
config.py             # CDP port, target URL
```
