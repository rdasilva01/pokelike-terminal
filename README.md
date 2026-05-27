# pokelike-terminal

A Python terminal UI for automating [pokelike.xyz](https://pokelike.xyz/), a Pokémon roguelike web game.

Connects to an open Chrome window via CDP, detects the current game screen, parses its state into JSON, and lets you navigate the game from a keyboard-driven terminal interface.

## Features

- Auto-detects game screens (main menu, starter select, map, and more)
- Rich terminal UI with keyboard navigation and letter shortcuts
- Auto-refreshes game state every 1.5 seconds
- Auto-selects your pre-chosen starter when the starter screen appears
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

Chrome must run with remote debugging enabled. `launcher.py` does this automatically. To do it manually:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug
```

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
| J | View raw parsed JSON |
| P | Reload browser page |
| R | Re-parse current screen |
| Q / Esc | Quit |

## Project structure

```
launcher.py         # finds Chrome, launches with debug port, starts interactor
browser.py          # CDP connection to open Chrome tab
screen_detector.py  # identifies current screen by DOM fingerprint
parsers/            # one parser per screen → returns state dict
models/screens.py   # TypedDicts for each screen's state
interactor.py       # Rich TUI — render loop, menu builders, key handling
config.py           # CDP port, target URL
```

## Screens implemented

| Screen | Parsed data |
|--------|-------------|
| Main menu | Selected gen, available gens, logged-in user |
| Starter select | Name, level, types, move for each starter |
| Map | Stage/boss info, team HP, bag, badges, all map nodes with type and state |
