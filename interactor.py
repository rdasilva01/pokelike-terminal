import json
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    DataTable, Footer, Header, Input, Label, Static
)
from textual import work

import item_db
from browser import connect_to_chrome
from screen_detector import detect, ScreenType
from parsers.battle import BattleParser
from parsers.champion import ChampionParser
from parsers.pokemon_received import PokemonReceivedParser
from parsers.stage_select import StageSelectParser
from parsers.team_select import TeamSelectParser
from parsers.trade_offer import TradeOfferParser
from parsers.catch_pokemon import CatchPokemonParser
from parsers.item_equip import ItemEquipParser
from parsers.item_select import ItemSelectParser
from parsers.main_menu import MainMenuParser
from parsers.map_screen import MapParser
from parsers.starter_select import StarterSelectParser
from parsers.team_full import TeamFullParser

PARSER_MAP = {
    ScreenType.MAIN_MENU:        MainMenuParser(),
    ScreenType.STARTER_SELECT:   StarterSelectParser(),
    ScreenType.MAP:              MapParser(),
    ScreenType.BATTLE:           BattleParser(),
    ScreenType.TRADE_OFFER:      TradeOfferParser(),
    ScreenType.POKEMON_RECEIVED: PokemonReceivedParser(),
    ScreenType.STAGE_SELECT:     StageSelectParser(),
    ScreenType.TEAM_SELECT:      TeamSelectParser(),
    ScreenType.CATCH_POKEMON:    CatchPokemonParser(),
    ScreenType.ITEM_SELECT:      ItemSelectParser(),
    ScreenType.ITEM_EQUIP:       ItemEquipParser(),
    ScreenType.CHAMPION:         ChampionParser(),
    ScreenType.TEAM_FULL:        TeamFullParser(),
}

ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}

AUTO_REFRESH_INTERVAL = 0.1

STARTERS: dict[str | None, list[tuple[str, str]]] = {
    "I":  [("B", "#4ade80"), ("C", "#fb923c"), ("S", "#38bdf8")],
    "II": [("C", "#4ade80"), ("C", "#fb923c"), ("T", "#38bdf8")],
}
STARTERS_DEFAULT = STARTERS["I"]


def get_starters(gen: str | None) -> list[tuple[str, str]]:
    return STARTERS.get(gen or "I", STARTERS_DEFAULT)


# ---------------------------------------------------------------------------
# Menu item
# ---------------------------------------------------------------------------

@dataclass
class MenuItem:
    label: str
    shortcut: str
    action: Callable
    enabled: bool = True


# ---------------------------------------------------------------------------
# Textual widgets
# ---------------------------------------------------------------------------

class StatusBar(Static):
    """One-line status bar: screen name · info · refresh dot."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #0f0f1f;
        color: #555577;
        padding: 0 2;
        border-bottom: solid #1e1e3a;
    }
    """

    def update_status(self, screen: ScreenType, state: dict, flash: bool) -> None:
        dot = "[bold #f5c518]●[/]" if flash else "[dim]·[/]"
        name = f"[bold #00d7d7]{screen.name.replace('_', ' ')}[/]"
        info = self._build_info(screen, state)
        self.update(Text.from_markup(f" {name}  {info}  {dot}"))

    @staticmethod
    def _build_info(screen: ScreenType, state: dict) -> str:
        if screen == ScreenType.CATCH_POKEMON:
            parts = [c["name"] for c in state.get("choices", [])]
            return f"[#e8e8ff]{'  ·  '.join(parts)}[/]"
        if screen == ScreenType.ITEM_SELECT:
            parts = [c["name"] for c in state.get("choices", [])]
            return f"[#e8e8ff]{'  ·  '.join(parts)}[/]"
        if screen == ScreenType.ITEM_EQUIP:
            label = "MOVE TUTOR" if state.get("is_move_tutor") else "EQUIP ITEM"
            name  = state.get("item_desc" if state.get("is_move_tutor") else "item_name", "?")
            return f"[dim]{label}[/]  [#e8e8ff]{name}[/]"
        if screen == ScreenType.POKEMON_RECEIVED:
            p     = state.get("pokemon") or {}
            shiny = " [bold yellow]★[/]" if p.get("is_shiny") else ""
            types = "/".join(p.get("types", []))
            return (
                f"[bold #e8e8ff]{p.get('name','?')}[/]{shiny}"
                f"  [dim]Lv{p.get('level','')}  [{types}]  {p.get('move','')}[/]"
            )
        if screen == ScreenType.CHAMPION:
            run   = state.get("run_count", "")
            names = "  ".join(
                f"{p['name']} {p['level']}" for p in state.get("team", [])
            )
            return f"[bold #f5c518]{run}[/]  [#e8e8ff]{names}[/]"
        if screen == ScreenType.TRADE_OFFER:
            parts = [
                f"{m['name']} {m['level']}" for m in state.get("members", [])
            ]
            return f"[#e8e8ff]{'  |  '.join(parts)}[/]"
        if screen == ScreenType.TEAM_FULL:
            incoming = state.get("incoming", [])
            names    = "  ·  ".join(p["name"] for p in incoming)
            return f"[#e8e8ff]Team Full[/]  [dim]{names}[/]"
        if screen == ScreenType.BATTLE:
            cont  = "  [bold #00e676]CONTINUE READY[/]" if state.get("can_continue") else ""
            return f"[#e8e8ff]{state.get('header', 'Battle')}[/]{cont}"
        if screen == ScreenType.MAP:
            stage     = state.get("stage", {})
            boss      = stage.get("boss") or "?"
            btype     = stage.get("boss_type") or ""
            stage_num = stage.get("number") or "?"
            badges    = state.get("badges", 0)
            return (
                f"[dim]stage[/] [bold #00d7d7]{stage_num}[/]"
                f"  [bold #e8e8ff]vs {boss}[/]"
                f"  [dim]{btype}[/]"
                f"  [dim]badges[/] [#f5c518]{badges}[/]"
            )
        # MAIN_MENU and others
        user = state.get("logged_in_user") or "not logged in"
        gen  = state.get("selected_gen") or "I"
        gens = state.get("available_gens", [])
        gen_display = "  ".join(
            f"[bold #f5c518]{ROMAN.get(g, g)}[/]" if g == gen
            else f"[dim]{ROMAN.get(g, g)}[/]"
            for g in gens
        )
        return f"[dim]user[/] [#00e676]{user}[/]  [dim]gen[/]  {gen_display}"


class StarterPickerWidget(Static):
    """Compact B / C / S starter selector shown on the MAIN_MENU screen."""

    DEFAULT_CSS = """
    StarterPickerWidget {
        width: 18;
        border: round #2a2a4a;
        background: #12121f;
        padding: 1 1;
        margin-left: 1;
        display: none;
        align: center top;
        height: auto;
    }
    """

    def update_starters(self, starters: list[tuple[str, str]], selected: int) -> None:
        t = Text()
        t.append("starter\n", style="#555577")
        for i, (letter, color) in enumerate(starters):
            if i == selected:
                t.append(f" {letter} ", style=f"bold {color} on #1e1e35")
            else:
                t.append(f" {letter} ", style="dim")
        t.append("\n◀ ▶ pick", style="#555577")
        self.update(t)


class PokemonTeamPanel(Static):
    """Team display for the MAP screen."""

    DEFAULT_CSS = """
    PokemonTeamPanel {
        width: 3fr;
        border: round #2a2a4a;
        background: #12121f;
        padding: 1 1;
        margin-right: 1;
        height: 1fr;
    }
    """

    def update_team(self, team: list, swap_val) -> None:
        swap_src_idx = swap_val if isinstance(swap_val, int) else None

        def make_block(pi: int, p: dict) -> Text:
            hp        = p.get("hp_pct", 100)
            hp_cur    = p.get("hp_current")
            hp_max    = p.get("hp_max")
            move_tier = p.get("move_tier")
            types     = p.get("types", [])
            color     = "#00e676" if hp > 50 else "#f5c518" if hp > 20 else "#ff1744"
            hp_str    = f"{hp_cur}/{hp_max}" if hp_cur is not None else f"{hp}%"
            move_str  = f"T{move_tier} {types[0]}" if move_tier is not None and types else ""
            if swap_src_idx == pi:
                name_style = "bold #00d7d7 reverse"
            elif swap_val == "src":
                name_style = f"bold {color} dim"
            else:
                name_style = f"bold {color}"
            t = Text()
            t.append(f"{pi + 1}. {p['name']}\n", style=name_style)
            t.append("/".join(types) + "\n", style="#555577")
            t.append(f"Lv{p['level']}  {hp_str}\n", style=color)
            if move_str:
                t.append(move_str + "\n", style="#555577")
            return t

        if not team:
            self.update(Text("[dim]no team[/]"))
            return

        header = Text("[dim]TEAM[/]\n", style="")
        if len(team) > 3:
            left  = team[:3]
            right = team[3:]
            grid  = Table.grid(padding=(0, 2))
            grid.add_column(ratio=1)
            grid.add_column(ratio=1)
            col_a = Text()
            for pi, p in enumerate(left):
                col_a.append_text(make_block(pi, p))
                col_a.append("\n")
            col_b = Text()
            for pi, p in enumerate(right):
                col_b.append_text(make_block(pi + 3, p))
                col_b.append("\n")
            grid.add_row(col_a, col_b)
            body = Text.from_markup("[dim]TEAM[/]\n")
            self.update(body)
            # Use a grid renderable since Static accepts Rich renderables
            combined = Table.grid(padding=(0, 2))
            combined.add_column(ratio=1)
            combined.add_column(ratio=1)
            ltext = Text()
            for pi, p in enumerate(left):
                ltext.append_text(make_block(pi, p))
                ltext.append("\n")
            rtext = Text()
            for pi, p in enumerate(right):
                rtext.append_text(make_block(pi + 3, p))
                rtext.append("\n")
            combined.add_row(ltext, rtext)
            self.update(combined)
        else:
            body = Text()
            for pi, p in enumerate(team):
                body.append_text(make_block(pi, p))
                body.append("\n")
            self.update(body)


class BagPanel(Static):
    """Bag display for the MAP screen."""

    BORDER_TITLE = "BAG"

    DEFAULT_CSS = """
    BagPanel {
        width: 21;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        height: 1fr;
        margin-left: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    """

    def update_bag(self, bag: list, follow_on: bool = False,
                   heal_on: bool = False, catch_on: bool = False,
                   autoswap_on: bool = False, autobattle_on: bool = False,
                   mystery_on: bool = False, catches_on: bool = False) -> None:
        t = Text()
        if bag:
            for item in bag:
                t.append(f"{item['name'][:17]}\n", style="#e8e8ff")
        else:
            t.append("—\n", style="#555577")
        t.append("\n")

        def _row(key: str, label: str, active: bool) -> None:
            style = "#00e676" if active else "#555577"
            state = "ON " if active else "OFF"
            t.append(f"{key}  {label} {state}\n", style=style)

        _row("F", "Follow Path ", follow_on)
        _row("A", "Autoswap    ", autoswap_on)
        _row("T", "Autobattle  ", autobattle_on)
        _row("H", "Prio. Heal  ", heal_on)
        _row("C", "Prio. Catch ", catch_on)
        _row("M", "Prio. Mystery", mystery_on)
        _row("N", "Prio. Catches", catches_on)
        t.append("\n")
        t.append("R  refresh\n", style="dim #555577")
        t.append("J  raw json",  style="dim #555577")
        self.update(t)


class BossPanel(Static):
    """Boss/gym leader info panel for the MAP screen."""

    BORDER_TITLE = "BOSS"

    DEFAULT_CSS = """
    BossPanel {
        width: 21;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        height: auto;
        margin-left: 1;
        margin-top: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    """

    def update_boss(self, stage: dict) -> None:
        boss      = stage.get("boss") or ""
        boss_type = stage.get("boss_type") or ""
        team      = (stage.get("boss_team") or [])[:6]
        t = Text()
        if boss:
            t.append(f"{boss}\n", style="bold #f5c518")
            if boss_type:
                t.append(f"{boss_type} Gym\n", style="#e8e8ff")
        else:
            t.append("—\n", style="#555577")
        if team:
            t.append("\n")
            for p in team:
                name  = (str(p.get("name") or ""))[:11]
                level = p.get("level") or 0
                lv    = f"Lv{level}" if level else "?"
                t.append(f"{name:<11} {lv}\n", style="#aaaacc")
        self.update(t)


# ---------------------------------------------------------------------------
# Auto-starter click
# ---------------------------------------------------------------------------

