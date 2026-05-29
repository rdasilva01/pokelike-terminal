# pokelike-terminal

A Python terminal UI for automating [pokelike.xyz](https://pokelike.xyz/), a Pokémon roguelike web game.

Connects to an open Chrome window via CDP, detects the current game screen, parses its state into JSON, and lets you navigate the game from a keyboard-driven terminal interface.

## Features

- Auto-detects game screens (main menu, map, battle, catch, items, trades, champion, and more)
- Rich terminal UI with keyboard navigation and letter shortcuts
- Auto-refreshes game state every 0.5 seconds
- Auto-clicks starter select, badge screen, game over, and evolution screens
- 3-panel MAP layout: team (with HP and move info) · actions · bag
- Pokémon swap via drag-to from the terminal
- Bag equip mode — pick an item from the bag and apply it to a Pokémon
- **Pokédex overlay** — type-ahead search across all 1350 species + reverse route lookup
- Raw JSON viewer for full parsed game state
- Launches Chrome automatically via `launcher.py`

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
# Install Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable

# Install Python dependencies
pip install playwright rich
python -m playwright install chromium
```

Then run normally — `launcher.py` will find Chrome automatically and use `~/.chrome-debug` as the profile directory.

## Usage

```
python launcher.py    # launches Chrome + terminal UI in one shot
python interactor.py  # terminal UI only (Chrome must already be open on pokelike.xyz)
```

## Terminal controls

| Key | Action |
|-----|--------|
| ↑ ↓ | Navigate menu |
| Enter | Execute selected item |
| Letter shortcuts | Execute directly (N, Z, B, R, P, J, Q…) |
| ◀ ▶ | Pick starter (on main menu) |
| D | Open Pokédex overlay |
| J | View raw parsed JSON |
| P | Reload browser page |
| R | Re-parse current screen |
| Q / Esc | Quit |

## Pokédex overlay

Press **D** from the main menu or map screen.

**Search mode** — type any characters to filter all 1350 species by name. Each result shows types, normal-mode spawn locations, and battle tower tiers. Backspace to edit, ↑↓ to scroll.

**Route mode** — press **Tab** to switch. Use ◀▶ to cycle through every route and tower floor in play order; ↑↓ to scroll that location's Pokémon list. Tab again to return to search.

Press **ESC** to exit the overlay.

## Screens implemented

| Screen | Parsed data |
|--------|-------------|
| Main menu | Selected gen, available gens, logged-in user |
| Starter select | Name, level, types, move for each starter |
| Map | Stage/boss info, team HP/moves/types, bag items, badges, all map nodes with type and state |
| Battle | Both teams with HP, active/fainted state, continue-ready detection |
| Catch Pokémon | Choices with level, types, shiny/caught flags |
| Item select | Item names and descriptions |
| Item equip / Move tutor | Per-Pokémon equip or teach options |
| Trade offer | Trade members with types and level |
| Pokémon received | Name, level, types, move, shiny flag |
| Champion | Win title, run count, full winning team stats |
| Game over | Auto-clicks Try Again |

## Project structure

```
launcher.py         # finds Chrome, launches with debug port, starts interactor
browser.py          # CDP connection to open Chrome tab
screen_detector.py  # identifies current screen by DOM fingerprint
parsers/            # one parser per screen → returns state dict
models/screens.py   # TypedDicts for each screen's state
interactor.py       # Rich TUI — render loop, menu builders, Pokédex overlay
config.py           # CDP port, target URL
```