def _click_center(page) -> None:
    vp = page.viewport_size or {"width": 800, "height": 600}
    page.mouse.move(vp["width"] // 2, vp["height"] // 2)
    page.mouse.click(vp["width"] // 2, vp["height"] // 2)
    page.mouse.move(0, 0)


def click_starter(page, starter_idx: int) -> str:
    page.evaluate("""(i) => {
        const cards = Array.from(document.querySelectorAll('.poke-card'))
            .filter(c => c.getBoundingClientRect().width > 0)
        if (cards[i]) cards[i].click()
    }""", starter_idx)
    return f"Auto-selected starter [{starter_idx}]"


# ---------------------------------------------------------------------------
# Screen-specific menu builders
# ---------------------------------------------------------------------------

def build_main_menu_items(
    state: dict, page, refresh_fn: Callable, selected_starter: int
) -> list[MenuItem]:

    def click_btn(text):
        def _action():
            page.evaluate(
                """(text) => {
                    const btn = Array.from(document.querySelectorAll('.btn-primary'))
                        .find(b => b.textContent.trim() === text);
                    if (btn) btn.click();
                }""",
                text,
            )
            return f"Clicked: {text}"
        return _action

    def click_gen(roman):
        def _action():
            page.locator(".gen-btn", has_text=roman).first.click()
            return f"Switched to Gen {ROMAN.get(roman, roman)}"
        return _action

    gens        = state.get("available_gens", [])
    selected_gen = state.get("selected_gen")
    gen          = selected_gen or "I"
    starters     = get_starters(gen)

    # Left column: game modes
    items: list[MenuItem] = [
        MenuItem("Normal Mode",  "N", click_btn("Normal Mode")),
        MenuItem("Nuzlocke",     "Z", click_btn("Nuzlocke")),
        MenuItem("Battle Tower", "B", click_btn("Battle Tower")),
    ]

    # Right column: gens
    for g in gens:
        num = ROMAN.get(g, g)
        items.append(MenuItem(f"Gen {g}", num, click_gen(g), enabled=(g != selected_gen)))

    # Right column: starters — use digit shortcuts (7/8/9) to avoid clashing with mode keys
    _starter_shortcuts = ["7", "8", "9"]
    for i, (letter, _color) in enumerate(starters):
        def set_starter(idx=i):
            return f"SET_STARTER:{idx}"
        items.append(MenuItem(f"Starter {letter}", _starter_shortcuts[i] if i < len(_starter_shortcuts) else "?",
                              set_starter, enabled=(i != selected_starter)))

    def reload_page():
        page.reload()
        return "Page reloaded."

    # Strip
    items += [
        MenuItem("Pokédex",     "D", lambda: "SHOW_POKEDEX"),
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_starter_select_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    starters = state.get("starters", [])

    def pick(idx):
        def _action():
            return click_starter(page, idx)
        return _action

    items = []
    for i, s in enumerate(starters):
        name  = s.get("name", f"Starter {i}")
        types = "/".join(s.get("types", []))
        label = f"{name}  [{types}]"
        items.append(MenuItem(label, str(i + 1), pick(i), enabled=(i == selected_starter)))

    def reload_page():
        page.reload()
        return "Page reloaded."

    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


NODE_TYPE_LABEL = {
    "trainer":        "Trainer battle",
    "wild_encounter": "Wild encounter",
    "catch_pokemon":  "Catch Pokémon",
    "move_tutor":     "Move tutor",
    "mystery":        "Mystery event",
    "pokecenter":     "Pokémon Center",
    "shop":           "Shop",
    "item":           "Item",
    "trade":          "Trade",
    "boss":           "GYM LEADER",
    "start":          "Start",
}


def build_map_items(state: dict, page, refresh_fn: Callable, selected_starter: int,
                    swap_source=None, bag_mode=None,
                    utils_mode=None, level_path_on=None,
                    follow_path_on=None, prioritize_catch_on=None,
                    prioritize_heal_on=None, autoswap_on=None,
                    poke_recommend_on=None, item_recommend_on=None,
                    autobattle_on=None, prioritize_mystery_on=None,
                    prioritize_shiny_on=None, prioritize_catches_on=None) -> list[MenuItem]:
    team   = state.get("team", [])
    bag    = state.get("bag", [])
    nodes  = state.get("nodes", [])
    accessible      = [n for n in nodes if n["accessible"]]
    digit_shortcuts = "123456789"

    def reload_page():
        page.reload()
        return "Page reloaded."

    def _cancel_all(msg):
        if swap_source is not None: swap_source[0] = None
        if bag_mode    is not None: bag_mode[0]    = False
        if utils_mode  is not None: utils_mode[0]  = False
        return msg

    if bag_mode is not None and bag_mode[0]:
        items = []
        for i, item in enumerate(bag):
            shortcut = digit_shortcuts[i] if i < len(digit_shortcuts) else "?"
            def equip(idx=i, name=item["name"]):
                page.evaluate("""(i) => {
                    const badges = Array.from(document.querySelectorAll('#item-bar .item-badge'))
                        .filter(b => b.getBoundingClientRect().width > 0)
                    if (badges[i]) badges[i].click()
                }""", idx)
                bag_mode[0] = False
                return f"Equipping {name}..."
            items.append(MenuItem(item["name"], shortcut, equip))
        items += [
            MenuItem("Cancel", "X", lambda: _cancel_all("Cancelled")),
            MenuItem("Quit",   "Q", lambda: "QUIT"),
        ]
        return items

    # ── swap: pick source Pokémon ─────────────────────────────────────
    if swap_source is not None and swap_source[0] == "swap":
        items = []
        for i, p in enumerate(team):
            shortcut = digit_shortcuts[i] if i < len(digit_shortcuts) else "?"
            def pick_swap_src(idx=i):
                swap_source[0] = idx
                return f"Swap {team[idx]['name']} — pick target"
            items.append(MenuItem(p["name"], shortcut, pick_swap_src))
        items += [
            MenuItem("Cancel", "X", lambda: _cancel_all("Cancelled")),
            MenuItem("Quit",   "Q", lambda: "QUIT"),
        ]
        return items

    # ── item_pick: pick which Pokémon to open item overlay for ────────
    if swap_source is not None and swap_source[0] == "item_pick":
        items = []
        for i, p in enumerate(team):
            shortcut = digit_shortcuts[i] if i < len(digit_shortcuts) else "?"
            def pick_item_poke(idx=i, name=p["name"]):
                page.evaluate("""(i) => {
                    const slot = document.querySelectorAll('.map-panel-left .team-slot')[i]
                    if (!slot) return
                    const badge = slot.querySelector('.held-item, .item-badge, [class*="item"]')
                    if (badge) badge.click()
                }""", idx)
                swap_source[0] = None
                return f"Clicked item for {name}"
            items.append(MenuItem(p["name"], shortcut, pick_item_poke))
        items += [
            MenuItem("Cancel", "X", lambda: _cancel_all("Cancelled")),
            MenuItem("Quit",   "Q", lambda: "QUIT"),
        ]
        return items

    if swap_source is not None and isinstance(swap_source[0], int):
        src_idx = swap_source[0]
        items   = []
        for i, p in enumerate(team):
            shortcut = digit_shortcuts[i] if i < len(digit_shortcuts) else "?"
            if i == src_idx:
                items.append(MenuItem(p["name"], shortcut, lambda: None, enabled=False))
                continue
            def do_swap(src=src_idx, dst=i):
                page.locator(".map-panel-left .team-slot").nth(src).drag_to(
                    page.locator(".map-panel-left .team-slot").nth(dst)
                )
                page.mouse.move(0, 0)
                swap_source[0] = None
                return f"Swapped {team[src]['name']} and {team[dst]['name']}"
            items.append(MenuItem(p["name"], shortcut, do_swap))
        items += [
            MenuItem("Cancel", "X", lambda: _cancel_all("Swap cancelled")),
            MenuItem("Quit",   "Q", lambda: "QUIT"),
        ]
        return items

    node_shortcuts = "123456789abcdefghijklmnopqrstuvwxyz"

    def click_node(idx):
        def _action():
            page.evaluate("""(i) => {
                const svg = document.querySelector('.screen.active svg')
                const groups = Array.from(svg.children).filter(el => el.tagName === 'g')
                groups[i]?.dispatchEvent(new MouseEvent('click', {bubbles: true}))
            }""", idx)
            return f"Clicked node {idx}"
        return _action

    items = []
    for i, node in enumerate(accessible):
        label    = NODE_TYPE_LABEL.get(node["type"], node["type"].replace("_", " ").title())
        if node["type"] == "trainer":
            poke_type = node.get("poke_type", "")
            label     = f"Trainer battle  [{poke_type}]" if poke_type else "Trainer battle"
        shortcut = node_shortcuts[i] if i < len(node_shortcuts) else "?"
        items.append(MenuItem(label, shortcut, click_node(node["index"])))

    if bag_mode is not None and bag:
        def open_bag():
            bag_mode[0] = True
            return "Select item to equip"
        items.append(MenuItem("Bag", "B", open_bag))

    if swap_source is not None and len(team) > 1:
        def enter_swap():
            swap_source[0] = "swap"
            return "Pick Pokémon to swap"
        def enter_item():
            swap_source[0] = "item_pick"
            return "Pick Pokémon for item"
        items.append(MenuItem("Pokémon Swap",  "W", enter_swap))
        items.append(MenuItem("Pokémon Items", "I", enter_item))

    def open_dex():
        return "SHOW_POKEDEX"

    def enter_utils():
        return "SHOW_UTILS"

    items += [
        MenuItem("Utils",       "U", enter_utils),
        MenuItem("Pokédex",     "D", open_dex),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_catch_pokemon_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    choices = state.get("choices", [])

    def pick(idx):
        def _action():
            page.locator(".screen.active .poke-choice-wrap").nth(idx).click()
            return f"Selected {choices[idx]['name']}"
        return _action

    def reroll(idx):
        def _action():
            page.evaluate("""(i) => {
                const btn = document.querySelectorAll('.screen.active .poke-choice-wrap')[i]
                    ?.querySelector('.reroll-btn')
                if (btn) btn.click()
            }""", idx)
            return f"Rerolled slot {idx + 1}"
        return _action

    def skip():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('Skip') && b.getBoundingClientRect().width > 0)
            if (btn) btn.click()
        }""")
        return "Skipped."

    reroll_shortcuts = "!@#$%"
    items = []
    for i, c in enumerate(choices):
        shiny  = " ★" if c.get("is_shiny") else ""
        caught = " ✓" if c.get("is_caught") else ""
        types  = "/".join(c.get("types", []))
        label  = f"{c['name']}{shiny}{caught}  Lv{c['level']}  [{types}]"
        items.append(MenuItem(label, str(i + 1), pick(i)))

    for i, c in enumerate(choices):
        items.append(MenuItem(f"⟳ Reroll {c['name']}", reroll_shortcuts[i] if i < len(reroll_shortcuts) else "?", reroll(i)))

    items.append(MenuItem("Skip (flee)", "S", skip))

    def reload_page():
        page.reload()
        return "Page reloaded."

    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_pokemon_received_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    buttons = state.get("buttons", ["Continue"])

    def click_btn(text):
        def _action():
            page.evaluate("""(t) => {
                const btn = Array.from(document.querySelectorAll('.btn-primary, .btn-secondary'))
                    .filter(b => b.getBoundingClientRect().width > 0)
                    .find(b => b.textContent.trim() === t)
                if (btn) btn.click()
            }""", text)
            return f"Clicked: {text}"
        return _action

    def reload_page():
        page.reload()
        return "Page reloaded."

    shortcuts = "CTSK"
    items = [
        MenuItem(btn_text, shortcuts[i] if i < len(shortcuts) else "?", click_btn(btn_text))
        for i, btn_text in enumerate(buttons)
    ]
    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_trade_offer_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    members = state.get("members", [])

    def trade(idx):
        def _action():
            page.evaluate("(i) => document.querySelectorAll('.trade-member-row')[i]?.click()", idx)
            return f"Traded {members[idx]['name']}"
        return _action

    def decline():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Decline')
            if (btn) btn.click()
        }""")
        return "Declined trade."

    def reload_page():
        page.reload()
        return "Page reloaded."

    shortcuts = "123456789"
    items     = []
    for i, m in enumerate(members):
        types = "/".join(m.get("types", []))
        label = f"Trade {m['name']}  {m['level']}  [{types}]  → random +3 lvls"
        items.append(MenuItem(label, shortcuts[i] if i < len(shortcuts) else "?", trade(i)))

    items.append(MenuItem("Decline", "D", decline))
    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_battle_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    can_continue = state.get("can_continue", False)

    def do_continue():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('.btn-primary'))
                .find(b => b.textContent.trim().startsWith('Continue') && b.getBoundingClientRect().width > 0)
            if (btn) btn.click()
        }""")
        return "Continuing..."

    def reload_page():
        page.reload()
        return "Page reloaded."

    items = []
    if can_continue:
        items.append(MenuItem("Continue", "C", do_continue))

    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_item_equip_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    pokemon = state.get("pokemon", [])

    def equip_to(idx):
        def _action():
            row = page.locator(".equip-pokemon-row").nth(idx)
            btn = row.locator(".equip-btn")
            if btn.count() > 0:
                btn.first.click()
            else:
                row.click()
            name   = state["pokemon"][idx]["name"]
            action = state["pokemon"][idx]["action"] or "Used"
            return f"{action} on {name}"
        return _action

    def keep_in_bag():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button, .btn-primary, [class*="btn"]'))
                .filter(b => b.getBoundingClientRect().width > 0)
                .find(b => b.textContent.trim().toLowerCase().includes('keep'))
            if (btn) btn.click()
        }""")
        return "Kept in bag."

    def cancel():
        page.evaluate("""() => {
            const words = ['cancel', 'skip', 'close', 'back']
            const btn = Array.from(document.querySelectorAll('button, .btn-primary, [class*="btn"]'))
                .filter(b => b.getBoundingClientRect().width > 0)
                .find(b => words.some(w => b.textContent.trim().toLowerCase().includes(w)))
            if (btn) btn.click()
        }""")
        return "Cancelled."

    is_tutor        = state.get("is_move_tutor", False)
    has_keep_in_bag = state.get("has_keep_in_bag", True)
    shortcuts       = "123456789"
    items           = []
    for i, p in enumerate(pokemon):
        info   = p.get("info", "")
        action = p.get("action", "")
        if is_tutor:
            label = f"{p['name']}  {info}  {action}"
        elif action:
            held  = f"  (has: {p['held_item']})" if p.get("held_item") else ""
            label = f"{action} → {p['name']}  {info}{held}"
        else:
            label = f"Use on {p['name']}  {info}"
        items.append(MenuItem(label, shortcuts[i] if i < len(shortcuts) else "?", equip_to(i)))

    if has_keep_in_bag:
        items.append(MenuItem("Keep in Bag", "B", keep_in_bag))
        items.append(MenuItem("Cancel",      "C", cancel))
    else:
        items.append(MenuItem("Cancel", "C", cancel))

    def reload_page():
        page.reload()
        return "Page reloaded."

    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_item_select_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    choices = state.get("choices", [])

    def pick(idx):
        def _action():
            page.locator(".item-card").nth(idx).click()
            return f"Took {choices[idx]['name']}"
        return _action

    def skip():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Skip');
            if (btn) btn.click();
        }""")
        return "Skipped."

    items = []
    for i, c in enumerate(choices):
        label = f"{c['name']}  —  {c['description']}"
        items.append(MenuItem(label, str(i + 1), pick(i)))

    items.append(MenuItem("Skip", "S", skip))

    def reload_page():
        page.reload()
        return "Page reloaded."

    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_champion_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    def click_btn(text):
        def _action():
            page.evaluate("""(t) => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === t && b.getBoundingClientRect().width > 0)
                if (btn) btn.click()
            }""", text)
            return f"Clicked {text}"
        return _action

    def reload_page():
        page.reload()
        return "Page reloaded."

    return [
        MenuItem("Play Again",      "P", click_btn("Play Again")),
        MenuItem("Climb the Tower", "T", click_btn("🗼 Climb the Tower")),
        MenuItem("Hall of Fame",    "H", click_btn("🏛️ Hall of Fame")),
        MenuItem("Raw JSON",        "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page",     "R", reload_page),
        MenuItem("Quit",            "Q", lambda: "QUIT"),
    ]


def build_team_full_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    incoming = state.get("incoming", [])
    team     = state.get("team", [])
    shortcuts = "123456"

    def release(idx):
        def _action():
            page.evaluate("""(i) => {
                const screen = document.querySelector('.screen.active')
                const cards = Array.from(screen.querySelectorAll('.poke-card'))
                    .filter(c => !c.closest('.poke-choice-wrap'))
                if (cards[i]) cards[i].click()
            }""", idx)
            return f"Released {team[idx]['name']}"
        return _action

    def keep():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button,.btn-secondary'))
                .find(b => b.textContent.includes('Keep') && b.getBoundingClientRect().width > 0)
            if (btn) btn.click()
        }""")
        return "Kept team as-is."

    def reload_page():
        page.reload()
        return "Page reloaded."

    items = []
    for i, p in enumerate(team):
        lvl   = p.get("level", "")
        types = "  ".join(p.get("types", []))
        label = f"Release {p['name']}  {lvl}  {types}".strip()
        items.append(MenuItem(label, shortcuts[i] if i < len(shortcuts) else "?", release(i)))

    items += [
        MenuItem("Keep team as-is", "K", keep),
        MenuItem("Raw JSON",        "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page",     "P", reload_page),
        MenuItem("Quit",            "Q", lambda: "QUIT"),
    ]
    return items


def build_team_select_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    def reload_page():
        page.reload()
        return "Page reloaded."
    return [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]


def build_stage_select_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    stages = state.get("stages", [])
    shortcuts = "123456789"

    def click_stage(idx):
        def _action():
            page.evaluate("""(i) => {
                const btns = document.querySelectorAll('#stage-select-list button')
                if (btns[i]) btns[i].click()
            }""", idx)
            return f"Selected {stages[idx]['name']}"
        return _action

    def go_back():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('Back') && b.getBoundingClientRect().width > 0)
            if (btn) btn.click()
        }""")
        return "Going back..."

    def reload_page():
        page.reload()
        return "Page reloaded."

    items = []
    for i, s in enumerate(stages):
        label = f"{s['name']}  {s['gen']}"
        items.append(MenuItem(label, shortcuts[i] if i < len(shortcuts) else "?",
                              click_stage(i), enabled=s.get("enabled", True)))

    items += [
        MenuItem("← Back",      "B", go_back),
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


MENU_BUILDERS = {
    ScreenType.MAIN_MENU:        build_main_menu_items,
    ScreenType.STARTER_SELECT:   build_starter_select_items,
    ScreenType.MAP:              build_map_items,
    ScreenType.BATTLE:           build_battle_items,
    ScreenType.TRADE_OFFER:      build_trade_offer_items,
    ScreenType.POKEMON_RECEIVED: build_pokemon_received_items,
    ScreenType.CATCH_POKEMON:    build_catch_pokemon_items,
    ScreenType.ITEM_SELECT:      build_item_select_items,
    ScreenType.ITEM_EQUIP:       build_item_equip_items,
    ScreenType.CHAMPION:         build_champion_items,
    ScreenType.TEAM_FULL:        build_team_full_items,
    ScreenType.STAGE_SELECT:     build_stage_select_items,
    ScreenType.TEAM_SELECT:      build_team_select_items,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _execute(items: list[MenuItem], index: int) -> str:
    item = items[index]
    if not item.enabled:
        return f"{item.label} is not available."
    try:
        return item.action() or ""
    except Exception as e:
        return f"Error: {e}"


def _fallback_items(refresh_fn: Callable, page=None) -> list[MenuItem]:
    def reload_page():
        if page:
            page.reload()
        return "Page reloaded."

    return [
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]


def _unknown_state(page, screen: ScreenType) -> dict:
    try:
        dom_info = page.evaluate("""() => {
            const vis = el => el && el.getBoundingClientRect().width > 0
            const allClasses = new Set()
            document.querySelectorAll('*').forEach(el => {
                el.classList.forEach(c => allClasses.add(c))
            })
            const visibleText = Array.from(document.querySelectorAll('h1,h2,h3,.title,.header,[class*="title"],[class*="header"]'))
                .filter(vis).map(el => el.textContent.trim()).filter(Boolean).slice(0, 10)
            const visibleBtns = Array.from(document.querySelectorAll('button,.btn-primary'))
                .filter(vis).map(el => el.textContent.trim()).filter(Boolean).slice(0, 10)
            return { classes: [...allClasses].sort(), headings: visibleText, buttons: visibleBtns }
        }""")
    except Exception:
        dom_info = {}
    return {"screen": "unknown", "title": page.title(), "url": page.url, "dom": dom_info}


def _dom_hash(page, screen: ScreenType) -> str:
    """Cheap single JS call that returns a string summarising visible DOM state.
    If the hash is identical to the previous cycle we skip a full parse."""
    try:
        return page.evaluate("""() => {
            const q  = s => document.querySelector(s)
            const hp = q('.hp-bar-fill')?.getAttribute('style') || ''
            const sl = q('.team-slot-name')?.innerText || ''
            const bt = q('.battle-header')?.innerText || ''
            const nd = document.querySelectorAll('.screen.active svg g').length
            const it = document.querySelectorAll('.screen.active .item-card').length
            const pc = document.querySelectorAll('.screen.active .poke-choice-wrap').length
            const bh = Array.from(document.querySelectorAll('.battle-pokemon .hp-text')).map(e => e.innerText).join('|')
            const ba = Array.from(document.querySelectorAll('.battle-pokemon')).map(e => e.className).join('|')
            return `${hp}|${sl}|${bt}|${nd}|${it}|${pc}|${bh}|${ba}`
        }""")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Type palette
# ---------------------------------------------------------------------------

TYPE_COLORS: dict[str, str] = {
    "Normal":   "#aaaaaa", "Fire":     "#ff7722", "Water":    "#4488ff",
    "Grass":    "#44cc55", "Electric": "#ffdd11", "Ice":      "#55dddd",
    "Fighting": "#cc3322", "Poison":   "#aa33bb", "Ground":   "#ddaa33",
    "Flying":   "#8899ee", "Psychic":  "#ff3377", "Bug":      "#99bb22",
    "Rock":     "#bbaa55", "Ghost":    "#6644aa", "Dragon":   "#6633ff",
    "Dark":     "#664433", "Steel":    "#99aabb", "Fairy":    "#ff88cc",
}


# ---------------------------------------------------------------------------
# Pokémon card (catch screen)
# ---------------------------------------------------------------------------

class PokemonCard(Widget):
    """Rich stat card for one catchable Pokémon."""

    can_focus = False

    DEFAULT_CSS = """
    PokemonCard {
        width: 1fr;
        height: 1fr;
        border: round #3a3a5a;
        background: #0f0f22;
        padding: 1 2;
        margin: 0 1;
        layout: vertical;
    }
    PokemonCard.selected { border: round #f5c518; background: #18183a; }
    PokemonCard.shiny    { border: round #ffdd22; }

    .card-shortcut { color: #f5c518; text-style: bold; margin-bottom: 1; }
    .card-name     { color: #e8e8ff; text-style: bold; }
    .card-caught   { color: #00e676; }
    .card-level    { color: #555577; margin-bottom: 1; }

    .card-types  { height: 1; margin-bottom: 1; }
    .type-badge  {
        width: auto; height: 1; padding: 0 1; margin-right: 1;
        text-style: bold; content-align: center middle;
    }
    .type-normal   { color: #aaaaaa; background: #2a2a2a; }
    .type-fire     { color: #ff7722; background: #2a1000; }
    .type-water    { color: #4488ff; background: #00082a; }
    .type-grass    { color: #44cc55; background: #002a0a; }
    .type-electric { color: #ffdd11; background: #2a2200; }
    .type-ice      { color: #55dddd; background: #002a2a; }
    .type-fighting { color: #cc3322; background: #2a0800; }
    .type-poison   { color: #aa33bb; background: #1a0022; }
    .type-ground   { color: #ddaa33; background: #2a1a00; }
    .type-flying   { color: #8899ee; background: #0a1030; }
    .type-psychic  { color: #ff3377; background: #2a0015; }
    .type-bug      { color: #99bb22; background: #1a2200; }
    .type-rock     { color: #bbaa55; background: #1a1500; }
    .type-ghost    { color: #6644aa; background: #10001a; }
    .type-dragon   { color: #6633ff; background: #0d0030; }
    .type-dark     { color: #997766; background: #1a1000; }
    .type-steel    { color: #99aabb; background: #101520; }
    .type-fairy    { color: #ff88cc; background: #2a0018; }

    .card-hp    { margin-bottom: 1; }
    .hp-ok  { color: #00e676; }
    .hp-mid { color: #f5c518; }
    .hp-low { color: #ff1744; }

    .card-stats { height: 3; margin-bottom: 1; }
    .stat-col   { width: auto; margin-right: 3; align: center top; }
    .stat-val   { color: #e8e8ff; text-style: bold; text-align: center; }
    .stat-key   { color: #555577; text-align: center; }

    .card-move      { color: #9999bb; margin-top: 1; }
    .move-type-badge {
        width: auto; height: 1; padding: 0 1; margin-top: 0; text-style: bold;
    }
    /* move-type-badge inherits .type-* colours above */
    PokemonCard.recommended { border: round #00e676; }
    .card-rec { color: #00e676; text-style: bold; margin-bottom: 1; }
    """

    def __init__(self, choice: dict, shortcut: str, is_selected: bool,
                 is_recommended: bool = False) -> None:
        super().__init__()
        self._choice         = choice
        self._shortcut       = shortcut
        self._is_recommended = is_recommended
        if is_selected:
            self.add_class("selected")
        if is_recommended:
            self.add_class("recommended")
        if choice.get("is_shiny"):
            self.add_class("shiny")

    def compose(self) -> ComposeResult:
        c = self._choice

        if self._is_recommended:
            yield Label("▲ REC", classes="card-rec")
        shiny_tag = "  ★ SHINY" if c.get("is_shiny") else ""
        yield Label(f"[ {self._shortcut} ]{shiny_tag}", classes="card-shortcut")

        caught = "  ✓" if c.get("is_caught") else ""
        yield Label(f"{c['name']}{caught}", classes="card-name")
        yield Label(f"Level  {c.get('level', '?')}", classes="card-level")

        types = c.get("types", [])
        if types:
            with Horizontal(classes="card-types"):
                for t in types:
                    yield Label(t, classes=f"type-badge type-{t.lower()}")

        hp_cur = c.get("hp_current")
        hp_max = c.get("hp_max")
        if hp_cur is not None and hp_max:
            pct    = hp_cur / hp_max
            filled = round(pct * 9)
            bar    = "█" * filled + "░" * (9 - filled)
            hp_cls = "hp-low" if pct < 0.2 else "hp-mid" if pct < 0.5 else "hp-ok"
            yield Label(f"{bar}  {hp_cur}/{hp_max}", classes=f"card-hp {hp_cls}")

        stats = c.get("stats", {})
        if stats:
            with Horizontal(classes="card-stats"):
                for stat, val in list(stats.items())[:6]:
                    with Vertical(classes="stat-col"):
                        yield Label(str(val),          classes="stat-val")
                        yield Label(stat[:4].upper(),  classes="stat-key")

        move = c.get("move", {})
        if move.get("name"):
            cat_icon = {"physical": "⚔", "special": "✦", "status": "◈"}.get(
                move.get("category", "").lower(), "·"
            )
            pwr = f"  PWR {move['power']}" if move.get("power") else ""
            yield Label(f"{cat_icon}  {move['name']}{pwr}", classes="card-move")
            if move.get("type"):
                yield Label(
                    move["type"],
                    classes=f"move-type-badge type-{move['type'].lower()}",
                )

    def set_selected(self, value: bool) -> None:
        self.set_class(value, "selected")

    def set_recommended(self, value: bool) -> None:
        self._is_recommended = value
        self.set_class(value, "recommended")


class CatchPokemonPanel(Widget):
    """Horizontal row of PokémonCards + a compact action strip below."""

    can_focus = False

    DEFAULT_CSS = """
    CatchPokemonPanel {
        layout: vertical;
        height: 1fr;
    }
    #catch-cards { layout: horizontal; height: 1fr; }
    #catch-rerolls {
        layout: horizontal;
        height: 3;
        padding: 0 1;
    }
    .reroll-cell {
        width: 1fr;
        height: 3;
        margin: 0 1;
        border: round #2a2a4a;
        background: #0f0f22;
        content-align: center middle;
        color: #555577;
        text-align: center;
    }
    .reroll-cell.active {
        border: round #f5c518;
        color: #f5c518;
        background: #18183a;
    }
    #catch-strip {
        height: 5;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #1e1e3a;
        align: left middle;
    }
    #catch-strip ActionItem {
        width: auto;
        min-width: 16;
        margin-right: 1;
    }
    #catch-strip ActionItem > .item-label {
        width: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Horizontal(id="catch-cards")
        yield Horizontal(id="catch-rerolls")
        yield Horizontal(id="catch-strip")

    def rebuild(self, choices: list, strip_items: list[MenuItem], selected: int,
                recommended_idx: int | None = None,
                reroll_items: list | None = None) -> None:
        shortcuts = "123456789"
        n = len(choices)

        # Cards row
        cards_row = self.query_one("#catch-cards")
        existing  = list(cards_row.query(PokemonCard))
        same_data = (
            len(existing) == n
            and all(e._choice.get("name") == c.get("name") for e, c in zip(existing, choices))
        )
        if same_data:
            for i, card in enumerate(existing):
                card.set_selected(i == selected)
                card.set_recommended(i == recommended_idx)
        else:
            cards_row.query(PokemonCard).remove()
            cards_row.mount(*[
                PokemonCard(c, shortcuts[i] if i < len(shortcuts) else "?",
                            i == selected, i == recommended_idx)
                for i, c in enumerate(choices)
            ])

        # Reroll row — one cell per card, highlighted when that reroll slot is selected
        reroll_row = self.query_one("#catch-rerolls")
        existing_cells = list(reroll_row.query(".reroll-cell"))
        reroll_selected = (selected - n) if reroll_items and n <= selected < n * 2 else None
        if len(existing_cells) == n:
            for i, cell in enumerate(existing_cells):
                cell.set_class(i == reroll_selected, "active")
        else:
            reroll_row.query(".reroll-cell").remove()
            cells = []
            for i in range(n):
                cell = Static("⟳  Reroll", classes="reroll-cell")
                cells.append(cell)
            reroll_row.mount(*cells)

        # Strip: compact action buttons (Skip, JSON, Quit …)
        strip_row = self.query_one("#catch-strip")
        strip_existing = list(strip_row.query(ActionItem))
        strip_offset = n * 2

        if len(strip_existing) == len(strip_items):
            for i, item in enumerate(strip_existing):
                item.refresh_state(strip_items[i], (strip_offset + i) == selected)
        else:
            strip_row.query(ActionItem).remove()
            strip_row.mount(*[
                ActionItem(item, (strip_offset + i) == selected)
                for i, item in enumerate(strip_items)
            ])


# ---------------------------------------------------------------------------
# Battle screen widgets
# ---------------------------------------------------------------------------

class BattleCard(Widget):
    """One pokémon row in the battle screen."""

    DEFAULT_CSS = """
    BattleCard {
        width: 1fr;
        height: auto;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        margin-bottom: 1;
    }
    BattleCard.active  { border: round #00d7d7; }
    BattleCard.fainted { border: round #333344; background: #090912; }
    .bc-header { layout: horizontal; height: 1; }
    .bc-icon   { width: 3; content-align: center middle; color: #00d7d7; }
    .bc-name   { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .bc-level  { width: 8; color: #555577; content-align: right middle; }
    .bc-hp-ok  { color: #00e676; }
    .bc-hp-mid { color: #f5c518; }
    .bc-hp-low { color: #ff1744; }
    .bc-faint  { color: #333355; }
    """

    def __init__(self, p: dict) -> None:
        super().__init__()
        self._p = p
        if p.get("is_active"):
            self.add_class("active")
        if p.get("is_fainted"):
            self.add_class("fainted")

    def compose(self) -> ComposeResult:
        p    = self._p
        icon = "◉" if p.get("is_active") else "·"
        with Horizontal(classes="bc-header"):
            yield Label(icon,                          classes="bc-icon")
            yield Label(p.get("name", "?"),            classes="bc-name")
            lv = p.get("level")
            yield Label(f"Lv{lv}" if lv else "",      classes="bc-level")
        if p.get("is_fainted"):
            yield Label("✕  fainted", classes="bc-faint")
        else:
            hp_cur = p.get("hp_current")
            hp_max = p.get("hp_max")
            if hp_cur is not None and hp_max:
                pct    = hp_cur / hp_max
                filled = round(pct * 10)
                bar    = "█" * filled + "░" * (10 - filled)
                hp_cls = "bc-hp-low" if pct < 0.2 else "bc-hp-mid" if pct < 0.5 else "bc-hp-ok"
                yield Label(f"{bar}  {hp_cur}/{hp_max}", classes=hp_cls)


class BattleSidePanel(Widget):
    """One side's team in the battle screen."""

    can_focus = False

    DEFAULT_CSS = """
    BattleSidePanel {
        width: 1fr;
        height: 1fr;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        layout: vertical;
        margin-right: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    BattleSidePanel:last-of-type { margin-right: 0; }
    .bs-row { layout: horizontal; height: 1fr; margin-bottom: 1; }
    .bs-row:last-of-type { margin-bottom: 0; }
    .bs-gap { width: 1; }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self.border_title = title

    def compose(self) -> ComposeResult:
        for _ in range(3):
            yield Horizontal(classes="bs-row")

    def rebuild(self, team: list) -> None:
        for ri, row in enumerate(self.query(".bs-row")):
            row.query(BattleCard).remove()
            row.query(Label).remove()
            left  = team[ri * 2]     if ri * 2     < len(team) else None
            right = team[ri * 2 + 1] if ri * 2 + 1 < len(team) else None
            children: list = []
            if left is not None:
                children.append(BattleCard(left))
            if left is not None and right is not None:
                children.append(Label(" ", classes="bs-gap"))
            if right is not None:
                children.append(BattleCard(right))
            if children:
                row.mount(*children)


class BattlePanel(Widget):
    """Full battle layout: your team left, rival right, action strip below."""

    can_focus = False

    DEFAULT_CSS = """
    BattlePanel {
        layout: vertical;
        height: 1fr;
        padding: 0 1 1 1;
    }
    #battle-sides {
        layout: horizontal;
        height: 1fr;
    }
    #battle-strip {
        height: 5;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #1e1e3a;
        align: left middle;
    }
    #battle-strip ActionItem {
        width: auto;
        min-width: 14;
        margin-right: 1;
    }
    #battle-strip ActionItem > .item-label { width: auto; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="battle-sides"):
            yield BattleSidePanel("YOUR TEAM")
            yield BattleSidePanel("RIVAL")
        yield Horizontal(id="battle-strip")

    def rebuild(self, your_team: list, enemy: list, items: list, selected: int) -> None:
        panels = list(self.query(BattleSidePanel))
        if panels:
            panels[0].rebuild(your_team)
        if len(panels) > 1:
            panels[1].rebuild(enemy)

        strip    = self.query_one("#battle-strip")
        existing = list(strip.query(ActionItem))
        if len(existing) == len(items):
            for i, w in enumerate(existing):
                w.refresh_state(items[i], i == selected)
        else:
            strip.query(ActionItem).remove()
            strip.mount(*[
                ActionItem(item, i == selected)
                for i, item in enumerate(items)
            ])


# ---------------------------------------------------------------------------
# Main menu screen widgets
# ---------------------------------------------------------------------------

_MODE_DESC = {
    "Normal Mode":  "Classic roguelike, no restrictions",
    "Nuzlocke":     "Fainted Pokémon are permanently lost",
    "Battle Tower": "Consecutive battle challenge",
}


class GameModeCard(Widget):
    """One game-mode option card — Normal / Nuzlocke / Battle Tower."""

    DEFAULT_CSS = """
    GameModeCard {
        width: 1fr;
        height: 1fr;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 2;
        layout: vertical;
        margin-bottom: 1;
    }
    GameModeCard:last-of-type { margin-bottom: 0; }
    GameModeCard.selected { border: round #f5c518; background: #16140a; }
    .gmc-row  { layout: horizontal; height: 1; }
    .gmc-key  { width: 4; color: #f5c518; text-style: bold; content-align: center middle; }
    .gmc-name { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .gmc-desc { color: #555577; margin-top: 1; }
    """

    def __init__(self, item: MenuItem, is_selected: bool) -> None:
        super().__init__()
        self._item = item
        if is_selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="gmc-row"):
            yield Label(Text(f"[{self._item.shortcut}]"), classes="gmc-key")
            yield Label(self._item.label,               classes="gmc-name")
        yield Label(_MODE_DESC.get(self._item.label, ""), classes="gmc-desc")

    def set_selected(self, value: bool) -> None:
        self.set_class(value, "selected")


class RightColCard(Widget):
    """Compact right-column card for gen/starter selection."""

    DEFAULT_CSS = """
    RightColCard {
        width: 1fr;
        height: 3;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 2;
        layout: horizontal;
        align: left middle;
    }
    RightColCard.focused { border: round #f5c518; background: #16140a; }
    RightColCard.active  { border: round #00d7d7; background: #001825; }
    .rcc-key   { width: 4; color: #f5c518; text-style: bold; content-align: center middle; }
    .rcc-label { width: 1fr; content-align: left middle; }
    """

    def __init__(self, shortcut: str, label: str, label_markup: str = "",
                 is_focused: bool = False, is_active: bool = False,
                 display_key: str = "") -> None:
        super().__init__()
        self._shortcut     = shortcut
        self._label        = label
        self._label_markup = label_markup
        self._display_key  = display_key or shortcut
        if is_focused: self.add_class("focused")
        if is_active:  self.add_class("active")

    def compose(self) -> ComposeResult:
        yield Label(Text(f"[{self._display_key}]"), classes="rcc-key")
        markup = self._label_markup or self._label
        yield Label(Text.from_markup(markup), classes="rcc-label")

    def set_focused(self, value: bool) -> None:
        self.set_class(value, "focused")

    def set_active(self, value: bool) -> None:
        self.set_class(value, "active")

    def update_label(self, markup: str) -> None:
        try:
            self.query_one(".rcc-label", Label).update(Text.from_markup(markup))
        except Exception:
            pass


class MainMenuPanel(Widget):
    """Rich main-menu layout: mode cards (left) + right column (gens+starters) + strip."""

    can_focus = False

    DEFAULT_CSS = """
    MainMenuPanel {
        layout: vertical;
        height: 1fr;
        padding: 0 1 1 1;
    }
    #mm-body  { layout: horizontal; height: 1fr; }
    #mm-modes { width: 1fr; height: 1fr; layout: vertical; margin-right: 1; }
    #mm-right {
        width: 28;
        height: 1fr;
        layout: vertical;
    }
    #mm-user {
        height: auto;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 2;
        margin-bottom: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    #mm-right-items { height: 1fr; layout: vertical; }
    .mm-section-hdr {
        height: 1;
        color: #555577;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
    }
    #mm-gen-hdr { margin-top: 0; }
    #mm-strip {
        height: 5;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #1e1e3a;
        align: left middle;
    }
    #mm-strip ActionItem       { width: auto; min-width: 12; margin-right: 1; }
    #mm-strip ActionItem > .item-label { width: auto; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="mm-body"):
            with Vertical(id="mm-modes"):
                pass
            with Vertical(id="mm-right"):
                yield Static("", id="mm-user")
                yield Vertical(id="mm-right-items")
        yield Horizontal(id="mm-strip")

    def rebuild(self, state: dict, items: list, selected: int,
                selected_starter: int, starters: list) -> None:
        n_modes    = 3
        gens       = state.get("available_gens", [])
        n_gens     = len(gens)
        n_starters = len(starters)
        n_right    = n_gens + n_starters
        active_gen = state.get("selected_gen")

        # ── Mode cards (left) ─────────────────────────────────────────
        modes_col  = self.query_one("#mm-modes")
        mode_items = items[:n_modes]
        existing   = list(modes_col.query(GameModeCard))
        if len(existing) == len(mode_items):
            for i, card in enumerate(existing):
                card.set_selected(i == selected)
        else:
            modes_col.query(GameModeCard).remove()
            modes_col.mount(*[
                GameModeCard(item, i == selected)
                for i, item in enumerate(mode_items)
            ])

        # ── User panel ────────────────────────────────────────────────
        user  = state.get("logged_in_user") or "not logged in"
        u_pan = self.query_one("#mm-user", Static)
        u_pan.border_title = "PLAYER"
        u_pan.update(Text.from_markup(
            f"[dim]logged in as[/]\n[bold #00e676]{user}[/]"
        ))

        def gen_markup(g: str) -> str:
            return f"[bold #00d7d7]GEN {g}[/]" if g == active_gen else f"[#e8e8ff]GEN {g}[/]"

        def starter_markup(letter: str, color: str, is_sel: bool) -> str:
            return f"[bold {color}]★  {letter}[/]" if is_sel else f"[#666688]{letter}[/]"

        # ── Right column: section headers + gen cards + starter cards ─
        right_col   = self.query_one("#mm-right-items")
        existing_rc = list(right_col.query(RightColCard))

        if len(existing_rc) == n_right:
            # In-place update — no remount
            for i, card in enumerate(existing_rc):
                is_focused = (n_modes + i) == selected
                card.set_focused(is_focused)
                if i < n_gens:
                    g = gens[i]
                    card.set_active(g == active_gen and not is_focused)
                    card.update_label(gen_markup(g))
                else:
                    si = i - n_gens
                    letter, color = starters[si]
                    is_sel = si == selected_starter
                    card.set_active(is_sel and not is_focused)
                    card.update_label(starter_markup(letter, color, is_sel))
        else:
            right_col.query(RightColCard).remove()
            right_col.query(Label).remove()
            widgets: list = [
                Label("GENERATION", id="mm-gen-hdr", classes="mm-section-hdr"),
            ]
            for i, g in enumerate(gens):
                is_focused = (n_modes + i) == selected
                widgets.append(RightColCard(
                    ROMAN.get(g, g), f"Gen {g}", gen_markup(g),
                    is_focused=is_focused,
                    is_active=(g == active_gen and not is_focused),
                    display_key=ROMAN.get(g, g),
                ))
            widgets.append(Label("STARTER", id="mm-str-hdr", classes="mm-section-hdr"))
            _str_display   = ["7", "8", "9"]
            _str_shortcuts = ["7", "8", "9"]
            for si, (letter, color) in enumerate(starters):
                i          = n_gens + si
                is_focused = (n_modes + i) == selected
                is_sel     = si == selected_starter
                widgets.append(RightColCard(
                    _str_shortcuts[si] if si < len(_str_shortcuts) else "?",
                    f"Starter {letter}",
                    starter_markup(letter, color, is_sel),
                    is_focused=is_focused,
                    is_active=(is_sel and not is_focused),
                    display_key=_str_display[si] if si < len(_str_display) else "?",
                ))
            right_col.mount(*widgets)

        # ── Strip ─────────────────────────────────────────────────────
        strip_offset = n_modes + n_right
        strip_items  = items[strip_offset:]
        strip        = self.query_one("#mm-strip")
        existing_ai  = list(strip.query(ActionItem))
        sel_in_strip = selected - strip_offset
        if len(existing_ai) == len(strip_items):
            for i, w in enumerate(existing_ai):
                w.refresh_state(strip_items[i], i == sel_in_strip)
        else:
            strip.query(ActionItem).remove()
            strip.mount(*[
                ActionItem(item, i == sel_in_strip)
                for i, item in enumerate(strip_items)
            ])


# ---------------------------------------------------------------------------
# Item select screen widgets
# ---------------------------------------------------------------------------

class ItemSelectCard(Widget):
    """One item choice card in the item select screen."""

    DEFAULT_CSS = """
    ItemSelectCard {
        width: 1fr;
        height: 1fr;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 1 2;
        layout: vertical;
    }
    ItemSelectCard.selected     { border: round #f5c518; background: #16163a; }
    ItemSelectCard.recommended  { border: round #00e676; }
    .isc-shortcut { color: #f5c518; text-style: bold; margin-bottom: 1; }
    .isc-name     { color: #e8e8ff; text-style: bold; margin-bottom: 1; }
    .isc-desc     { color: #9999bb; }
    .isc-rec      { color: #00e676; text-style: bold; margin-bottom: 1; }
    """

    def __init__(self, choice: dict, shortcut: str, is_selected: bool,
                 is_recommended: bool = False) -> None:
        super().__init__()
        self._choice        = choice
        self._shortcut      = shortcut
        self._is_recommended = is_recommended
        if is_selected:
            self.add_class("selected")
        if is_recommended:
            self.add_class("recommended")

    def compose(self) -> ComposeResult:
        c = self._choice
        if self._is_recommended:
            yield Label("▲ REC", classes="isc-rec")
        yield Label(f"[ {self._shortcut} ]", classes="isc-shortcut")
        yield Label(c.get("name", "?"),       classes="isc-name")
        yield Label(c.get("description", ""), classes="isc-desc")

    def set_selected(self, value: bool) -> None:
        self.set_class(value, "selected")

    def set_recommended(self, value: bool) -> None:
        self.set_class(value, "recommended")


class ItemSelectPanel(Widget):
    """Horizontal row of ItemSelectCards + a compact action strip below."""

    can_focus = False

    DEFAULT_CSS = """
    ItemSelectPanel {
        layout: vertical;
        height: 1fr;
        padding: 0 1 1 1;
    }
    #item-cards { layout: horizontal; height: 1fr; }
    #item-strip {
        height: 5;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #1e1e3a;
        align: left middle;
    }
    #item-strip ActionItem {
        width: auto;
        min-width: 14;
        margin-right: 1;
    }
    #item-strip ActionItem > .item-label { width: auto; }
    """

    def compose(self) -> ComposeResult:
        yield Horizontal(id="item-cards")
        yield Horizontal(id="item-strip")

    def rebuild(self, choices: list, strip_items: list, selected: int,
                recommended_idx: int | None = None) -> None:
        shortcuts = "123456789"
        cards_row = self.query_one("#item-cards")
        existing  = list(cards_row.query(ItemSelectCard))

        same_data = (
            len(existing) == len(choices)
            and all(e._choice.get("name") == c.get("name") for e, c in zip(existing, choices))
        )
        if same_data:
            for i, card in enumerate(existing):
                card.set_selected(i == selected)
                card.set_recommended(i == recommended_idx)
        else:
            cards_row.query(ItemSelectCard).remove()
            cards_row.mount(*[
                ItemSelectCard(c, shortcuts[i] if i < len(shortcuts) else "?",
                               i == selected, i == recommended_idx)
                for i, c in enumerate(choices)
            ])

        strip    = self.query_one("#item-strip")
        existing = list(strip.query(ActionItem))
        offset   = len(choices)
        if len(existing) == len(strip_items):
            for i, w in enumerate(existing):
                w.refresh_state(strip_items[i], (offset + i) == selected)
        else:
            strip.query(ActionItem).remove()
            strip.mount(*[
                ActionItem(item, (offset + i) == selected)
                for i, item in enumerate(strip_items)
            ])


# ---------------------------------------------------------------------------
# Team full screen widgets
# ---------------------------------------------------------------------------

class TeamMemberCard(Widget):
    """One team member slot in the team-full release screen."""

    DEFAULT_CSS = """
    TeamMemberCard {
        width: 1fr;
        height: 1fr;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        layout: vertical;
    }
    TeamMemberCard.selected { border: round #ff4455; background: #1a0a0a; }
    .tmc-header { layout: horizontal; height: 1; }
    .tmc-key    { width: 4; color: #f5c518; text-style: bold; content-align: center middle; }
    .tmc-name   { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .tmc-level  { width: 8; color: #555577; content-align: right middle; }
    .tmc-types  { layout: horizontal; height: 1; }
    .tmc-type   { width: auto; height: 1; padding: 0 1; margin-right: 1; text-style: bold; }
    """

    def __init__(self, p: dict, shortcut: str, is_selected: bool) -> None:
        super().__init__()
        self._p        = p
        self._shortcut = shortcut
        if is_selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        p = self._p
        with Horizontal(classes="tmc-header"):
            yield Label(f"[{self._shortcut}]",       classes="tmc-key")
            yield Label(p.get("name", "?"),           classes="tmc-name")
            yield Label(p.get("level", ""),           classes="tmc-level")
        types = p.get("types", [])
        if types:
            with Horizontal(classes="tmc-types"):
                for t in types:
                    yield Label(t, classes=f"tmc-type type-{t.lower()}")

    def set_selected(self, value: bool) -> None:
        self.set_class(value, "selected")


class TeamFullPanel(Widget):
    """Team-full layout: incoming pokemon row + 2×3 team grid + action strip."""

    can_focus = False

    DEFAULT_CSS = """
    TeamFullPanel {
        layout: vertical;
        height: 1fr;
        padding: 0 1 1 1;
    }
    #tf-incoming {
        layout: horizontal;
        height: auto;
        padding: 0 0 1 0;
    }
    #tf-incoming-label {
        width: 1fr;
        height: 3;
        color: #555577;
        content-align: center middle;
        text-style: bold;
        border-bottom: solid #1e1e3a;
    }
    #tf-grid {
        layout: vertical;
        height: 1fr;
    }
    .tf-row { layout: horizontal; height: 1fr; margin-bottom: 1; }
    .tf-row:last-of-type { margin-bottom: 0; }
    .tf-gap { width: 1; }
    #tf-strip {
        height: 5;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #1e1e3a;
        align: left middle;
    }
    #tf-strip ActionItem {
        width: auto;
        min-width: 14;
        margin-right: 1;
    }
    #tf-strip ActionItem > .item-label { width: auto; }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="tf-incoming-label")
        with Vertical(id="tf-grid"):
            yield Horizontal(classes="tf-row")
            yield Horizontal(classes="tf-row")
        yield Horizontal(id="tf-strip")

    def rebuild(self, incoming: list, team: list, items: list, selected: int) -> None:
        # Incoming label
        names = "  ·  ".join(
            f"{p['name']} {p.get('level','')}" + (" ★" if p.get("is_shiny") else "")
            for p in incoming
        )
        self.query_one("#tf-incoming-label", Label).update(
            f"[dim]Incoming:[/]  [bold #e8e8ff]{names}[/]"
        )

        # Team grid: row 0 → slots 0-2, row 1 → slots 3-5
        shortcuts = "123456"
        for ri, row in enumerate(self.query(".tf-row")):
            row.query(TeamMemberCard).remove()
            row.query(Label).remove()
            children: list = []
            for ci in range(3):
                slot = ri * 3 + ci
                if slot < len(team):
                    is_sel = slot == selected
                    children.append(TeamMemberCard(team[slot], shortcuts[slot], is_sel))
                if ci < 2:
                    children.append(Label(" ", classes="tf-gap"))
            if children:
                row.mount(*children)

        # Action strip
        strip    = self.query_one("#tf-strip")
        existing = list(strip.query(ActionItem))
        offset   = len(team)
        if len(existing) == len(items):
            for i, w in enumerate(existing):
                w.refresh_state(items[i], (offset + i) == selected)
        else:
            strip.query(ActionItem).remove()
            strip.mount(*[
                ActionItem(item, (offset + i) == selected)
                for i, item in enumerate(items)
            ])


# ---------------------------------------------------------------------------
# Map screen widgets
# ---------------------------------------------------------------------------

TYPE_EMOJI: dict[str, str] = {
    "Normal":   "⬜", "Fire":     "🔥", "Water":    "💧",
    "Grass":    "🌿", "Electric": "⚡", "Ice":      "❄️",
    "Fighting": "👊", "Poison":   "☠️", "Ground":   "🌍",
    "Flying":   "🌀", "Psychic":  "🔮", "Bug":      "🐛",
    "Rock":     "🪨", "Ghost":    "👻", "Dragon":   "🐲",
    "Dark":     "🌑", "Steel":    "⚙️", "Fairy":    "🌸",
}

NODE_META: dict[str, tuple[str, str]] = {
    "trainer":        ("⊗",  "#ff4455"),
    "boss":           ("♛",  "#f5c518"),
    "wild_encounter": ("◈",  "#44cc55"),
    "catch_pokemon":  ("○",  "#ffaa22"),
    "pokecenter":     ("♥",  "#ff88cc"),
    "shop":           ("◆",  "#4488ff"),
    "item":           ("★",  "#ffdd11"),
    "move_tutor":     ("✦",  "#aa44ff"),
    "mystery":        ("?",  "#00dddd"),
    "trade":          ("⇌",  "#55ddaa"),
    "start":          ("◉",  "#888888"),
}


# ---------------------------------------------------------------------------
# MAP lattice constants
# ---------------------------------------------------------------------------

_ROW_SIZES  = [1, 2, 3, 4, 3, 4, 3, 2, 1]
_STEP       = 4
_ROW_OFFSET = [(4 - n) * 2 for n in _ROW_SIZES]   # [6,4,2,0,2,0,2,4,6]
_GRID_W     = 15   # 0..14 (extra room for emoji to the right of nodes)
_GRID_H     = 17   # 9 node rows + 8 connector rows

# Map node index (0-22) → (grid_y, grid_x)
_NODE_GRID_POS: list[tuple[int, int]] = []
for _r, _sz in enumerate(_ROW_SIZES):
    for _c in range(_sz):
        _NODE_GRID_POS.append((_r * 2, _ROW_OFFSET[_r] + _c * _STEP))

# Map (row, col) → node index
_ROW_COL_TO_IDX: list[list[int]] = []
_idx = 0
for _r, _sz in enumerate(_ROW_SIZES):
    _row_idxs = []
    for _c in range(_sz):
        _row_idxs.append(_idx)
        _idx += 1
    _ROW_COL_TO_IDX.append(_row_idxs)


# Pre-compute connectors: (grid_y, grid_x, char, top_node_idx, bottom_node_idx)
def _lattice_connectors() -> list[tuple[int, int, str, int, int]]:
    out = []
    for r in range(len(_ROW_SIZES) - 1):
        sc, nc = _ROW_SIZES[r], _ROW_SIZES[r + 1]
        expanding = nc > sc
        for c in range(sc):
            sx = _ROW_OFFSET[r] + c * _STEP
            if expanding:
                targets = [c, c + 1]
            else:
                targets = sorted({max(0, c - 1), min(nc - 1, c)})
            for c2 in targets:
                dx = _ROW_OFFSET[r + 1] + c2 * _STEP
                cx = (sx + dx) // 2
                cy = r * 2 + 1
                ch = "/" if dx < sx else "\\" if dx > sx else "|"
                out.append((cy, cx, ch, _ROW_COL_TO_IDX[r][c], _ROW_COL_TO_IDX[r + 1][c2]))
    return out

_CONNECTORS = _lattice_connectors()

_NODE_SCORE: dict[str, float] = {
    "trainer": 2.0, "wild_encounter": 1.0, "mystery": 0.5,
    "move_tutor": 0.25, "item": 0.1,
}

_TYPE_CHART: dict[str, dict[str, float]] = {
    "Normal":   {"Normal":1,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":1,"Fighting":1,"Poison":1,"Ground":1,"Flying":1,"Psychic":1,"Bug":1,"Rock":0.5,"Ghost":0,"Dragon":1,"Dark":1,"Steel":0.5},
    "Fire":     {"Normal":1,"Fire":0.5,"Water":0.5,"Electric":1,"Grass":2,"Ice":2,"Fighting":1,"Poison":1,"Ground":1,"Flying":1,"Psychic":1,"Bug":2,"Rock":0.5,"Ghost":1,"Dragon":0.5,"Dark":1,"Steel":2},
    "Water":    {"Normal":1,"Fire":2,"Water":0.5,"Electric":1,"Grass":0.5,"Ice":1,"Fighting":1,"Poison":1,"Ground":2,"Flying":1,"Psychic":1,"Bug":1,"Rock":2,"Ghost":1,"Dragon":0.5,"Dark":1,"Steel":1},
    "Electric": {"Normal":1,"Fire":1,"Water":2,"Electric":0.5,"Grass":0.5,"Ice":1,"Fighting":1,"Poison":1,"Ground":0,"Flying":2,"Psychic":1,"Bug":1,"Rock":1,"Ghost":1,"Dragon":0.5,"Dark":1,"Steel":1},
    "Grass":    {"Normal":1,"Fire":0.5,"Water":2,"Electric":1,"Grass":0.5,"Ice":1,"Fighting":1,"Poison":0.5,"Ground":2,"Flying":0.5,"Psychic":1,"Bug":0.5,"Rock":2,"Ghost":1,"Dragon":0.5,"Dark":1,"Steel":0.5},
    "Ice":      {"Normal":1,"Fire":0.5,"Water":0.5,"Electric":1,"Grass":2,"Ice":0.5,"Fighting":1,"Poison":1,"Ground":2,"Flying":2,"Psychic":1,"Bug":1,"Rock":1,"Ghost":1,"Dragon":2,"Dark":1,"Steel":0.5},
    "Fighting": {"Normal":2,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":2,"Fighting":1,"Poison":0.5,"Ground":1,"Flying":0.5,"Psychic":0.5,"Bug":0.5,"Rock":2,"Ghost":0,"Dragon":1,"Dark":2,"Steel":2},
    "Poison":   {"Normal":1,"Fire":1,"Water":1,"Electric":1,"Grass":2,"Ice":1,"Fighting":1,"Poison":0.5,"Ground":0.5,"Flying":1,"Psychic":1,"Bug":1,"Rock":0.5,"Ghost":0.5,"Dragon":1,"Dark":1,"Steel":0},
    "Ground":   {"Normal":1,"Fire":2,"Water":1,"Electric":2,"Grass":0.5,"Ice":1,"Fighting":1,"Poison":2,"Ground":1,"Flying":0,"Psychic":1,"Bug":0.5,"Rock":2,"Ghost":1,"Dragon":1,"Dark":1,"Steel":2},
    "Flying":   {"Normal":1,"Fire":1,"Water":1,"Electric":0.5,"Grass":2,"Ice":1,"Fighting":2,"Poison":1,"Ground":1,"Flying":1,"Psychic":1,"Bug":2,"Rock":0.5,"Ghost":1,"Dragon":1,"Dark":1,"Steel":0.5},
    "Psychic":  {"Normal":1,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":1,"Fighting":2,"Poison":2,"Ground":1,"Flying":1,"Psychic":0.5,"Bug":1,"Rock":1,"Ghost":1,"Dragon":1,"Dark":0,"Steel":0.5},
    "Bug":      {"Normal":1,"Fire":0.5,"Water":1,"Electric":1,"Grass":2,"Ice":1,"Fighting":0.5,"Poison":0.5,"Ground":1,"Flying":0.5,"Psychic":2,"Bug":1,"Rock":1,"Ghost":0.5,"Dragon":1,"Dark":2,"Steel":0.5},
    "Rock":     {"Normal":1,"Fire":2,"Water":1,"Electric":1,"Grass":1,"Ice":2,"Fighting":0.5,"Poison":1,"Ground":0.5,"Flying":2,"Psychic":1,"Bug":2,"Rock":1,"Ghost":1,"Dragon":1,"Dark":1,"Steel":0.5},
    "Ghost":    {"Normal":0,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":1,"Fighting":1,"Poison":1,"Ground":1,"Flying":1,"Psychic":2,"Bug":1,"Rock":1,"Ghost":2,"Dragon":1,"Dark":0.5,"Steel":0.5},
    "Dragon":   {"Normal":1,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":1,"Fighting":1,"Poison":1,"Ground":1,"Flying":1,"Psychic":1,"Bug":1,"Rock":1,"Ghost":1,"Dragon":2,"Dark":1,"Steel":0.5},
    "Dark":     {"Normal":1,"Fire":1,"Water":1,"Electric":1,"Grass":1,"Ice":1,"Fighting":0.5,"Poison":1,"Ground":1,"Flying":1,"Psychic":2,"Bug":1,"Rock":1,"Ghost":2,"Dragon":1,"Dark":0.5,"Steel":0.5},
    "Steel":    {"Normal":1,"Fire":0.5,"Water":0.5,"Electric":0.5,"Grass":1,"Ice":2,"Fighting":1,"Poison":1,"Ground":1,"Flying":1,"Psychic":1,"Bug":1,"Rock":2,"Ghost":1,"Dragon":1,"Dark":1,"Steel":0.5},
}

def _node_score(node_type: str) -> float:
    return _NODE_SCORE.get(node_type, 0.0)

def _autoswap_score(pokemon_types: list, poke_type: str) -> float:
    """Our attack effectiveness vs opponent (higher = better).
    Multiplies across all trainer types (dual-type = x2*x0.5 = x1.0)."""
    if not poke_type:
        return 1.0
    trainer_types = [t.strip().capitalize() for t in poke_type.split("/") if t.strip()]
    if not trainer_types:
        return 1.0
    attack = (pokemon_types[0] if pokemon_types else "").capitalize()
    mult = 1.0
    for tt in trainer_types:
        mult *= _TYPE_CHART.get(attack, {}).get(tt, 1.0)
    return mult


def _defense_score(pokemon_types: list, poke_type: str) -> float:
    """Damage multiplier opponent deals to our pokemon (lower = better, 0.5 > 1.0 > 2.0).
    Multiplies across all trainer attack types and our own types."""
    if not poke_type:
        return 1.0
    trainer_types = [t.strip().capitalize() for t in poke_type.split("/") if t.strip()]
    if not trainer_types:
        return 1.0
    mult = 1.0
    for attack in trainer_types:
        for t in pokemon_types:
            mult *= _TYPE_CHART.get(attack, {}).get(t.capitalize(), 1.0)
    return mult


def _catch_recommend_score(pokemon_types: list, boss_types: list[str],
                           team_type_coverage: set | None = None) -> float:
    """Weighted resistance score vs upcoming bosses (higher = better catch).
    weights 3/2/1 for boss N, N+1, N+2. resistance = 1 / dmg_taken.
    x0.5 penalty per type already covered by the current team."""
    weights = [3, 2, 1]
    total = 0.0
    for i, bt in enumerate(boss_types[:3]):
        if not bt:
            continue
        dmg = _defense_score(pokemon_types, bt)
        resistance = (1.0 / dmg) if dmg else 4.0
        total += resistance * weights[i]
    if team_type_coverage:
        for t in pokemon_types:
            if t.capitalize() in team_type_coverage:
                total *= 0.5
    return total


_ITEM_TYPE_BOOST_RE = re.compile(r'\+50%\s+(\w+)(?:-type)?\s+(?:move\s+)?damage', re.IGNORECASE)


def _item_recommend_score(item: dict, points_map: dict[str, int],
                          team_attack_types: set) -> float:
    name  = item.get("name", "")
    desc  = item.get("description", "")
    score = float(points_map.get(name, 0))
    m = _ITEM_TYPE_BOOST_RE.search(desc)
    if m:
        item_type = m.group(1).capitalize()
        if item_type in team_attack_types:
            score += 500
        else:
            score -= 100
    return score


def _compute_autoswap_order(team: list, poke_type: str) -> list[int]:
    scored = [
        (i,
         _autoswap_score(p.get("types", []), poke_type),   # our attack  — higher better
         _defense_score(p.get("types", []), poke_type),    # dmg received — lower better
         p.get("level") or 0)                               # level        — higher better
        for i, p in enumerate(team)
    ]
    scored.sort(key=lambda x: (-x[1], x[2], -x[3]))
    return [i for i, _, _, _ in scored]


def _make_extra_score(prioritize_catch: bool, prioritize_heal: bool,
                      prioritize_mystery: bool = False, prioritize_catches: bool = False):
    """Return an extra_score(idx, node) function for the active priority toggles."""
    if not prioritize_catch and not prioritize_heal and not prioritize_mystery and not prioritize_catches:
        return None
    def _extra(idx: int, node: dict) -> float:
        bonus = 0.0
        if prioritize_catch and idx == 1:
            bonus += 10.0
        if prioritize_heal and node.get("type") == "pokecenter":
            bonus += 10.0
        if prioritize_mystery and node.get("type") == "mystery":
            bonus += 10.0
        if prioritize_catches and node.get("type") == "catch_pokemon":
            bonus += 10.0
        return bonus
    return _extra


def _compute_best_level_path(nodes: list, start_idx: int,
                             extra_score=None) -> list[int]:
    """DFS from start_idx to boss, maximising score.
    extra_score(node_idx, node_dict) -> float bonus added on top of _node_score."""
    children: dict[int, list[int]] = {}
    for _, _, _, top, bot in _CONNECTORS:
        children.setdefault(top, []).append(bot)
    boss_idx = next((i for i, n in enumerate(nodes) if n.get("type") == "boss"), len(nodes) - 1)

    def node_val(idx: int) -> float:
        if idx >= len(nodes):
            return 0.0
        base  = _node_score(nodes[idx].get("type", ""))
        bonus = extra_score(idx, nodes[idx]) if extra_score else 0.0
        return base + bonus

    best: list[int] = [start_idx]
    best_score: list[float] = [-float("inf")]

    def dfs(path: list[int], score: float) -> None:
        cur = path[-1]
        if cur == boss_idx:
            if score > best_score[0]:
                best_score[0] = score
                best[:] = path
            return
        for child in children.get(cur, []):
            dfs(path + [child], score + node_val(child))

    dfs([start_idx], node_val(start_idx))
    return best


# ---------------------------------------------------------------------------
# MAP screen widgets
# ---------------------------------------------------------------------------

class TeamCard(Widget):
    """Full-size 2×3 grid Pokémon card — fills its grid cell."""

    can_focus = False

    DEFAULT_CSS = """
    TeamCard {
        width: 1fr;
        height: 1fr;
        border: round #2a3a5a;
        background: #0d0d20;
        padding: 0 1;
        layout: vertical;
    }
    TeamCard.hp-ok        { border: round #00e676; }
    TeamCard.hp-mid       { border: round #f5c518; }
    TeamCard.hp-low       { border: round #ff1744; }
    TeamCard.swapping     { border: round #00d7d7; background: #001825; }
    TeamCard.empty        { border: round #1a1a2e; background: #090912; }
    TeamCard.grid-selected { border: round #f5c518; background: #16140a; }

    .tc-header { layout: horizontal; height: 1; align: left middle; }
    .tc-slot   { width: 3; color: #555577; content-align: left middle; }
    .tc-name   { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .tc-level  { width: 6; color: #555577; text-align: right; content-align: right middle; }
    .tc-types  { layout: horizontal; height: 1; }
    .tc-type   { width: auto; height: 1; padding: 0 1; margin-right: 1; text-style: bold; }
    .tc-hp-ok  { height: 1; color: #00e676; }
    .tc-hp-mid { height: 1; color: #f5c518; }
    .tc-hp-low { height: 1; color: #ff1744; }
    .tc-move   { height: 1; color: #555577; }
    .tc-item   { height: 1; color: #4488ff; }
    .tc-empty  { color: #1e1e35; content-align: center middle; height: 1fr; }
    """

    def __init__(self, slot: int, p: dict | None, swap_val) -> None:
        super().__init__()
        self._slot = slot
        self._p    = p
        if p is None:
            self.add_class("empty")
        else:
            hp = p.get("hp_pct", 100)
            if swap_val == slot:
                self.add_class("swapping")
            elif hp > 50:
                self.add_class("hp-ok")
            elif hp > 20:
                self.add_class("hp-mid")
            else:
                self.add_class("hp-low")

    def compose(self) -> ComposeResult:
        if self._p is None:
            yield Label(f"{self._slot + 1}.", classes="tc-empty")
            return
        p      = self._p
        hp     = p.get("hp_pct", 100)
        hp_cur = p.get("hp_current")
        hp_max = p.get("hp_max")
        types  = p.get("types", [])
        with Horizontal(classes="tc-header"):
            yield Label(f"{self._slot + 1}.",       classes="tc-slot")
            yield Label(p.get("name", "?"),          classes="tc-name")
            yield Label(f"Lv{p.get('level','?')}",  classes="tc-level")
        if types:
            with Horizontal(classes="tc-types"):
                for t in types:
                    yield Label(t, classes=f"tc-type type-{t.lower()}")
        pct    = hp / 100
        filled = round(pct * 7)
        bar    = "█" * filled + "░" * (7 - filled)
        hp_str = f"{hp_cur}/{hp_max}" if hp_cur is not None else f"{hp}%"
        hp_cls = "tc-hp-low" if hp < 20 else "tc-hp-mid" if hp < 50 else "tc-hp-ok"
        yield Label(f"{bar}  {hp_str}", classes=hp_cls)
        move_tier = p.get("move_tier")
        if move_tier is not None and types:
            yield Label(f"T{move_tier} · {types[0]}", classes="tc-move")
        held = p.get("held_item")
        if held:
            yield Label(f"◆ {held}", classes="tc-item")

    def set_selected(self, value: bool) -> None:
        self.set_class(value, "grid-selected")


class TeamGridPanel(Widget):
    """Left panel — 2×3 grid of TeamCards filling width and height equally."""

    BORDER_TITLE = "TEAM"
    can_focus    = False

    DEFAULT_CSS = """
    TeamGridPanel {
        width: 52;
        height: 1fr;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 1;
        layout: vertical;
        margin-right: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    .tg-row { layout: horizontal; height: 1fr; margin-bottom: 1; }
    .tg-row:last-of-type { margin-bottom: 0; }
    .tg-gap { width: 1; }
    """

    def compose(self) -> ComposeResult:
        for _ in range(3):
            yield Horizontal(classes="tg-row")

    def rebuild(self, team: list, swap_val) -> None:
        for ri, row in enumerate(self.query(".tg-row")):
            row.query(TeamCard).remove()
            row.query(Label).remove()
            pair_start = ri * 2
            cards: list = []
            for j in range(2):
                slot = pair_start + j
                p    = team[slot] if slot < len(team) else None
                cards.append(TeamCard(slot, p, swap_val))
                if j == 0:
                    cards.append(Label(" ", classes="tg-gap"))
            row.mount(*cards)

    def update_selected(self, slot: int | None) -> None:
        for card in self.query(TeamCard):
            card.set_selected(card._slot == slot)


class MapGraphWidget(Static):
    """Lattice graph — nodes + ╱╲ connectors, centred in the panel."""

    BORDER_TITLE = "MAP"

    DEFAULT_CSS = """
    MapGraphWidget {
        height: 1fr;
        border: round #2a2a4a;
        background: #080816;
        padding: 0 3;
        content-align: center top;
        border-title-color: #555577;
        border-title-style: bold;
    }
    """

    def rebuild(self, nodes: list[dict], current_node_idx: int | None = None,
                highlight_path: list[int] | None = None) -> None:
        completed_idxs = [i for i, n in enumerate(nodes) if n.get("state") == "completed"]
        last_completed = max(completed_idxs) if completed_idxs else None

        # Pre-compute selected node's grid position for the gold "v"
        sel_gy, sel_gx = None, None
        if current_node_idx is not None:
            _idx = 0
            for _r, _sz in enumerate(_ROW_SIZES):
                for _c in range(_sz):
                    if _idx == current_node_idx:
                        sel_gy = _r * 2
                        sel_gx = _ROW_OFFSET[_r] + _c * _STEP
                    _idx += 1

        # Build 2D grid
        grid: list[list[tuple[str, str]]] = [
            [(" ", "")] * _GRID_W for _ in range(_GRID_H)
        ]

        # Connectors
        completed_set = {i for i, n in enumerate(nodes) if n.get("state") == "completed"}
        path_set      = set(highlight_path) if highlight_path else set()
        for gy, gx, ch, top_idx, bot_idx in _CONNECTORS:
            diag = "╱" if ch == "/" else "╲"
            if path_set and top_idx in path_set and bot_idx in path_set:
                style = "#00aaff"   # blue — best level path
            elif top_idx in completed_set and bot_idx in completed_set:
                style = "#e8e8ff"   # white — completed
            else:
                style = "#2e2e50"   # dim
            grid[gy][gx] = (diag, style)

        # "v" marker one row above the selected node
        if sel_gy is not None and sel_gy > 0:
            grid[sel_gy - 1][sel_gx] = ("v", "bold #f5c518")

        # Nodes
        for idx, (gy, gx) in enumerate(_NODE_GRID_POS):
            if idx < len(nodes):
                n     = nodes[idx]
                state = n.get("state", "locked")
                ntype = n.get("type", "")
                icon, color = NODE_META.get(ntype, ("●", "#e8e8ff"))

                if idx == last_completed:
                    char, style = "X", "bold #e8e8ff"
                elif state == "completed":
                    char, style = icon, "#e8e8ff"
                elif idx == current_node_idx:
                    char, style = icon, f"bold {color}"
                elif state == "available":
                    char, style = icon, color
                else:
                    char, style = icon, f"dim {color}"
            else:
                char, style = "·", "#2e2e50"
            grid[gy][gx] = (char, style)

        # Type emojis — placed at gx+1; gx+2 is a None placeholder so the
        # renderer skips that slot and subsequent chars stay aligned.
        for idx, (gy, gx) in enumerate(_NODE_GRID_POS):
            if idx >= len(nodes):
                continue
            n     = nodes[idx]
            ntype = n.get("type", "")
            if ntype != "trainer":
                continue
            poke_type  = (n.get("poke_type") or "").strip()
            first_type = poke_type.split("/")[0].strip()
            emoji      = TYPE_EMOJI.get(first_type) or TYPE_EMOJI.get(poke_type, "")
            if emoji and gx + 1 < _GRID_W:
                grid[gy][gx + 1] = (emoji, "")
                if gx + 2 < _GRID_W:
                    grid[gy][gx + 2] = (None, "")  # consumed by wide emoji

        # Render (skip None placeholder cells — consumed by a preceding wide emoji)
        result = Text()
        for row in grid:
            line = Text()
            for ch, st in row:
                if ch is not None:
                    line.append(ch, style=st if st else "")
            result.append_text(line)
            result.append("\n")
        self.update(result)


class NodeTile(Widget):
    """One accessible node shown as a card below the graph."""

    can_focus = False

    DEFAULT_CSS = """
    NodeTile {
        width: 1fr;
        height: 5;
        border: round #2a2a4a;
        background: #0d0d1e;
        layout: horizontal;
        align: left middle;
        padding: 0 2;
        margin-right: 1;
    }
    NodeTile.selected { background: #16163a; }
    .nt-key    { width: 5; color: #f5c518; text-style: bold; content-align: center middle; }
    .nt-icon   { width: 4; content-align: center middle; }
    .nt-label  { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .nt-detail { width: auto; color: #555577; content-align: right middle; }
    """

    def __init__(self, item: MenuItem, node: dict, is_selected: bool) -> None:
        super().__init__()
        self._item        = item
        self._node        = node
        self._is_selected = is_selected
        _, self._color    = NODE_META.get(node.get("type", ""), ("·", "#555577"))
        if is_selected:
            self.add_class("selected")

    def on_mount(self) -> None:
        self.styles.border = ("round", self._color)

    def compose(self) -> ComposeResult:
        ntype     = self._node.get("type", "")
        icon, _   = NODE_META.get(ntype, ("·", "#555577"))
        label     = NODE_TYPE_LABEL.get(ntype, ntype.replace("_", " ").title())
        poke_type = self._node.get("poke_type", "")
        yield Label(self._item.shortcut,              classes="nt-key")
        yield Label(icon,                             classes="nt-icon")
        yield Label(label,                            classes="nt-label")
        if poke_type:
            yield Label(f"({poke_type})",             classes="nt-detail")

    def set_selected(self, value: bool) -> None:
        self._is_selected = value
        self.set_class(value, "selected")
        self.styles.border = ("round", self._color if value else "#2a2a4a")


class SingleNodeDisplay(Widget):
    """One accessible node at a time, full-width, ◀▶ to cycle."""

    BORDER_TITLE = "CHOOSE"
    can_focus    = False

    DEFAULT_CSS = """
    SingleNodeDisplay {
        height: 5;
        layout: horizontal;
        align: left middle;
        border: round #2a2a4a;
        background: #0d0d1e;
        padding: 0 2;
        margin-top: 1;
        border-title-color: #555577;
        border-title-style: bold;
    }
    .sn-nav    { width: 4; color: #555577; text-style: bold; content-align: center middle; }
    .sn-key    { width: 5; color: #f5c518; text-style: bold; content-align: center middle; }
    .sn-icon   { width: 4; content-align: center middle; }
    .sn-label  { width: 1fr; color: #e8e8ff; text-style: bold; content-align: left middle; }
    .sn-detail { width: auto; color: #555577; content-align: right middle; }
    .sn-count  { width: 8; color: #555577; content-align: right middle; }
    """

    def compose(self) -> ComposeResult:
        yield Label("◀", classes="sn-nav",    id="sn-prev")
        yield Label("",  classes="sn-key",    id="sn-key")
        yield Label("",  classes="sn-icon",   id="sn-icon")
        yield Label("",  classes="sn-label",  id="sn-label")
        yield Label("",  classes="sn-detail", id="sn-detail")
        yield Label("",  classes="sn-count",  id="sn-count")
        yield Label("▶", classes="sn-nav",    id="sn-next")

    def rebuild(self, node_items: list[MenuItem], nodes: list[dict], idx: int) -> None:
        if not node_items:
            for wid in ("sn-key", "sn-icon", "sn-label", "sn-detail", "sn-count"):
                try: self.query_one(f"#{wid}", Label).update("")
                except Exception: pass
            self.styles.border = ("round", "#2a2a4a")
            return
        i         = idx % len(node_items)
        item      = node_items[i]
        node      = nodes[i] if i < len(nodes) else {}
        ntype     = node.get("type", "")
        icon, color = NODE_META.get(ntype, ("●", "#e8e8ff"))
        label     = NODE_TYPE_LABEL.get(ntype, ntype.replace("_", " ").title())
        poke_type = node.get("poke_type", "")
        try:
            self.query_one("#sn-key",    Label).update(item.shortcut)
            self.query_one("#sn-icon",   Label).update(icon)
            self.query_one("#sn-label",  Label).update(label)
            self.query_one("#sn-detail", Label).update(f"({poke_type})" if poke_type else "")
            self.query_one("#sn-count",  Label).update(f"{i+1}/{len(node_items)}")
            self.styles.border = ("round", color)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Action menu widgets
# ---------------------------------------------------------------------------

class ActionItem(Widget):
    """A single menu entry rendered as a card block."""

    can_focus = False

    DEFAULT_CSS = """
    ActionItem {
        height: 3;
        layout: horizontal;
        align: left middle;
        padding: 0 1;
        border: round #3a3a5a;
        background: #141428;
        margin-bottom: 0;
    }
    ActionItem.selected {
        border: round #f5c518;
        background: #1e1e38;
    }
    ActionItem.disabled {
        border: round #222235;
        background: #0f0f20;
    }

    ActionItem > .shortcut {
        width: 5;
        content-align: center middle;
        color: #00d7d7;
    }
    ActionItem.selected > .shortcut {
        color: #f5c518;
        text-style: bold;
    }
    ActionItem.disabled > .shortcut {
        color: #333355;
    }

    ActionItem > .item-label {
        width: 1fr;
        content-align: left middle;
        color: #9999bb;
    }
    ActionItem.selected > .item-label {
        color: #e8e8ff;
        text-style: bold;
    }
    ActionItem.disabled > .item-label {
        color: #444455;
        text-style: strike dim;
    }

    ActionItem > .arrow {
        width: 3;
        content-align: center middle;
        color: #f5c518;
    }
    """

    def __init__(self, item: MenuItem, is_selected: bool) -> None:
        super().__init__()
        self._item        = item
        self._is_selected = is_selected
        if is_selected:
            self.add_class("selected")
        if not item.enabled:
            self.add_class("disabled")

    def compose(self) -> ComposeResult:
        yield Label(self._item.shortcut,              classes="shortcut")
        yield Label(self._item.label,                 classes="item-label")
        yield Label("❯" if self._is_selected else " ", classes="arrow")

    def refresh_state(self, item: MenuItem, is_selected: bool) -> None:
        """Update visual state without remounting — no flicker."""
        self._item        = item
        self._is_selected = is_selected
        self.set_class(is_selected,     "selected")
        self.set_class(not item.enabled, "disabled")
        self.query_one(".shortcut",   Label).update(item.shortcut)
        self.query_one(".item-label", Label).update(item.label)
        self.query_one(".arrow",      Label).update("❯" if is_selected else " ")


class ActionMenu(Widget):
    """Vertical stack of ActionItem cards."""

    can_focus = False

    DEFAULT_CSS = """
    ActionMenu {
        height: 1fr;
        layout: vertical;
        overflow-y: auto;
        background: transparent;
    }
    """

    def rebuild(self, items: list[MenuItem], selected: int) -> None:
        current = list(self.query(ActionItem))
        if len(current) == len(items):
            # Same number of items — update in place, zero DOM changes
            for i, (widget, item) in enumerate(zip(current, items)):
                widget.refresh_state(item, i == selected)
        else:
            # Screen changed — full remount
            self.query(ActionItem).remove()
            self.mount(*[ActionItem(item, i == selected) for i, item in enumerate(items)])
        widgets = list(self.query(ActionItem))
        if 0 <= selected < len(widgets):
            widgets[selected].scroll_visible(animate=False)


# ---------------------------------------------------------------------------
# Textual screens
# ---------------------------------------------------------------------------

_UTILS_TOGGLES = [
    # (shortcut, label, attr_name, action_type)
    # action_type: "path" = invalidate path cache, "follow" = also reset accessible, "rebuild" = just rebuild
    ("U", "Level Path",        "level_path_on",         "path"),
    ("F", "Follow Path",       "follow_path_on",        "follow"),
    ("A", "Autoswap",          "autoswap_on",           "rebuild"),
    ("C", "Prio. 1st Catch",   "prioritize_catch_on",   "path"),
    ("H", "Prio. Heal",        "prioritize_heal_on",    "path"),
    ("R", "Poke. Recommend",   "poke_recommend_on",     "rebuild"),
    ("I", "Item Recommend",    "item_recommend_on",     "rebuild"),
    ("T", "Autobattle",        "autobattle_on",         "rebuild"),
    ("M", "Prio. Mystery",     "prioritize_mystery_on", "path"),
    ("N", "Prio. Catches",     "prioritize_catches_on", "path"),
    ("S", "Prio. Shiny",       "prioritize_shiny_on",   "rebuild"),
    ("Z", "Auto Reroll",      "auto_reroll_on",        "rebuild"),
]


class UtilsScreen(ModalScreen):
    """Centered popup overlay for toggling automation options."""

    DEFAULT_CSS = """
    UtilsScreen {
        align: center middle;
    }
    #utils-panel {
        width: 46;
        height: auto;
        border: double #4488ff;
        background: #0d0d1a;
        padding: 1 2;
    }
    #utils-title {
        height: 1;
        text-align: center;
        color: #4488ff;
        text-style: bold;
        margin-bottom: 1;
        content-align: center middle;
    }
    #utils-body {
        height: auto;
    }
    #utils-hint {
        height: 1;
        color: #555577;
        text-align: center;
        margin-top: 1;
        content-align: center middle;
    }
    """

    def __init__(self, app_ref) -> None:
        super().__init__()
        self._app_ref = app_ref
        self._selected = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="utils-panel"):
            yield Label("⚙  UTILS", id="utils-title")
            yield Static("", id="utils-body")
            yield Label("↑↓ navigate  ·  Enter/letter toggle  ·  Esc close", id="utils-hint")

    def on_mount(self) -> None:
        self._app_ref.utils_mode[0] = True
        self._refresh_body()

    def on_unmount(self) -> None:
        self._app_ref.utils_mode[0] = False
        self._app_ref._follow_last_accessible = frozenset()
        self._app_ref._force_parse = True

    def _refresh_body(self) -> None:
        a = self._app_ref
        t = Text()
        for i, (key, label, attr, _) in enumerate(_UTILS_TOGGLES):
            is_sel = i == self._selected
            if attr:
                val = getattr(a, attr)[0]
                state_str = "[bold #00e676]ON [/]" if val else "[dim]OFF[/]"
            else:
                state_str = "   "
            row_style = "bold #ffffff on #1a1a3a" if is_sel else ""
            cursor = "❯ " if is_sel else "  "
            line = Text()
            line.append(f"{cursor}", style=row_style)
            line.append(f"{key}", style=f"bold #f5c518{' on #1a1a3a' if is_sel else ''}")
            line.append(f"  {label:<18}", style=row_style)
            line.append(f"  ")
            line.append_text(Text.from_markup(state_str))
            line.append("\n")
            t.append_text(line)
        t.append_text(Text.from_markup("\n  [dim]G[/]  [dim]Debug[/]"))
        self.query_one("#utils-body", Static).update(t)

    def _toggle_selected(self, idx: int) -> None:
        a = self._app_ref
        key, label, attr, action = _UTILS_TOGGLES[idx]
        if attr is None:
            return
        ref = getattr(a, attr)
        ref[0] = not ref[0]
        if action in ("path", "follow"):
            a._last_level_path_key = None
            a._force_parse = True
        if action == "follow":
            a._follow_last_accessible = frozenset()
        a._force_parse = True
        a._rebuild()
        self._refresh_body()

    def on_key(self, event) -> None:
        key = event.key
        if key == "escape" or key == "x":
            self.app.pop_screen()
            return
        if key == "up":
            self._selected = (self._selected - 1) % len(_UTILS_TOGGLES)
            self._refresh_body()
            return
        if key == "down":
            self._selected = (self._selected + 1) % len(_UTILS_TOGGLES)
            self._refresh_body()
            return
        if key == "enter":
            self._toggle_selected(self._selected)
            return
        if key == "g":
            self.app.pop_screen()
            self._app_ref._execute_item_by_result("SHOW_LEVEL_PATH_DEBUG")
            return
        # Letter shortcut — find matching toggle
        for i, (k, _, attr, _) in enumerate(_UTILS_TOGGLES):
            if key == k.lower() and attr is not None:
                self._selected = i
                self._toggle_selected(i)
                return


class JsonScreen(Screen):
    """Scrollable JSON viewer."""

    BINDINGS = [Binding("escape", "close_json", "Close")]

    DEFAULT_CSS = """
    JsonScreen {
        background: #0d0d1a;
        align: center middle;
    }
    #json-outer {
        width: 92%;
        height: 92%;
        border: double #f5c518;
        background: #0d0d1a;
        layout: vertical;
    }
    #json-title {
        height: 1;
        background: #12121f;
        color: #f5c518;
        text-align: center;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #2a2a4a;
        padding: 0 2;
    }
    #json-scroll {
        height: 1fr;
        overflow-y: scroll;
        background: #0d0d1a;
    }
    #json-content {
        padding: 1 2;
    }
    """

    def __init__(self, json_text: str) -> None:
        super().__init__()
        self.json_text = json_text

    def compose(self) -> ComposeResult:
        with Vertical(id="json-outer"):
            yield Label(
                "RAW JSON  ·  ↑↓ scroll  ·  any other key closes",
                id="json-title",
            )
            with ScrollableContainer(id="json-scroll"):
                yield Static(
                    Syntax(
                        self.json_text, "json",
                        theme="monokai", line_numbers=True,
                    ),
                    id="json-content",
                )

    def action_close_json(self) -> None:
        self.app.pop_screen()

    def on_key(self, event) -> None:
        if event.key not in ("up", "down", "pageup", "pagedown", "escape"):
            self.app.pop_screen()


class TeamSelectScreen(ModalScreen):
    """Full-screen Battle Tower PC box — search + shiny filter + scrollable grid."""

    BINDINGS = [
        Binding("escape", "cancel",     "Cancel",  priority=True),
        Binding("up",     "row_up",     "",        show=False, priority=True),
        Binding("down",   "row_down",   "",        show=False, priority=True),
        Binding("enter",  "select_row", "Select",  priority=True),
    ]

    DEFAULT_CSS = """
    TeamSelectScreen {
        background: #0d0d1a 85%;
        align: center middle;
    }
    #ts-outer {
        width: 92%;
        height: 92%;
        layout: vertical;
        border: double #4488ff;
        background: #0d0d1a;
    }
    #ts-header {
        height: 1;
        background: #12121f;
        color: #4488ff;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #2a2a4a;
    }
    #ts-toolbar {
        height: 3;
        background: #0f0f1f;
        border-bottom: solid #1e1e3a;
        padding: 0 2;
        align: left middle;
    }
    #ts-search {
        width: 28;
        background: #0d0d1a;
        color: #00d7d7;
        border: round #2a2a4a;
    }
    #ts-count {
        color: #555577;
        margin-left: 2;
        width: auto;
        content-align: left middle;
    }
    #ts-hint {
        color: #2a2a4a;
        width: 1fr;
        text-align: right;
        content-align: right middle;
        padding-right: 1;
    }
    #ts-table {
        height: 1fr;
        background: #12121f;
    }
    TeamSelectScreen DataTable > .datatable--header {
        background: #12121f;
        color: #f5c518;
        text-style: bold;
    }
    TeamSelectScreen DataTable > .datatable--cursor {
        background: #1e1e35;
        color: #e8e8ff;
    }
    TeamSelectScreen DataTable {
        background: #12121f;
        color: #e8e8ff;
    }
    """

    def __init__(self, app_ref) -> None:
        super().__init__()
        self._app_ref = app_ref
        self._rows: list[dict] = []   # filtered rows, index matches DataTable row

    def compose(self) -> ComposeResult:
        with Vertical(id="ts-outer"):
            yield Label("", id="ts-header")
            with Horizontal(id="ts-toolbar"):
                yield Input(placeholder="search by name…", id="ts-search")
                yield Label("", id="ts-count")
                yield Label("↑↓=nav  Enter=pick  Esc=cancel", id="ts-hint")
            yield DataTable(id="ts-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Name", "Lv", "Types", "Buff")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.query_one(Input).focus()
        self._refresh()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._refresh()

    def _filtered(self) -> list[dict]:
        pokemon = self._app_ref.state.get("pokemon", [])
        q = ""
        try:
            q = self.query_one(Input).value.lower()
        except Exception:
            pass
        result = pokemon
        if q:
            result = [p for p in result if p["name"].lower().startswith(q)]
        return sorted(result, key=lambda p: (-int(p.get("is_shiny") or 0), -p.get("buff", 0)))

    def _refresh(self) -> None:
        title = self._app_ref.state.get("title", "HALL OF FAME PC")
        total = len(self._app_ref.state.get("pokemon", []))
        try:
            self.query_one("#ts-header", Label).update(
                f"⚔  {title}  ·  {total} Pokémon"
            )
        except Exception:
            pass
        self._rows = self._filtered()
        table = self.query_one(DataTable)
        table.clear()
        for p in self._rows:
            shiny_mark = Text("★", style="bold #ffdd22") if p.get("is_shiny") else Text(" ", style="#555577")
            name  = Text(p["name"], style="bold #e8e8ff" if p.get("is_shiny") else "#e8e8ff")
            level = Text(p.get("level", "?"), style="#555577")
            types = Text("/".join(p.get("types", [])) or "—", style="#888899")
            buff  = Text("★" * min(p.get("buff", 0), 12), style="#f5c518")
            table.add_row(shiny_mark, name, level, types, buff)
        try:
            self.query_one("#ts-count", Label).update(
                f"[#555577]{len(self._rows)}/{total}[/]"
            )
        except Exception:
            pass

    def action_row_up(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row > 0:
            table.move_cursor(row=table.cursor_row - 1)

    def action_row_down(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1)

    def action_select_row(self) -> None:
        table = self.query_one(DataTable)
        if not self._rows or table.row_count == 0:
            return
        row_idx = table.cursor_row
        if row_idx < len(self._rows):
            slot_idx = self._rows[row_idx]["index"]
            page = self._app_ref.page
            self._app_ref.run_in_browser(
                lambda i=slot_idx: page.evaluate(
                    "(i) => document.querySelectorAll('.pc-slot')[i]?.click()", i
                )
            )
            self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def on_key(self, event) -> None:
        # Backspace for search input
        if event.key == "backspace":
            try:
                inp = self.query_one(Input)
                inp.value = inp.value[:-1]
            except Exception:
                pass


class PokedexScreen(Screen):
    """Full-screen Pokédex overlay with search and route-browse modes."""

    BINDINGS = [
        Binding("escape", "close_dex",    "Close",       priority=True),
        Binding("tab",    "toggle_mode",  "Switch Mode", priority=True),
        Binding("up",     "row_up",       "",            show=False, priority=True),
        Binding("down",   "row_down",     "",            show=False, priority=True),
        Binding("left",   "prev_route",   "◀",           show=False, priority=True),
        Binding("right",  "next_route",   "▶",           show=False, priority=True),
    ]

    DEFAULT_CSS = """
    PokedexScreen {
        background: #0d0d1a;
        layout: vertical;
    }
    #dex-header {
        height: 1;
        background: #12121f;
        color: #f5c518;
        text-style: bold;
        text-align: center;
        content-align: center middle;
        border-bottom: solid #2a2a4a;
    }
    #dex-toolbar {
        height: 3;
        background: #0f0f1f;
        border-bottom: solid #1e1e3a;
        padding: 0 2;
        align: left middle;
    }
    #dex-route-bar {
        height: 3;
        background: #0f0f1f;
        border-bottom: solid #1e1e3a;
        align: center middle;
        display: none;
    }
    #dex-search {
        width: 28;
        background: #0d0d1a;
        color: #00d7d7;
        border: round #2a2a4a;
    }
    #dex-count {
        color: #555577;
        margin-left: 2;
        width: auto;
        content-align: left middle;
    }
    #dex-hint {
        color: #2a2a4a;
        width: 1fr;
        text-align: right;
        content-align: right middle;
        padding-right: 1;
    }
    #dex-route-name {
        color: #00d7d7;
        text-style: bold;
        width: 1fr;
        text-align: center;
        content-align: center middle;
    }
    .dex-nav-arrow {
        color: #555577;
        width: 4;
        content-align: center middle;
    }
    #dex-table {
        height: 1fr;
        background: #12121f;
    }
    DataTable > .datatable--header {
        background: #12121f;
        color: #f5c518;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #1e1e35;
        color: #e8e8ff;
    }
    DataTable {
        background: #12121f;
        color: #e8e8ff;
    }
    """

    ROUTE_ORDER = [
        "Route 1", "Mt Moon", "Nugget Bridge", "Rock Tunnel",
        "Silph Co", "Safari Zone", "Seafoam Island", "Viridian City", "Victory Road",
    ]
    FLOOR_ORDER = ["Early", "Early-Middle", "Middle", "Middle-Late", "Late"]

    def __init__(self, app) -> None:
        super().__init__()
        self._app      = app
        self.mode      = "search"
        self.route_idx = 0
        self.data:       list = []
        self.route_map:  dict = {}
        self.all_routes: list = []

    def compose(self) -> ComposeResult:
        yield Label(
            "POKÉDEX  ·  Tab=switch mode  ·  ↑↓=scroll  ·  Esc=close",
            id="dex-header",
        )
        with Horizontal(id="dex-toolbar"):
            yield Input(placeholder="type to filter by name…", id="dex-search")
            yield Label("", id="dex-count")
            yield Label("Tab → route mode", id="dex-hint")
        with Horizontal(id="dex-route-bar"):
            yield Label("◀", classes="dex-nav-arrow")
            yield Label("", id="dex-route-name")
            yield Label("▶", classes="dex-nav-arrow")
        yield DataTable(id="dex-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Name", "Types", "Normal Routes", "Tower Floors")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.query_one(Input).focus()
        self._load_data()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.mode == "search":
            self._refresh_table()

    # ── data loading ──────────────────────────────────────────────────────

    @work(thread=True)
    def _load_data(self) -> None:
        js = """() => {
                const species = JSON.parse(localStorage.getItem('pkrl_species_list') || '[]')
                const dex     = JSON.parse(localStorage.getItem('poke_dex') || '{}')
                return species.map(s => {
                    const locs  = (typeof getPokemonLocations === 'function') ? getPokemonLocations(s.id) : {}
                    const types = (typeof getSpeciesTypes     === 'function') ? getSpeciesTypes(s.id)     : []
                    return {
                        id:     s.id,
                        name:   s.name,
                        types:  types || [],
                        caught: !!dex[s.id],
                        routes: locs.regularMaps || [],
                        floors: locs.towerFloors || [],
                    }
                })
            }"""
        try:
            data = self._app.run_in_browser(lambda: self._app.page.evaluate(js))
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []

        route_map: dict = {}
        for s in data:
            for r in s["routes"]:
                route_map.setdefault(r, []).append(s)
            for f in s["floors"]:
                route_map.setdefault(f"Tower: {f}", []).append(s)

        def _route_sort_key(name: str) -> tuple:
            if name.startswith("Tower: "):
                floor = name[len("Tower: "):]
                idx   = self.FLOOR_ORDER.index(floor) if floor in self.FLOOR_ORDER else len(self.FLOOR_ORDER)
                return (1, idx)
            idx = self.ROUTE_ORDER.index(name) if name in self.ROUTE_ORDER else len(self.ROUTE_ORDER)
            return (0, idx)

        all_routes = sorted(route_map.keys(), key=_route_sort_key)
        self.app.call_from_thread(self._apply_data, data, route_map, all_routes)

    def _apply_data(self, data, route_map, all_routes) -> None:
        self.data       = data
        self.route_map  = route_map
        self.all_routes = all_routes
        self._refresh_table()

    # ── table refresh ─────────────────────────────────────────────────────

    def _filtered(self) -> list:
        try:
            q = self.query_one(Input).value.lower()
        except Exception:
            q = ""
        if q:
            return [s for s in self.data if s["name"].lower().startswith(q)]
        return self.data

    def _refresh_table(self) -> None:
        table   = self.query_one(DataTable)
        table.clear()
        results = self._filtered()
        caught  = sum(1 for s in results if s["caught"])
        try:
            self.query_one("#dex-count", Label).update(
                f"[#00e676]{caught}[/][#555577]/{len(results)}[/]"
            )
        except Exception:
            pass
        for s in results:
            check  = Text("✓ ", style="#00e676") if s["caught"] else Text("· ", style="#555577")
            name   = Text(s["name"], style="bold #e8e8ff" if s["caught"] else "#777799")
            types  = Text("/".join(s["types"]) if s["types"] else "—", style="#555577")
            routes = ", ".join(s["routes"]) if s["routes"] else "—"
            floors = ", ".join(s["floors"]) if s["floors"] else "—"
            table.add_row(check, name, types, routes, floors, key=str(s["id"]))

    def _refresh_route_view(self) -> None:
        if not self.all_routes:
            return
        ri         = self.route_idx % len(self.all_routes)
        route_name = self.all_routes[ri]
        try:
            self.query_one("#dex-route-name", Label).update(route_name)
        except Exception:
            pass
        table = self.query_one(DataTable)
        table.clear()
        for s in self.route_map.get(route_name, []):
            check = Text("✓ ", style="#00e676") if s["caught"] else Text("· ", style="#555577")
            name  = Text(s["name"], style="bold #e8e8ff" if s["caught"] else "#777799")
            types = Text("/".join(s["types"]) if s["types"] else "—", style="#555577")
            table.add_row(check, name, types, "", "", key=str(s["id"]))

    # ── actions ───────────────────────────────────────────────────────────

    def action_close_dex(self) -> None:
        self.app.pop_screen()

    def action_toggle_mode(self) -> None:
        self.mode = "route" if self.mode == "search" else "search"
        toolbar   = self.query_one("#dex-toolbar")
        route_bar = self.query_one("#dex-route-bar")
        if self.mode == "search":
            toolbar.display   = True
            route_bar.display = False
            self.query_one(Input).focus()
            self._refresh_table()
        else:
            toolbar.display   = False
            route_bar.display = True
            self.query_one(DataTable).focus()
            self._refresh_route_view()

    def action_row_up(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row > 0:
            table.move_cursor(row=table.cursor_row - 1)

    def action_row_down(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1)

    def action_prev_route(self) -> None:
        if self.mode == "route" and self.all_routes:
            self.route_idx = (self.route_idx - 1) % len(self.all_routes)
            self._refresh_route_view()

    def action_next_route(self) -> None:
        if self.mode == "route" and self.all_routes:
            self.route_idx = (self.route_idx + 1) % len(self.all_routes)
            self._refresh_route_view()


# ---------------------------------------------------------------------------
# Main Textual app
# ---------------------------------------------------------------------------

class PokelikeApp(App):
    """
    All Playwright operations run in a single dedicated browser thread.
    Textual runs its asyncio loop in the main thread, receiving UI updates
    via call_from_thread.
    """

    TITLE = "POKELIKE  automation"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
    ]

    DEFAULT_CSS = """
    /* ── Global ─────────────────────────────────────────────── */
    Screen {
        background: #0d0d1a;
    }
    Header {
        background: #0a0a18;
        color: #f5c518;
        text-style: bold;
        height: 1;
    }
    Footer {
        background: #0a0a18;
        color: #2a2a4a;
        height: 1;
    }

    /* ── Layout containers ──────────────────────────────────── */
    #default-layout {
        height: 1fr;
        padding: 0 1;
    }
    #menu-panel {
        width: 1fr;
        border: round #2a2a4a;
        background: #12121f;
        padding: 1 2;
        height: 1fr;
    }
    #menu-panel-title {
        color: #555577;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    #starter-panel {
        display: none;
    }
    #map-layout {
        height: 1fr;
        padding: 0 1 0 1;
        layout: vertical;
    }
    #map-inner { height: 1fr; }
    #map-right-col { width: 21; layout: vertical; margin-left: 1; }
    #map-right-col BagPanel { margin-left: 0; }
    #map-right-col BossPanel { margin-left: 0; }
    #map-center {
        width: 1fr;
        layout: vertical;
        padding: 0 1;
    }
    #map-strip {
        height: 5;
        layout: horizontal;
        border-top: solid #1e1e3a;
        align: left middle;
        overflow-x: auto;
    }
    #map-strip ActionItem {
        width: auto;
        min-width: 14;
        margin-right: 1;
    }
    #map-strip ActionItem > .item-label { width: auto; }

    /* ── Catch screen ───────────────────────────────────────── */
    #catch-layout {
        height: 1fr;
        padding: 0 1 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.page            = None
        self.game_screen     = ScreenType.UNKNOWN
        self.state: dict     = {}
        self.selected        = 0
        self.selected_starter = 0
        self.swap_source     = [None]
        self.bag_mode        = [False]
        self.utils_mode           = [False]
        self.level_path_on        = [True]
        self.follow_path_on       = [False]
        self.autoswap_on          = [False]
        self.autobattle_on        = [False]
        self.prioritize_catch_on  = [False]
        self.prioritize_heal_on   = [False]
        self.prioritize_mystery_on  = [False]
        self.prioritize_catches_on  = [False]
        self.poke_recommend_on    = [True]
        self.item_recommend_on    = [True]
        self.prioritize_shiny_on  = [True]
        self.auto_reroll_on       = [False]
        self._item_points_cache: dict[str, int] = {}
        self._team_attack_types: set = set()
        self._upcoming_boss_types: list = []
        self._team_type_coverage: set  = set()
        self.best_level_path = [[]]
        self._last_level_path_key  = None
        self._follow_last_accessible: frozenset = frozenset()
        self._last_battle_can_continue: bool = False
        self._item_equip_try_idx: int = 0
        self._item_equip_last_try: float = 0.0
        self.flash_until     = 0.0
        self._items: list[MenuItem] = []
        self._task_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._stop           = threading.Event()
        self._ui_ready        = False
        self._last_items_key       = None
        self._last_team_key        = None
        self._last_graph_key       = None
        self._last_battle_team_key  = None
        self._last_team_full_key    = None
        self.map_carousel_idx = 0
        self._force_parse           = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(id="status-bar")
        with Horizontal(id="default-layout"):
            with Vertical(id="menu-panel"):
                yield Label("ACTIONS", id="menu-panel-title")
                yield ActionMenu(id="menu-actions")
            yield StarterPickerWidget(id="starter-panel")
        with Vertical(id="map-layout"):
            with Horizontal(id="map-inner"):
                yield TeamGridPanel(id="map-team-grid")
                with Vertical(id="map-center"):
                    yield MapGraphWidget(id="map-graph")
                    yield SingleNodeDisplay(id="map-node-display")
                with Vertical(id="map-right-col"):
                    yield BagPanel(id="bag-panel")
                    yield BossPanel(id="boss-panel")
            with Horizontal(id="map-strip"):
                pass
        with Horizontal(id="catch-layout"):
            yield CatchPokemonPanel(id="catch-panel")
        yield BattlePanel(id="battle-panel")
        yield ItemSelectPanel(id="item-select-panel")
        yield TeamFullPanel(id="team-full-panel")
        yield MainMenuPanel(id="main-menu-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._ui_ready = True
        self.query_one("#map-layout").display         = False
        self.query_one("#catch-layout").display       = False
        self.query_one("#battle-panel").display       = False
        self.query_one("#item-select-panel").display  = False
        self.query_one("#team-full-panel").display    = False
        self.query_one("#main-menu-panel").display    = False
        t = threading.Thread(target=self._browser_loop, daemon=True)
        t.start()

    def on_unmount(self) -> None:
        self._stop.set()

    def action_quit_app(self) -> None:
        self.exit()

    # ------------------------------------------------------------------
    # Browser thread
    # ------------------------------------------------------------------

    def _browser_loop(self) -> None:
        try:
            with connect_to_chrome() as page:
                self.page = page
                self.call_from_thread(self._on_connected, page.url)
                last_refresh = 0.0
                last_dom_hash = ""
                while not self._stop.is_set():
                    while True:
                        try:
                            task, result_holder, done_event = self._task_queue.get_nowait()
                            try:
                                result_holder[0] = task()
                            except Exception as e:
                                result_holder[0] = f"Error: {e}"
                            done_event.set()
                        except queue.Empty:
                            break

                    now = time.monotonic()
                    if now - last_refresh >= AUTO_REFRESH_INTERVAL:
                        last_refresh = now
                        try:
                            prev       = self.game_screen
                            new_screen = detect(page)
                            dom_hash   = _dom_hash(page, new_screen)
                            if dom_hash and dom_hash == last_dom_hash and new_screen == prev and not self._force_parse:
                                continue
                            self._force_parse = False
                            last_dom_hash = dom_hash
                            p          = PARSER_MAP.get(new_screen)
                            new_state  = p.parse(page) if p else _unknown_state(page, new_screen)
                            self.call_from_thread(self._apply_state, prev, new_screen, new_state)
                            # Keep clicking through multi-phase evolution overlays
                            if new_screen == ScreenType.EVOLUTION:
                                page.evaluate("""() => {
                                    const o = document.getElementById('evo-overlay')
                                    if (o) o.dispatchEvent(
                                        new MouseEvent('click', {bubbles: true, cancelable: true})
                                    )
                                }""")
                        except Exception:
                            pass

                    self._stop.wait(timeout=0.05)

        except Exception as e:
            try:
                self.call_from_thread(self._on_connect_error, e)
            except Exception:
                pass

    def _on_connected(self, url: str) -> None:
        if not self._ui_ready:
            return
        try:
            self.query_one(StatusBar).update(
                Text.from_markup(f" [bold #00e676]Connected[/]  [#555577]{url}[/]")
            )
        except Exception:
            pass

    def _on_connect_error(self, e: Exception) -> None:
        if not self._ui_ready:
            return
        try:
            self.query_one(StatusBar).update(
                Text.from_markup(f" [bold #ff1744]Connection error:[/]  [#e8e8ff]{e}[/]")
            )
        except Exception:
            pass

    def run_in_browser(self, fn) -> str:
        result_holder = [None]
        done = threading.Event()
        self._task_queue.put((fn, result_holder, done))
        done.wait()
        return result_holder[0] or ""

    # ------------------------------------------------------------------
    # UI updates (main thread)
    # ------------------------------------------------------------------

    def _apply_state(self, prev: ScreenType, new_screen: ScreenType, new_state: dict) -> None:
        changed          = new_screen != prev
        self.game_screen = new_screen
        self.state       = new_state
        self.flash_until = time.monotonic() + 1.2
        if changed:
            self.selected = 0
            self.map_carousel_idx = 0
            if (new_screen == ScreenType.CATCH_POKEMON
                    and self.poke_recommend_on[0]
                    and self._upcoming_boss_types):
                choices = new_state.get("choices", [])
                scores  = [_catch_recommend_score(c.get("types", []), self._upcoming_boss_types,
                                                   self._team_type_coverage)
                           + (50 if self.prioritize_shiny_on[0] and c.get("is_shiny") else 0)
                           for c in choices]
                if scores:
                    self.selected = scores.index(max(scores))
            if new_screen == ScreenType.CATCH_POKEMON and self.auto_reroll_on[0]:
                page = self.page
                for i, c in enumerate(new_state.get("choices", [])):
                    if not c.get("is_shiny"):
                        def do_reroll(idx=i):
                            page.evaluate("""(i) => {
                                const btn = document.querySelectorAll('.screen.active .poke-choice-wrap')[i]
                                    ?.querySelector('.reroll-btn')
                                if (btn) btn.click()
                            }""", idx)
                        self._task_queue.put((do_reroll, [None], threading.Event()))
            if new_screen == ScreenType.ITEM_SELECT:
                choices = new_state.get("choices", [])
                item_db.upsert_items(choices)
                self._item_points_cache = item_db.get_scores()
                if self.item_recommend_on[0] and choices:
                    scores = [_item_recommend_score(c, self._item_points_cache,
                                                    self._team_attack_types)
                              for c in choices]
                    if scores:
                        self.selected = scores.index(max(scores))
            self._handle_screen_change_ui(prev, new_screen)

        # Cache upcoming boss types and team type coverage whenever map is parsed
        if new_screen == ScreenType.MAP:
            ubt = new_state.get("upcoming_boss_types", [])
            if ubt:
                self._upcoming_boss_types = ubt
            self._team_type_coverage = {
                t.capitalize()
                for p in new_state.get("team", [])
                for t in p.get("types", [])
                if t
            }
            self._team_attack_types = {
                t.capitalize()
                for p in new_state.get("team", [])
                for t in p.get("move_types", [])
                if t
            }

        # Path logic — runs before _rebuild() so cursor is correct on first render
        _target_node_idx = None
        _acc_list: list[int] = []
        _nodes: list = []
        if (new_screen == ScreenType.MAP
                and not self.utils_mode[0]
                and not self.swap_source[0]
                and not self.bag_mode[0]
                and (self.level_path_on[0] or self.follow_path_on[0] or self.autoswap_on[0])):
            _nodes  = new_state.get("nodes", [])
            new_acc = frozenset(n["index"] for n in _nodes if n["accessible"])
            if new_acc and new_acc != self._follow_last_accessible:
                self._follow_last_accessible = new_acc
                completed_idxs = [i for i, n in enumerate(_nodes) if n.get("state") == "completed"]
                last_done = max(completed_idxs) if completed_idxs else 0
                path = _compute_best_level_path(_nodes, last_done,
                    _make_extra_score(self.prioritize_catch_on[0], self.prioritize_heal_on[0], self.prioritize_mystery_on[0], self.prioritize_catches_on[0]))
                _acc_list = [n["index"] for n in _nodes if n["accessible"]]
                for node_idx in path:
                    if node_idx >= len(_nodes): continue
                    if node_idx in new_acc:
                        _target_node_idx = node_idx
                        break

                # Set cursor to path node before rendering
                if _target_node_idx is not None and self.level_path_on[0]:
                    pos = _acc_list.index(_target_node_idx)
                    self.selected = pos
                    self.map_carousel_idx = pos

        self._rebuild()

        # Autoswap + Follow Path (after render, FIFO queue ensures swap-before-click)
        if _target_node_idx is not None:
            if self.autoswap_on[0]:
                node = _nodes[_target_node_idx]
                if node.get("type") in ("trainer", "boss"):
                    self._queue_autoswap(new_state.get("team", []), node.get("poke_type", ""))
            if self.follow_path_on[0] and (_nodes[_target_node_idx].get("type") != "boss" or self.autobattle_on[0]):
                self._execute_item(_acc_list.index(_target_node_idx))

        # Auto-item: if Follow Path and Item Recommend are on, auto-pick the recommended item
        if new_screen == ScreenType.ITEM_SELECT and new_screen != prev and self.follow_path_on[0] and self.item_recommend_on[0]:
            def do_auto_item():
                if self._items and self.selected < len(self._items):
                    return self._items[self.selected].action()
                return "No item"
            self._task_queue.put((do_auto_item, [None], threading.Event()))

        # Auto-equip: if Follow Path is on and we're on the item equip screen,
        # try each pokemon in order; if still on screen after 2s, advance to the next one
        if new_screen == ScreenType.ITEM_EQUIP and self.follow_path_on[0]:
            if new_screen != prev:
                self._item_equip_try_idx = 0
                self._item_equip_last_try = time.time()
                def do_auto_equip():
                    if self._items:
                        return self._items[0].action()
                    return "No action"
                self._task_queue.put((do_auto_equip, [None], threading.Event()))
            elif time.time() - self._item_equip_last_try >= 2.0:
                self._item_equip_try_idx += 1
                self._item_equip_last_try = time.time()
                idx = self._item_equip_try_idx
                def do_auto_equip_next(i=idx):
                    if self._items and i < len(self._items):
                        return self._items[i].action()
                    return "No action"
                self._task_queue.put((do_auto_equip_next, [None], threading.Event()))
        elif new_screen != ScreenType.ITEM_EQUIP:
            self._item_equip_try_idx = 0
            self._item_equip_last_try = 0.0

        # Auto-battle: if autobattle is on and battle screen shows Continue, click it once
        if new_screen == ScreenType.BATTLE and self.autobattle_on[0]:
            can_continue = new_state.get("can_continue", False)
            if can_continue and not self._last_battle_can_continue:
                for item in self._items:
                    if item.shortcut == "C":
                        self._task_queue.put((item.action, [None], threading.Event()))
                        break
            self._last_battle_can_continue = can_continue
        elif new_screen != ScreenType.BATTLE:
            self._last_battle_can_continue = False

    def _handle_screen_change_ui(self, prev: ScreenType, new: ScreenType) -> None:
        if new in (ScreenType.BADGE_OBTAINED, ScreenType.STARTER_SELECT):
            self.follow_path_on[0]        = False
            self._follow_last_accessible  = frozenset()
        page = self.page
        if new == ScreenType.STARTER_SELECT:
            idx = self.selected_starter
            self._task_queue.put((lambda: click_starter(page, idx), [None], threading.Event()))
        elif new == ScreenType.BADGE_OBTAINED:
            js = """() => { const b = Array.from(document.querySelectorAll('.btn-primary')).find(b => b.textContent.includes('Next Map')); if (b) b.click() }"""
            self._task_queue.put((lambda: page.evaluate(js), [None], threading.Event()))
        elif new == ScreenType.GAME_OVER:
            js = """() => { const b = Array.from(document.querySelectorAll('.btn-primary')).find(b => b.textContent.trim() === 'Try Again'); if (b) b.click() }"""
            self._task_queue.put((lambda: page.evaluate(js), [None], threading.Event()))
        elif new == ScreenType.EVOLUTION:
            evo_js = """() => {
                const o = document.getElementById('evo-overlay')
                if (o) o.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))
            }"""
            self._task_queue.put((lambda: page.evaluate(evo_js), [None], threading.Event()))
        if new == ScreenType.TEAM_SELECT:
            self.push_screen(TeamSelectScreen(self))
        elif prev == ScreenType.TEAM_SELECT:
            if len(self.screen_stack) > 1 and isinstance(self.screen_stack[-1], TeamSelectScreen):
                self.pop_screen()

    def _rebuild(self) -> None:
        if not self._ui_ready or self.page is None:
            return
        self._items = self._build_current_items()
        if self._items:
            self.selected = max(0, min(self.selected, len(self._items) - 1))

        flash = time.monotonic() < self.flash_until

        # Show screen type in the Header subtitle (always visible at top)
        self.sub_title = self.game_screen.name.replace("_", " ")

        try:
            self.query_one(StatusBar).update_status(self.game_screen, self.state, flash)
        except Exception:
            pass

        is_map         = self.game_screen == ScreenType.MAP
        is_catch       = self.game_screen == ScreenType.CATCH_POKEMON
        is_battle      = self.game_screen == ScreenType.BATTLE
        is_item_select = self.game_screen == ScreenType.ITEM_SELECT
        is_team_full   = self.game_screen == ScreenType.TEAM_FULL
        is_main_menu   = self.game_screen == ScreenType.MAIN_MENU
        is_custom      = is_map or is_catch or is_battle or is_item_select or is_team_full or is_main_menu
        try:
            self.query_one("#default-layout").display      = not is_custom
            self.query_one("#map-layout").display          = is_map
            self.query_one("#catch-layout").display        = is_catch
            self.query_one("#battle-panel").display        = is_battle
            self.query_one("#item-select-panel").display   = is_item_select
            self.query_one("#team-full-panel").display     = is_team_full
            self.query_one("#main-menu-panel").display     = is_main_menu
        except Exception:
            pass

        if is_map:
            swap_val      = self.swap_source[0]
            team          = self.state.get("team", [])
            nodes_all     = self.state.get("nodes", [])
            accessible    = [n for n in nodes_all if n["accessible"]]
            n_nodes       = len(accessible)
            is_swap_pick  = swap_val in ("swap", "item_pick") or isinstance(swap_val, int)
            is_bag_active = self.bag_mode[0]
            is_special    = is_swap_pick or is_bag_active

            # Team grid
            team_key = tuple(
                f"{p.get('name')}:{p.get('hp_pct')}:{p.get('hp_current')}:{swap_val}"
                for p in team
            )
            if team_key != self._last_team_key:
                self._last_team_key = team_key
                try:
                    self.query_one(TeamGridPanel).rebuild(team, swap_val)
                except Exception:
                    pass

            # Grid-selected highlight (in-place, no remount)
            try:
                focused = self.selected if is_swap_pick and self.selected < len(team) else None
                self.query_one(TeamGridPanel).update_selected(focused)
            except Exception:
                pass

            # Bag
            try:
                self.query_one(BagPanel).update_bag(
                    self.state.get("bag", []),
                    follow_on=self.follow_path_on[0],
                    heal_on=self.prioritize_heal_on[0],
                    catch_on=self.prioritize_catch_on[0],
                    autoswap_on=self.autoswap_on[0],
                    autobattle_on=self.autobattle_on[0],
                    mystery_on=self.prioritize_mystery_on[0],
                    catches_on=self.prioritize_catches_on[0],
                )
            except Exception:
                pass

            # Boss
            try:
                self.query_one(BossPanel).update_boss(self.state.get("stage", {}))
            except Exception:
                pass

            # Graph
            acc_indices = [i for i, n in enumerate(nodes_all) if n["accessible"]]
            carousel_sel = self.map_carousel_idx % max(1, len(acc_indices))
            current_node_idx = acc_indices[carousel_sel] if acc_indices else None
            # Best level path — compute/cache when active, starting from the X (last completed) node
            completed_idxs = [i for i, n in enumerate(nodes_all) if n.get("state") == "completed"]
            last_completed = max(completed_idxs) if completed_idxs else 0
            if self.level_path_on[0]:
                lp_key = (last_completed, tuple(n.get("type", "") for n in nodes_all),
                          self.prioritize_catch_on[0], self.prioritize_heal_on[0],
                          self.prioritize_mystery_on[0], self.prioritize_catches_on[0])
                if lp_key != self._last_level_path_key:
                    self._last_level_path_key = lp_key
                    self.best_level_path[0] = _compute_best_level_path(nodes_all, last_completed,
                        _make_extra_score(self.prioritize_catch_on[0], self.prioritize_heal_on[0], self.prioritize_mystery_on[0], self.prioritize_catches_on[0]))
            elif not self.level_path_on[0]:
                self._last_level_path_key = None
                self.best_level_path[0] = []

            highlight = self.best_level_path[0] if self.level_path_on[0] else None
            graph_key = (tuple(n.get("state", "") for n in nodes_all), current_node_idx, tuple(highlight) if highlight else ())
            if graph_key != self._last_graph_key:
                self._last_graph_key = graph_key
                try:
                    self.query_one(MapGraphWidget).rebuild(nodes_all, current_node_idx, highlight_path=highlight)
                except Exception:
                    pass

            # Single node display (normal mode only)
            if not is_special:
                node_items = self._items[:n_nodes]
                # selected within carousel range → sync carousel_idx
                if n_nodes and self.selected < n_nodes:
                    self.map_carousel_idx = self.selected
                carousel_sel = self.map_carousel_idx % max(1, n_nodes)
                try:
                    self.query_one(SingleNodeDisplay).rebuild(node_items, accessible, carousel_sel)
                except Exception:
                    pass

        elif is_catch:
            choices     = self.state.get("choices", [])
            rec_idx: int | None = None
            if self.poke_recommend_on[0] and self._upcoming_boss_types:
                scores = [
                    _catch_recommend_score(c.get("types", []), self._upcoming_boss_types,
                                           self._team_type_coverage)
                    + (50 if self.prioritize_shiny_on[0] and c.get("is_shiny") else 0)
                    for c in choices
                ]
                if scores:
                    rec_idx = scores.index(max(scores))
                    # Move cursor to new recommendation only when choices changed (e.g. after reroll)
                    choices_key = tuple(c.get("name") for c in choices)
                    if choices_key != getattr(self, "_last_catch_choices_key", None):
                        self._last_catch_choices_key = choices_key
                        if self.selected < len(choices):
                            self.selected = rec_idx
            items_key = (tuple(f"{i.label}:{i.enabled}" for i in self._items), self.selected, rec_idx)
            if items_key != self._last_items_key:
                self._last_items_key = items_key
                n = len(choices)
                reroll_items = self._items[n:n * 2]
                strip_items  = self._items[n * 2:]
                try:
                    self.query_one(CatchPokemonPanel).rebuild(choices, strip_items, self.selected, rec_idx, reroll_items)
                except Exception:
                    pass
            return

        elif is_battle:
            # Team panels — only rebuild when HP/active/fainted state changes
            battle_team_key = tuple(
                f"{p['name']}:{p.get('hp_current')}:{p.get('is_active')}:{p.get('is_fainted')}"
                for p in self.state.get("your_team", []) + self.state.get("enemy", [])
            )
            if battle_team_key != self._last_battle_team_key:
                self._last_battle_team_key = battle_team_key
                try:
                    panel = self.query_one(BattlePanel)
                    panels = list(panel.query(BattleSidePanel))
                    if panels:
                        panels[0].rebuild(self.state.get("your_team", []))
                    if len(panels) > 1:
                        panels[1].rebuild(self.state.get("enemy", []))
                except Exception:
                    pass

            # Action strip — update on every selection change
            strip_key = (tuple(f"{i.label}:{i.enabled}" for i in self._items), self.selected)
            if strip_key != self._last_items_key:
                self._last_items_key = strip_key
                try:
                    strip    = self.query_one("#battle-strip", Horizontal)
                    existing = list(strip.query(ActionItem))
                    if len(existing) == len(self._items):
                        for i, w in enumerate(existing):
                            w.refresh_state(self._items[i], i == self.selected)
                    else:
                        strip.query(ActionItem).remove()
                        strip.mount(*[
                            ActionItem(item, i == self.selected)
                            for i, item in enumerate(self._items)
                        ])
                except Exception:
                    pass
            return

        elif is_item_select:
            items_key = (tuple(f"{i.label}:{i.enabled}" for i in self._items), self.selected)
            if items_key != self._last_items_key:
                self._last_items_key = items_key
                choices     = self.state.get("choices", [])
                strip_items = self._items[len(choices):]
                rec_idx: int | None = None
                if self.item_recommend_on[0] and choices:
                    scores = [_item_recommend_score(c, self._item_points_cache,
                                                    self._team_attack_types)
                              for c in choices]
                    if scores:
                        rec_idx = scores.index(max(scores))
                try:
                    self.query_one(ItemSelectPanel).rebuild(choices, strip_items, self.selected,
                                                            rec_idx)
                except Exception:
                    pass
            return

        elif is_main_menu:
            items_key = (
                tuple(f"{i.label}:{i.enabled}" for i in self._items),
                self.selected,
                self.selected_starter,
                self.state.get("selected_gen"),
                self.state.get("logged_in_user"),
            )
            if items_key != self._last_items_key:
                self._last_items_key = items_key
                gen     = self.state.get("selected_gen") or "I"
                starters = get_starters(gen)
                try:
                    self.query_one(MainMenuPanel).rebuild(
                        self.state, self._items, self.selected,
                        self.selected_starter, starters,
                    )
                except Exception:
                    pass
            return

        elif is_team_full:
            team     = self.state.get("team", [])
            incoming = self.state.get("incoming", [])

            # Team grid — only rebuild when data changes
            team_key = tuple(f"{p['name']}:{p.get('level')}" for p in team + incoming)
            if team_key != self._last_team_full_key:
                self._last_team_full_key = team_key
                try:
                    panel = self.query_one(TeamFullPanel)
                    panel.query_one("#tf-incoming-label", Label).update(
                        "  ".join(
                            f"[bold #e8e8ff]{p['name']}[/]  [dim]{p.get('level','')}[/]"
                            + ("  [#f5c518]★[/]" if p.get("is_shiny") else "")
                            for p in incoming
                        ) or "[dim]?[/]"
                    )
                    for ri, row in enumerate(panel.query(".tf-row")):
                        row.query(TeamMemberCard).remove()
                        row.query(Label).remove()
                        children: list = []
                        for ci in range(3):
                            slot = ri * 3 + ci
                            if slot < len(team):
                                children.append(TeamMemberCard(
                                    team[slot], str(slot + 1), slot == self.selected
                                ))
                            if ci < 2:
                                children.append(Label(" ", classes="tf-gap"))
                        if children:
                            row.mount(*children)
                except Exception:
                    pass

            # Selection highlight — in-place update, no remount
            try:
                cards = list(self.query_one(TeamFullPanel).query(TeamMemberCard))
                for i, card in enumerate(cards):
                    card.set_selected(i == self.selected)
            except Exception:
                pass

            # Strip
            strip_key = (tuple(f"{i.label}:{i.enabled}" for i in self._items), self.selected)
            if strip_key != self._last_items_key:
                self._last_items_key = strip_key
                strip_items = self._items[len(team):]
                try:
                    strip    = self.query_one("#tf-strip", Horizontal)
                    existing = list(strip.query(ActionItem))
                    offset   = len(team)
                    if len(existing) == len(strip_items):
                        for i, w in enumerate(existing):
                            w.refresh_state(strip_items[i], (offset + i) == self.selected)
                    else:
                        strip.query(ActionItem).remove()
                        strip.mount(*[
                            ActionItem(item, (offset + i) == self.selected)
                            for i, item in enumerate(strip_items)
                        ])
                except Exception:
                    pass
            return

        else:
            try:
                starter = self.query_one(StarterPickerWidget)
                if self.game_screen == ScreenType.MAIN_MENU:
                    starter.display = True
                    gen = self.state.get("selected_gen") or "I"
                    starter.update_starters(get_starters(gen), self.selected_starter)
                else:
                    starter.display = False
            except Exception:
                pass

        # Rebuild menus when list or selection changes
        items_key = (tuple(f"{i.label}:{i.enabled}" for i in self._items), self.selected)
        if items_key != self._last_items_key:
            self._last_items_key = items_key
            if is_map:
                # Strip: util items (everything after node items)
                if is_swap_pick:
                    util_items   = self._items[len(team):]  # only Cancel/Quit
                    strip_offset = len(team)
                elif is_bag_active:
                    util_items   = self._items              # all items in strip
                    strip_offset = 0
                else:
                    util_items   = self._items[n_nodes:]
                    strip_offset = n_nodes
                try:
                    strip = self.query_one("#map-strip", Horizontal)
                    existing = list(strip.query(ActionItem))
                    sel_in_strip = self.selected - strip_offset
                    if len(existing) == len(util_items):
                        for i, w in enumerate(existing):
                            w.refresh_state(util_items[i], i == sel_in_strip)
                    else:
                        strip.query(ActionItem).remove()
                        strip.mount(*[
                            ActionItem(item, i == sel_in_strip)
                            for i, item in enumerate(util_items)
                        ])
                    widgets = list(strip.query(ActionItem))
                    if 0 <= sel_in_strip < len(widgets):
                        widgets[sel_in_strip].scroll_visible(animate=False)
                except Exception:
                    pass
            else:
                try:
                    self.query_one("#menu-actions", ActionMenu).rebuild(self._items, self.selected)
                except Exception:
                    pass

    # Screens that expose the Utils sub-menu (non-MAP)
    _UTILS_SCREENS = frozenset({
        ScreenType.CATCH_POKEMON, ScreenType.ITEM_SELECT, ScreenType.ITEM_EQUIP,
        ScreenType.TRADE_OFFER, ScreenType.TEAM_FULL,
    })

    def _build_current_items(self) -> list[MenuItem]:
        def noop_refresh():
            return ""

        if self.game_screen == ScreenType.MAP:
            return build_map_items(
                self.state, self.page, noop_refresh,
                self.selected_starter, self.swap_source, self.bag_mode,
                self.utils_mode, self.level_path_on, self.follow_path_on,
                self.prioritize_catch_on, self.prioritize_heal_on, self.autoswap_on,
                self.poke_recommend_on, self.item_recommend_on,
                autobattle_on=self.autobattle_on,
                prioritize_mystery_on=self.prioritize_mystery_on,
                prioritize_shiny_on=self.prioritize_shiny_on,
                prioritize_catches_on=self.prioritize_catches_on,
            )

        self.swap_source[0] = None
        self.bag_mode[0]    = False

        builder = MENU_BUILDERS.get(self.game_screen)
        items   = builder(self.state, self.page, noop_refresh, self.selected_starter) if builder \
                  else _fallback_items(noop_refresh, self.page)

        # Inject Utils entry on supported screens (before Quit)
        if self.game_screen in self._UTILS_SCREENS:
            items.insert(len(items) - 1, MenuItem("Utils", "U", lambda: "SHOW_UTILS"))

        return items

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        # Let pushed screens (JSON viewer, Pokédex) handle their own keys
        if len(self.screen_stack) > 1:
            return
        key   = event.key
        items = self._items
        if not items:
            return
        if key == "f" and not self.utils_mode[0]:
            self.follow_path_on[0] = not self.follow_path_on[0]
            self._follow_last_accessible = frozenset()
        if key == "a" and self.game_screen == ScreenType.MAP and not self.utils_mode[0]:
            self.autoswap_on[0] = not self.autoswap_on[0]
            self._rebuild()
            return
        if key == "h" and self.game_screen == ScreenType.MAP and not self.utils_mode[0]:
            self.prioritize_heal_on[0] = not self.prioritize_heal_on[0]
            self._last_level_path_key = None
            self._force_parse = True
            self._rebuild()
            return
        if key == "c" and self.game_screen == ScreenType.MAP and not self.utils_mode[0]:
            self.prioritize_catch_on[0] = not self.prioritize_catch_on[0]
            self._last_level_path_key = None
            self._force_parse = True
            self._rebuild()
            return
        if key == "m" and self.game_screen == ScreenType.MAP and not self.utils_mode[0]:
            self.prioritize_mystery_on[0] = not self.prioritize_mystery_on[0]
            self._last_level_path_key = None
            self._force_parse = True
            self._rebuild()
            return
        if key == "n" and self.game_screen == ScreenType.MAP and not self.utils_mode[0]:
            self.prioritize_catches_on[0] = not self.prioritize_catches_on[0]
            self._last_level_path_key = None
            self._force_parse = True
            self._rebuild()
            return
        if self.game_screen == ScreenType.MAIN_MENU and key in ("up", "down", "left", "right"):
            self._main_menu_nav(key)
            return
        if self.game_screen == ScreenType.TEAM_FULL and key in ("up", "down", "left", "right"):
            self._team_full_nav(key)
            return
        if self.game_screen == ScreenType.MAP and key in ("up", "down", "left", "right"):
            self._map_nav(key)
            return
        if self.game_screen in (ScreenType.ITEM_SELECT, ScreenType.CATCH_POKEMON) and key in ("up", "down", "left", "right"):
            n = len(self.state.get("choices", []))
            n_rerolls = n if self.game_screen == ScreenType.CATCH_POKEMON else 0
            self._cards_strip_nav(key, n, n_rerolls)
            return
        if key == "up":
            self.selected = (self.selected - 1) % len(items)
            if self.game_screen == ScreenType.MAP:
                n_acc = sum(1 for n in self.state.get("nodes", []) if n["accessible"])
                if self.selected < n_acc:
                    self.map_carousel_idx = self.selected
            self._rebuild()
        elif key == "down":
            self.selected = (self.selected + 1) % len(items)
            if self.game_screen == ScreenType.MAP:
                n_acc = sum(1 for n in self.state.get("nodes", []) if n["accessible"])
                if self.selected < n_acc:
                    self.map_carousel_idx = self.selected
            self._rebuild()
        elif key == "left":
            if self.game_screen in (ScreenType.STARTER_SELECT, ScreenType.BATTLE):
                self.selected = (self.selected - 1) % len(items)
                self._rebuild()
            else:
                gen = self.state.get("selected_gen") or "I"
                self.selected_starter = (self.selected_starter - 1) % max(1, len(get_starters(gen)))
                self._rebuild()
        elif key == "right":
            if self.game_screen in (ScreenType.STARTER_SELECT, ScreenType.BATTLE):
                self.selected = (self.selected + 1) % len(items)
                self._rebuild()
            else:
                gen = self.state.get("selected_gen") or "I"
                self.selected_starter = (self.selected_starter + 1) % max(1, len(get_starters(gen)))
                self._rebuild()
        elif key == "enter":
            self._execute_item(self.selected)
        elif key == "escape":
            if self.game_screen == ScreenType.MAP:
                sv = self.swap_source[0]
                if sv is not None or self.bag_mode[0] or self.utils_mode[0]:
                    self.swap_source[0] = None
                    self.bag_mode[0]    = False
                    self.utils_mode[0]  = False
                    self._follow_last_accessible = frozenset()
                    self._force_parse   = True
                    self._rebuild()
        elif key == "q":
            self.exit()
        elif key == "j" and self.game_screen == ScreenType.MAP:
            state_json = json.dumps(self.state, indent=2)
            self.push_screen(JsonScreen(state_json))
        else:
            char = key.lower() if len(key) == 1 else None
            if char:
                for i, item in enumerate(items):
                    if item.shortcut.lower() == char and item.enabled:
                        self._execute_item(i)
                        break

    def _map_nav(self, direction: str) -> None:
        items        = self._items
        n_nodes      = sum(1 for n in self.state.get("nodes", []) if n["accessible"])
        sv           = self.swap_source[0]
        is_swap_pick = sv in ("swap", "item_pick") or isinstance(sv, int)
        is_bag_active = self.bag_mode[0]

        if is_swap_pick:
            n_team   = len(self.state.get("team", []))
            n_strip  = max(1, len(items) - n_team)
            in_strip = self.selected >= n_team
            strip_idx = self.selected - n_team if in_strip else 0
            col      = self.selected % 2 if not in_strip else min(strip_idx, 1)
            row      = self.selected // 2 if not in_strip else 3
            last_row = (n_team - 1) // 2

            if direction == "right":
                self.selected = (n_team + (strip_idx + 1) % n_strip) if in_strip else row * 2 + (col + 1) % 2
            elif direction == "left":
                self.selected = (n_team + (strip_idx - 1) % n_strip) if in_strip else row * 2 + (col - 1) % 2
            elif direction == "down":
                if in_strip:          self.selected = 0
                elif row >= last_row: self.selected = n_team
                else:                 self.selected = min((row + 1) * 2 + col, n_team - 1)
            elif direction == "up":
                if in_strip:
                    target = last_row * 2 + min(strip_idx, 1)
                    self.selected = min(target, n_team - 1)
                elif row == 0:  self.selected = n_team + n_strip - 1
                else:           self.selected = (row - 1) * 2 + col

            self.selected = max(0, min(self.selected, len(items) - 1))
            self._rebuild()
            return

        if is_bag_active or self.utils_mode[0] or n_nodes == 0:
            delta = -1 if direction in ("up", "left") else 1
            self.selected = (self.selected + delta) % len(items)
            self._rebuild()
            return

        n_strip   = max(1, len(items) - n_nodes)
        in_strip  = self.selected >= n_nodes
        strip_idx = self.selected - n_nodes if in_strip else 0
        node_idx  = self.selected if not in_strip else 0

        if direction == "right":
            if in_strip:
                self.selected = n_nodes + (strip_idx + 1) % n_strip
            else:
                self.selected = (node_idx + 1) % n_nodes
                self.map_carousel_idx = self.selected
        elif direction == "left":
            if in_strip:
                self.selected = n_nodes + (strip_idx - 1) % n_strip
            else:
                self.selected = (node_idx - 1) % n_nodes
                self.map_carousel_idx = self.selected
        elif direction == "down":
            if in_strip:
                self.selected = 0
                self.map_carousel_idx = 0
            else:
                self.selected = n_nodes
        elif direction == "up":
            if in_strip:
                self.selected = min(strip_idx, n_nodes - 1)
                self.map_carousel_idx = self.selected
            else:
                self.selected = n_nodes + n_strip - 1

        self.selected = max(0, min(self.selected, len(items) - 1))
        self._rebuild()

    def _cards_strip_nav(self, direction: str, n_cards: int, n_rerolls: int = 0) -> None:
        items       = self._items
        reroll_start = n_cards
        strip_start  = n_cards + n_rerolls
        n_strip      = max(1, len(items) - strip_start)
        sel          = self.selected

        in_cards   = sel < n_cards
        in_rerolls = n_rerolls > 0 and reroll_start <= sel < strip_start
        in_strip   = sel >= strip_start

        card_idx   = sel if in_cards else max(0, sel - (0 if in_cards else (n_rerolls if in_rerolls else n_cards + n_rerolls)))
        reroll_idx = sel - reroll_start if in_rerolls else 0
        strip_idx  = sel - strip_start if in_strip else 0

        if direction == "right":
            if in_cards:
                self.selected = (sel + 1) % max(1, n_cards)
            elif in_rerolls:
                self.selected = reroll_start + (reroll_idx + 1) % max(1, n_rerolls)
            else:
                self.selected = strip_start + (strip_idx + 1) % n_strip
        elif direction == "left":
            if in_cards:
                self.selected = (sel - 1) % max(1, n_cards)
            elif in_rerolls:
                self.selected = reroll_start + (reroll_idx - 1) % max(1, n_rerolls)
            else:
                self.selected = strip_start + (strip_idx - 1) % n_strip
        elif direction == "down":
            if in_cards:
                self.selected = (reroll_start + min(sel, n_rerolls - 1)) if n_rerolls else strip_start
            elif in_rerolls:
                self.selected = strip_start
            # already in strip — no-op
        elif direction == "up":
            if in_strip:
                self.selected = (reroll_start + min(strip_idx, n_rerolls - 1)) if n_rerolls else min(strip_idx, n_cards - 1)
            elif in_rerolls:
                self.selected = min(reroll_idx, n_cards - 1)
            else:
                self.selected = strip_start + n_strip - 1

        self.selected = max(0, min(self.selected, len(items) - 1))
        self._rebuild()

    def _main_menu_nav(self, direction: str) -> None:
        items      = self._items
        n_left     = 3   # Normal Mode, Nuzlocke, Battle Tower
        gens       = self.state.get("available_gens", [])
        starters   = get_starters(self.state.get("selected_gen") or "I")
        n_right    = len(gens) + len(starters)
        strip_start = n_left + n_right
        n_strip    = max(1, len(items) - strip_start)
        sel        = self.selected

        in_left  = 0 <= sel < n_left
        in_right = n_left <= sel < strip_start
        in_strip = sel >= strip_start

        left_row  = sel
        right_row = sel - n_left
        strip_idx = sel - strip_start

        if direction == "right":
            if in_left:
                self.selected = n_left + min(left_row, n_right - 1)
            elif in_strip:
                self.selected = strip_start + (strip_idx + 1) % n_strip
        elif direction == "left":
            if in_right:
                self.selected = min(right_row, n_left - 1)
            elif in_strip:
                self.selected = strip_start + (strip_idx - 1) % n_strip
        elif direction == "down":
            if in_left:
                self.selected = left_row + 1 if left_row < n_left - 1 else strip_start
            elif in_right:
                self.selected = n_left + right_row + 1 if right_row < n_right - 1 else strip_start
            elif in_strip:
                self.selected = 0
        elif direction == "up":
            if in_left:
                self.selected = left_row - 1 if left_row > 0 else strip_start + n_strip - 1
            elif in_right:
                self.selected = n_left + right_row - 1 if right_row > 0 else strip_start + n_strip - 1
            elif in_strip:
                self.selected = n_left - 1

        self.selected = max(0, min(self.selected, len(items) - 1))
        self._rebuild()

    def _queue_autoswap(self, team: list, poke_type: str) -> None:
        desired = _compute_autoswap_order(team, poke_type)
        if desired == list(range(len(team))):
            return
        current = list(range(len(team)))
        pg = self.page
        for i in range(len(current)):
            if current[i] == desired[i]:
                continue
            j = current.index(desired[i])
            src, dst = i, j
            def do_autoswap(s=src, d=dst):
                pg.locator(".map-panel-left .team-slot").nth(s).drag_to(
                    pg.locator(".map-panel-left .team-slot").nth(d)
                )
                pg.mouse.move(0, 0)
                return f"Autoswap: {s} ↔ {d}"
            self._task_queue.put((do_autoswap, [None], threading.Event()))
            current[i], current[j] = current[j], current[i]

    def _team_full_nav(self, direction: str) -> None:
        items   = self._items
        n_team  = len(self.state.get("team", []))   # 6
        n_strip = max(1, len(items) - n_team)
        sel     = self.selected
        in_strip = sel >= n_team
        strip_idx = sel - n_team if in_strip else 0
        col  = sel % 3 if not in_strip else strip_idx
        row  = sel // 3 if not in_strip else 2   # 0, 1, or 2 (strip)

        if direction == "right":
            if in_strip:
                self.selected = n_team + (strip_idx + 1) % n_strip
            else:
                self.selected = row * 3 + (col + 1) % 3
        elif direction == "left":
            if in_strip:
                self.selected = n_team + (strip_idx - 1) % n_strip
            else:
                self.selected = row * 3 + (col - 1) % 3
        elif direction == "down":
            if in_strip:
                self.selected = min(strip_idx, 2)           # row 0, same col
            elif row == 0:
                self.selected = sel + 3                      # row 1
            else:
                self.selected = n_team                       # strip item 0
        elif direction == "up":
            if in_strip:
                self.selected = n_team - 3 + min(strip_idx, 2)   # row 1, clamped col
            elif row == 1:
                self.selected = sel - 3                      # row 0
            else:
                self.selected = n_team + n_strip - 1         # last strip item

        self.selected = max(0, min(self.selected, len(items) - 1))
        self._rebuild()

    def _execute_item_by_result(self, result: str) -> None:
        """Dispatch a result string as if it came from _execute_item (called from main thread)."""
        if result == "SHOW_UTILS":
            self.push_screen(UtilsScreen(self))
        elif result == "SHOW_LEVEL_PATH_DEBUG":
            self._execute_item_debug()

    def _execute_item_debug(self) -> None:
        """Build and show the full debug screen (must be called from main thread)."""
        nodes = self.state.get("nodes", [])
        team  = self.state.get("team", [])
        path  = self.best_level_path[0]
        lines: list[str] = []

        # ── Level path ───────────────────────────────────────────
        extra_fn = _make_extra_score(
            self.prioritize_catch_on[0], self.prioritize_heal_on[0],
            self.prioritize_mystery_on[0], self.prioritize_catches_on[0],
        )
        prio_flags = []
        if self.prioritize_catch_on[0]:   prio_flags.append("1st Catch")
        if self.prioritize_heal_on[0]:    prio_flags.append("Heal")
        if self.prioritize_mystery_on[0]: prio_flags.append("Mystery")
        if self.prioritize_catches_on[0]: prio_flags.append("Catches")
        prio_str = f"  [{', '.join(prio_flags)}]" if prio_flags else ""
        if not path:
            lines.append("No path computed. Enable Level Path first (U).")
        else:
            total = sum(
                _node_score(nodes[i].get("type", "")) + (extra_fn(i, nodes[i]) if extra_fn else 0)
                for i in path if i < len(nodes)
            )
            lines.append(f"Best Level Path  (total score: {total:.1f}){prio_str}\n")
            for i in path:
                if i >= len(nodes): continue
                ntype = nodes[i].get("type", "?")
                base  = _node_score(ntype)
                bonus = extra_fn(i, nodes[i]) if extra_fn else 0.0
                bonus_str = f"  +{bonus:.0f} prio" if bonus else ""
                lines.append(f"  Node {i:2d}  {ntype:<20}  +{base:.1f}{bonus_str}")

        # ── Autoswap order ───────────────────────────────────────
        if team:
            poke_type = ""
            new_acc   = frozenset(n["index"] for n in nodes if n["accessible"])
            for ni in path:
                if ni < len(nodes) and ni in new_acc:
                    poke_type = nodes[ni].get("poke_type", "")
                    break
            lines.append(f"\nAutoswap order  (vs {poke_type or '?'})\n")
            order = _compute_autoswap_order(team, poke_type)
            for rank, slot in enumerate(order):
                if slot >= len(team): continue
                p    = team[slot]
                name = p.get("name", "?")
                types = "/".join(p.get("types", []))
                lv   = p.get("level") or "?"
                atk  = _autoswap_score(p.get("types", []), poke_type)
                dfn  = _defense_score(p.get("types", []), poke_type)
                lines.append(f"  {rank+1}. {name:<12} Lv{lv:<3}  [{types}]  atk×{atk:.1f}  def×{dfn:.1f}")

        # ── Catch recommendation ─────────────────────────────────
        if self.game_screen == ScreenType.CATCH_POKEMON and self._upcoming_boss_types:
            choices    = self.state.get("choices", [])
            boss_types = self._upcoming_boss_types
            weights    = [3, 2, 1]
            boss_labels = "  ".join(f"{bt} ×{weights[i]}" for i, bt in enumerate(boss_types[:3]))
            lines.append(f"\nCatch Recommendation  (boss types: {boss_labels})\n")
            coverage = self._team_type_coverage
            scored = []
            for c in choices:
                ptypes      = c.get("types", [])
                shiny_bonus = 50 if self.prioritize_shiny_on[0] and c.get("is_shiny") else 0
                total       = _catch_recommend_score(ptypes, boss_types, coverage) + shiny_bonus
                scored.append((c, ptypes, total, shiny_bonus))
            scored.sort(key=lambda x: -x[2])
            for rank, (c, ptypes, total, shiny_bonus) in enumerate(scored):
                star      = "★ " if rank == 0 else "  "
                tstr      = "/".join(ptypes)
                shiny_str = "  +50 shiny" if shiny_bonus else ""
                lines.append(f"  {star}{c.get('name','?'):<14} [{tstr:<16}]  total = {total:.2f}{shiny_str}")
                for i, bt in enumerate(boss_types[:3]):
                    if not bt: continue
                    dmg = _defense_score(ptypes, bt)
                    res = (1.0 / dmg) if dmg else 4.0
                    lines.append(f"      {bt:<14} (×{weights[i]}):  dmg={dmg:.2f}  res={res:.2f}  → {res*weights[i]:.2f}")
                overlapping = [t for t in ptypes if t.capitalize() in coverage]
                if overlapping:
                    lines.append(f"      team overlap: {'/'.join(overlapping)}  → ×0.5 per type")

        # ── Item recommendation ──────────────────────────────────
        if self.game_screen == ScreenType.ITEM_SELECT:
            choices      = self.state.get("choices", [])
            pts_map      = self._item_points_cache
            attack_types = self._team_attack_types
            lines.append(f"\nItem Recommendation  (attack types: {', '.join(sorted(attack_types)) or 'none'})\n")
            scored = []
            for c in choices:
                name  = c.get("name", "?")
                base  = float(pts_map.get(name, 0))
                bonus = 0.0
                m = _ITEM_TYPE_BOOST_RE.search(c.get("description", ""))
                if m:
                    item_type = m.group(1).capitalize()
                    bonus = 500.0 if item_type in attack_types else -100.0
                scored.append((c, base, bonus, base + bonus))
            scored.sort(key=lambda x: -x[3])
            for rank, (c, base, bonus, total) in enumerate(scored):
                star      = "★ " if rank == 0 else "  "
                bonus_str = f"+{bonus:.0f}" if bonus >= 0 else f"{bonus:.0f}"
                m2 = _ITEM_TYPE_BOOST_RE.search(c.get("description", ""))
                type_tag = f"  [{m2.group(1).capitalize()} boost]" if m2 else ""
                lines.append(f"  {star}{c.get('name','?'):<20}  base={base:.0f}  bonus={bonus_str:<5}  total={total:.0f}{type_tag}")

        self.push_screen(JsonScreen("\n".join(lines)))

    @work(thread=True)
    def _execute_item(self, index: int) -> None:
        items  = self._items
        result = self.run_in_browser(lambda: _execute(items, index))
        if result == "QUIT":
            self.call_from_thread(self.exit)
        elif result == "SHOW_UTILS":
            self.call_from_thread(self.push_screen, UtilsScreen(self))
        elif result == "SHOW_POKEDEX":
            self.call_from_thread(self.push_screen, PokedexScreen(self))
        elif result == "SHOW_JSON":
            state_json = json.dumps(self.state, indent=2)
            self.call_from_thread(self.push_screen, JsonScreen(state_json))
        elif result == "FOLLOW_PATH_TOGGLED":
            self._follow_last_accessible = frozenset()
            self._force_parse = True
            self.call_from_thread(self._rebuild)
        elif result == "AUTOBATTLE_TOGGLED":
            self._force_parse = True
            self.call_from_thread(self._rebuild)
        elif result == "Level Path toggled":
            self._follow_last_accessible = frozenset()
            self._force_parse = True
            self.call_from_thread(self._rebuild)
        elif result == "SHOW_LEVEL_PATH_DEBUG":
            self.call_from_thread(self._execute_item_debug)
        elif isinstance(result, str) and result.startswith("SET_STARTER:"):
            idx = int(result.split(":")[1])
            def _apply(i=idx):
                self.selected_starter = i
                self._rebuild()
            self.call_from_thread(_apply)
        else:
            # Force a fresh parse on the next browser loop cycle so state-changing
            # actions (swap, equip, etc.) are reflected even if the DOM hash matches.
            self._force_parse = True
            # If utils/follow-path mode was just exited, reset follow tracker so
            # the next map state triggers the auto-execute immediately.
            if not self.utils_mode[0]:
                self._follow_last_accessible = frozenset()
            self.call_from_thread(self._rebuild)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    PokelikeApp().run()
    sys.stdout.write(
        "\033[0m"
        "\033[39m"
        "\033[49m"
        "\033]104\007"
        "\033]110\007"
        "\033]111\007"
        "\033[?25h"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
