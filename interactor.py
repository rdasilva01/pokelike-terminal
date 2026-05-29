import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Static
from textual.binding import Binding
from textual import work

from browser import connect_to_chrome
from screen_detector import detect, ScreenType
from parsers.battle import BattleParser
from parsers.champion import ChampionParser
from parsers.pokemon_received import PokemonReceivedParser
from parsers.trade_offer import TradeOfferParser
from parsers.catch_pokemon import CatchPokemonParser
from parsers.item_equip import ItemEquipParser
from parsers.item_select import ItemSelectParser
from parsers.main_menu import MainMenuParser
from parsers.map_screen import MapParser
from parsers.starter_select import StarterSelectParser

console = Console()

PARSER_MAP = {
    ScreenType.MAIN_MENU:      MainMenuParser(),
    ScreenType.STARTER_SELECT: StarterSelectParser(),
    ScreenType.MAP:            MapParser(),
    ScreenType.BATTLE:         BattleParser(),
    ScreenType.TRADE_OFFER:    TradeOfferParser(),
    ScreenType.POKEMON_RECEIVED: PokemonReceivedParser(),
    ScreenType.CATCH_POKEMON:  CatchPokemonParser(),
    ScreenType.ITEM_SELECT:    ItemSelectParser(),
    ScreenType.ITEM_EQUIP:     ItemEquipParser(),
    ScreenType.CHAMPION:       ChampionParser(),
}

ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}

AUTO_REFRESH_INTERVAL = 0.5  # seconds

# Starters per gen: (display_letter, rich_color)
STARTERS: dict[str | None, list[tuple[str, str]]] = {
    "I":  [("B", "green3"),      ("C", "dark_orange"), ("S", "dodger_blue1")],
    "II": [("C", "green3"),      ("C", "dark_orange"), ("T", "dodger_blue1")],
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
# Rendering
# ---------------------------------------------------------------------------

def render_starter_inline(starters: list[tuple[str, str]], selected: int) -> Text:
    """Render B C S (or C C T) with the selected one bold and colored."""
    t = Text()
    for i, (letter, color) in enumerate(starters):
        if i == selected:
            t.append(f" {letter} ", style=f"bold {color} on grey23")
        else:
            t.append(f" {letter} ", style="dim")
    return t


def render(
    screen: ScreenType,
    state: dict,
    items: list[MenuItem],
    selected: int,
    refresh_flash: bool,
    selected_starter: int,
    swap_source=None,
    bag_mode=None,
) -> Align:
    try:
        term_w = console.size.width
    except Exception:
        term_w = os.get_terminal_size().columns
    panel_w = min(92, term_w - 4)

    layout = Table.grid(padding=(0, 1))
    layout.add_column(ratio=1)

    # Header
    dot = "[bold yellow]●[/]" if refresh_flash else "[dim]·[/]"

    if screen == ScreenType.CATCH_POKEMON:
        choices = state.get("choices", [])
        parts = [c["name"] for c in choices]
        header = Text.assemble(
            ("  CATCH POKÉMON  ", "bold cyan"),
            ("  ".join(parts), "white"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.ITEM_SELECT:
        choices = state.get("choices", [])
        parts = [c["name"] for c in choices]
        header = Text.assemble(
            ("  ITEM FOUND  ", "bold cyan"),
            ("  ".join(parts), "white"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.ITEM_EQUIP:
        item_name = state.get("item_name", "?")
        item_desc = state.get("item_desc", "")
        is_tutor  = state.get("is_move_tutor", False)
        label     = "  MOVE TUTOR  " if is_tutor else "  EQUIP ITEM  "
        header = Text.assemble(
            (label, "bold cyan"),
            (item_desc if is_tutor else item_name, "white"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.POKEMON_RECEIVED:
        p = state.get("pokemon") or {}
        title = state.get("title", "Pokémon received!")
        shiny = " ★" if p.get("is_shiny") else ""
        types = "/".join(p.get("types", []))
        header = Text.assemble(
            ("  RECEIVED  ", "bold cyan"),
            (f"{p.get('name','?')}{shiny}", "bold white"),
            (f"  {p.get('level','')}  [{types}]", "dim"),
            (f"  {p.get('move','')} {p.get('move_power','')}", "white"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.CHAMPION:
        run_count = state.get("run_count", "")
        team = state.get("team", [])
        names = "  ".join(f"{p['name']} {p['level']}" for p in team)
        header = Text.assemble(
            ("  CHAMPION!  ", "bold yellow"),
            (run_count, "gold1"),
            (f"  {names}", "white"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.TRADE_OFFER:
        members = state.get("members", [])
        parts = [f"{m['name']} {m['level']}" for m in members]
        header = Text.assemble(("  TRADE OFFER  ", "bold cyan"), ("  |  ".join(parts), "white"))
        header.append_text(Text.from_markup(f"   {dot}"))
    elif screen == ScreenType.BATTLE:
        header_txt = state.get("header", "Battle")
        can_cont   = state.get("can_continue", False)
        cont_hint  = "  [bold green]CONTINUE READY[/]" if can_cont else ""
        header = Text.assemble(("  BATTLE  ", "bold cyan"), (header_txt, "white"))
        header.append_text(Text.from_markup(f"{cont_hint}   {dot}"))
    elif screen == ScreenType.MAP:
        stage = state.get("stage", {})
        boss  = stage.get("boss") or "?"
        btype = stage.get("boss_type") or ""
        stage_num = stage.get("number") or "?"
        badges = state.get("badges", 0)
        header = Text.assemble(
            ("  MAP ", "dim"),
            (f"{stage_num}", "bold cyan"),
            (f"  vs {boss}", "bold white"),
            (f" ({btype})", "dim"),
            ("  badges: ", "dim"),
            (str(badges), "yellow"),
        )
        header.append_text(Text.from_markup(f"   {dot}"))
    else:
        user = state.get("logged_in_user") or "not logged in"
        gen  = state.get("selected_gen") or "I"
        gens = state.get("available_gens", [])
        gen_display = "  ".join(
            f"[bold yellow]{ROMAN.get(g, g)}[/]" if g == gen else f"[dim]{ROMAN.get(g, g)}[/]"
            for g in gens
        )
        header = Text.assemble(
            ("  ", ""),
            (screen.name.replace("_", " "), "bold cyan"),
            ("    user: ", "dim"),
            (user, "green"),
            ("    gen: ", "dim"),
        )
        header.append_text(Text.from_markup(f"{gen_display}   {dot}"))

    layout.add_row(Panel(header, box=box.SIMPLE, style="on grey11"))

    # Menu table
    menu_table = Table.grid(padding=(0, 2))
    menu_table.add_column(width=2)
    menu_table.add_column(min_width=22, no_wrap=True)
    menu_table.add_column(width=6)

    for i, item in enumerate(items):
        is_sel = (i == selected)
        if not item.enabled:
            arrow = Text(">", style="dim yellow") if is_sel else Text(" ")
            label = Text(item.label, style="dim strike")
            key   = Text(f"[{item.shortcut}]", style="dim")
        elif is_sel:
            arrow = Text("❯", style="bold yellow")
            label = Text(item.label, style="bold white on grey23")
            key   = Text(f"[{item.shortcut}]", style="bold yellow")
        else:
            arrow = Text(" ")
            label = Text(item.label, style="white")
            key   = Text(f"[{item.shortcut}]", style="dim cyan")
        menu_table.add_row(arrow, label, key)

    if screen == ScreenType.MAIN_MENU:
        gen = state.get("selected_gen") or "I"
        starters = get_starters(gen)
        starter_widget = render_starter_inline(starters, selected_starter)
        side = Table.grid(padding=(1, 1))
        side.add_column()
        side.add_row(Text("starter", style="dim"))
        side.add_row(starter_widget)
        side.add_row(Text("◀ ▶ pick", style="dim"))
        outer = Table.grid()
        outer.add_column(ratio=1)
        outer.add_column(width=13)
        outer.add_row(menu_table, side)
        layout.add_row(Panel(outer, title="[dim]actions[/]", box=box.ROUNDED, padding=(1, 2)))
        footer_hint = "↑↓ navigate   ◀▶ starter   Enter / letter select"
    elif screen == ScreenType.MAP:
        # --- left: team panel ---
        swap_val = swap_source[0] if swap_source is not None else None
        swap_src_idx = swap_val if isinstance(swap_val, int) else None
        team = state.get("team", [])

        def make_poke_block(pi, p):
            hp        = p.get("hp_pct", 100)
            hp_cur    = p.get("hp_current")
            hp_max    = p.get("hp_max")
            move_tier = p.get("move_tier")
            types     = p.get("types", [])
            color     = "green3" if hp > 50 else "yellow" if hp > 20 else "red"
            hp_str    = f"{hp_cur}/{hp_max}" if hp_cur is not None else f"{hp}%"
            move_str  = (f"T{move_tier} {types[0]}" if move_tier is not None and types else "")
            if swap_src_idx == pi:
                name_style = "bold cyan reverse"
            elif swap_val == "src":
                name_style = f"bold {color} dim"
            else:
                name_style = f"bold {color}"
            col = Table.grid()
            col.add_column()
            col.add_row(Text(f"{pi + 1}. {p['name']}", style=name_style))
            col.add_row(Text("/".join(types), style="dim"))
            col.add_row(Text(f"Lv{p['level']}  {hp_str}", style=color))
            if move_str:
                col.add_row(Text(move_str, style="dim"))
            return col

        if len(team) > 3:
            left_team  = team[:3]
            right_team = team[3:]
            col_a = Table.grid(padding=(0, 0))
            col_a.add_column()
            for pi, p in enumerate(left_team):
                col_a.add_row(make_poke_block(pi, p))
                col_a.add_row(Text(""))
            col_b = Table.grid(padding=(0, 0))
            col_b.add_column()
            for pi, p in enumerate(right_team):
                col_b.add_row(make_poke_block(pi + 3, p))
                col_b.add_row(Text(""))
            two_col = Table.grid(padding=(0, 2))
            two_col.add_column(ratio=1)
            two_col.add_column(ratio=1)
            two_col.add_row(col_a, col_b)
            team_table = two_col
        else:
            team_table = Table.grid(padding=(0, 1))
            team_table.add_column()
            for pi, p in enumerate(team):
                team_table.add_row(make_poke_block(pi, p))
                team_table.add_row(Text(""))

        # --- right: bag panel ---
        bag_table = Table.grid(padding=(0, 1))
        bag_table.add_column()
        bag = state.get("bag", [])
        if bag:
            for item in bag:
                bag_table.add_row(Text(item["name"], style="white"))
        else:
            bag_table.add_row(Text("empty", style="dim"))

        three_col = Table.grid(padding=(0, 1))
        three_col.add_column(ratio=3)
        three_col.add_column(ratio=4)
        three_col.add_column(ratio=1)
        three_col.add_row(
            Panel(team_table, title="[dim]team[/]", box=box.SIMPLE),
            Panel(menu_table, title="[dim]actions[/]", box=box.ROUNDED, padding=(1, 1)),
            Panel(bag_table,  title="[dim]bag[/]",  box=box.SIMPLE),
        )
        layout.add_row(three_col)
        _bag_open = bag_mode[0] if bag_mode is not None else False
        if _bag_open:
            footer_hint = "Pick item to equip   X cancel"
        elif swap_val == "src":
            footer_hint = "Pick Pokémon to move   X cancel"
        elif isinstance(swap_val, int):
            footer_hint = "Pick swap target   X cancel"
        else:
            footer_hint = "↑↓ navigate   Enter / letter select   B bag   W swap"
    else:
        layout.add_row(Panel(menu_table, title="[dim]actions[/]", box=box.ROUNDED, padding=(1, 2)))
        footer_hint = "↑↓ navigate   Enter / letter select"

    layout.add_row(Text(f"  {footer_hint}", style="dim"))

    panel = Panel(layout, title="[bold yellow]POKELIKE[/] [dim]automation[/]", box=box.DOUBLE_EDGE, width=panel_w)
    return Align(panel, align="center", vertical="middle")


# ---------------------------------------------------------------------------
# Auto-starter click (called when STARTER_SELECT screen is detected)
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

    gen = state.get("selected_gen") or "I"
    starters = get_starters(gen)

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

    gens = state.get("available_gens", [])
    selected_gen = state.get("selected_gen")

    items: list[MenuItem] = [
        MenuItem("Normal Mode",  "N", click_btn("Normal Mode")),
        MenuItem("Nuzlocke",     "Z", click_btn("Nuzlocke")),
        MenuItem("Battle Tower", "B", click_btn("Battle Tower")),
    ]
    for g in gens:
        num = ROMAN.get(g, g)
        items.append(MenuItem(f"Switch to Gen {num}", num, click_gen(g), enabled=(g != selected_gen)))

    def reload_page():
        page.reload()
        return "Page reloaded."

    def open_dex_main():
        return "SHOW_POKEDEX"

    items += [
        MenuItem("Pokédex",     "D", open_dex_main),
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def show_raw_json(state: dict) -> str:
    """Legacy blocking function — kept for reference. Not used in Textual mode."""
    lines = json.dumps(state, indent=2).splitlines()
    return ""


def show_pokedex(page) -> str:
    """Legacy blocking function — kept for reference. Not used in Textual mode."""
    return ""


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
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


NODE_TYPE_LABEL = {
    "trainer":       "Trainer battle",
    "wild_encounter":"Wild encounter",
    "catch_pokemon": "Catch Pokémon",
    "move_tutor":    "Move tutor",
    "mystery":       "Mystery event",
    "pokecenter":    "Pokémon Center",
    "shop":          "Shop",
    "item":          "Item",
    "trade":         "Trade",
    "boss":          "GYM LEADER",
    "start":         "Start",
}


def build_map_items(state: dict, page, refresh_fn: Callable, selected_starter: int,
                    swap_source=None, bag_mode=None) -> list[MenuItem]:
    team = state.get("team", [])
    bag  = state.get("bag", [])
    nodes = state.get("nodes", [])
    accessible = [n for n in nodes if n["accessible"]]
    digit_shortcuts = "123456789"

    def reload_page():
        page.reload()
        return "Page reloaded."

    def _cancel_all(msg):
        if swap_source is not None: swap_source[0] = None
        if bag_mode   is not None: bag_mode[0]   = False
        return msg

    # --- bag pick mode ---
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

    # --- swap source-pick mode ---
    if swap_source is not None and swap_source[0] == "src":
        items = []
        for i, p in enumerate(team):
            shortcut = digit_shortcuts[i] if i < len(digit_shortcuts) else "?"
            def pick(idx=i):
                swap_source[0] = idx
                return f"Picked {team[idx]['name']} — choose swap target"
            items.append(MenuItem(p["name"], shortcut, pick))
        items += [
            MenuItem("Cancel", "X", lambda: _cancel_all("Swap cancelled")),
            MenuItem("Quit",   "Q", lambda: "QUIT"),
        ]
        return items

    # --- swap destination-pick mode ---
    if swap_source is not None and isinstance(swap_source[0], int):
        src_idx = swap_source[0]
        items = []
        dest_num = 0
        for i, p in enumerate(team):
            if i == src_idx:
                continue
            shortcut = digit_shortcuts[dest_num] if dest_num < len(digit_shortcuts) else "?"
            dest_num += 1
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

    # --- normal mode ---
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

    def sprite_to_class(sprite: str) -> str:
        return re.sub(r"([A-Z])", r" \1", sprite).strip().title()

    items = []
    for i, node in enumerate(accessible):
        label = NODE_TYPE_LABEL.get(node["type"], node["type"].replace("_", " ").title())
        if node["type"] == "trainer":
            poke_type = node.get("poke_type", "")
            label = f"Trainer battle  [{poke_type}]" if poke_type else "Trainer battle"
        shortcut = node_shortcuts[i] if i < len(node_shortcuts) else "?"
        items.append(MenuItem(label, shortcut, click_node(node["index"])))

    if bag_mode is not None and bag:
        def open_bag():
            bag_mode[0] = True
            return "Select item to equip"
        items.append(MenuItem("Bag", "B", open_bag))

    if swap_source is not None and len(team) > 1:
        def enter_swap():
            swap_source[0] = "src"
            return "Pick Pokémon to move"
        items.append(MenuItem("Swap Pokémon", "W", enter_swap))

    def open_dex():
        return "SHOW_POKEDEX"

    items += [
        MenuItem("Pokédex",     "D", open_dex),
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def build_catch_pokemon_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    choices = state.get("choices", [])

    def pick(idx):
        def _action():
            page.locator(".poke-choice-wrap").nth(idx).click()
            return f"Selected {choices[idx]['name']}"
        return _action

    def skip():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('Skip') && b.getBoundingClientRect().width > 0)
            if (btn) btn.click()
        }""")
        return "Skipped."

    items = []
    for i, c in enumerate(choices):
        shiny = " ★" if c.get("is_shiny") else ""
        caught = " ✓" if c.get("is_caught") else ""
        types = "/".join(c.get("types", []))
        label = f"{c['name']}{shiny}{caught}  Lv{c['level']}  [{types}]"
        items.append(MenuItem(label, str(i + 1), pick(i)))

    items.append(MenuItem("Skip (flee)", "S", skip))

    def reload_page():
        page.reload()
        return "Page reloaded."

    items += [
        MenuItem("Raw JSON", "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",    "R", refresh_fn),
        MenuItem("Quit",       "Q", lambda: "QUIT"),
    ]
    return items


def build_pokemon_received_items(state: dict, page, refresh_fn: Callable, selected_starter: int) -> list[MenuItem]:
    def do_continue():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('.screen.active .btn-primary'))
                .find(b => b.textContent.trim() === 'Continue')
            if (btn) btn.click()
        }""")
        return "Continuing..."

    def reload_page():
        page.reload()
        return "Page reloaded."

    return [
        MenuItem("Continue",    "C", do_continue),
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]


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
    items = []
    for i, m in enumerate(members):
        types = "/".join(m.get("types", []))
        label = f"Trade {m['name']}  {m['level']}  [{types}]  → random +3 lvls"
        items.append(MenuItem(label, shortcuts[i] if i < len(shortcuts) else "?", trade(i)))

    items.append(MenuItem("Decline", "D", decline))
    items += [
        MenuItem("Raw JSON",    "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
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
        MenuItem("Refresh",     "R", refresh_fn),
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
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Keep in Bag')
            if (btn) btn.click()
        }""")
        return "Kept in bag."

    def cancel():
        page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => ['Cancel', 'Skip'].includes(b.textContent.trim()))
            if (btn) btn.click()
        }""")
        return "Cancelled."

    is_tutor       = state.get("is_move_tutor", False)
    has_keep_in_bag = state.get("has_keep_in_bag", True)
    shortcuts = "123456789"
    items = []
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
        MenuItem("Refresh",     "R", refresh_fn),
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
        MenuItem("Refresh",     "R", refresh_fn),
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
        MenuItem("Play Again",       "P", click_btn("Play Again")),
        MenuItem("Climb the Tower",  "T", click_btn("🗼 Climb the Tower")),
        MenuItem("Hall of Fame",     "H", click_btn("🏛️ Hall of Fame")),
        MenuItem("Raw JSON",         "J", lambda: "SHOW_JSON"),
        MenuItem("Reload Page",      "R", reload_page),
        MenuItem("Quit",             "Q", lambda: "QUIT"),
    ]


MENU_BUILDERS = {
    ScreenType.MAIN_MENU:      build_main_menu_items,
    ScreenType.STARTER_SELECT: build_starter_select_items,
    ScreenType.MAP:            build_map_items,
    ScreenType.BATTLE:         build_battle_items,
    ScreenType.TRADE_OFFER:      build_trade_offer_items,
    ScreenType.POKEMON_RECEIVED: build_pokemon_received_items,
    ScreenType.CATCH_POKEMON:  build_catch_pokemon_items,
    ScreenType.ITEM_SELECT:    build_item_select_items,
    ScreenType.ITEM_EQUIP:     build_item_equip_items,
    ScreenType.CHAMPION:       build_champion_items,
}


# ---------------------------------------------------------------------------
# Helpers shared with old run_tui
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
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]


def _unknown_state(page, screen: ScreenType) -> dict:
    return {"screen": "unknown", "title": page.title(), "url": page.url}


# ---------------------------------------------------------------------------
# Textual screens
# ---------------------------------------------------------------------------

class JsonScreen(Screen):
    """Full-screen JSON viewer with scroll support."""

    def __init__(self, json_text: str) -> None:
        super().__init__()
        self.json_text = json_text
        self.lines = json_text.splitlines()
        self.offset = 0

    def compose(self) -> ComposeResult:
        yield Static(id="json_display")

    def on_mount(self) -> None:
        self._update_display()

    def _make_renderable(self):
        try:
            term_h = max(5, self.app.size.height - 6)
        except Exception:
            term_h = max(5, os.get_terminal_size().lines - 6)
        visible = self.lines[self.offset:self.offset + term_h]
        syntax = Syntax(
            "\n".join(visible), "json",
            theme="monokai", line_numbers=True, start_line=self.offset + 1
        )
        pct = f"{self.offset + 1}-{min(self.offset + term_h, len(self.lines))}/{len(self.lines)}"
        return Panel(
            syntax,
            title="[bold yellow]RAW JSON[/] [dim](↑↓ scroll · any other key to go back)[/]",
            subtitle=f"[dim]{pct}[/]",
            box=box.DOUBLE_EDGE,
        )

    def _update_display(self) -> None:
        self.query_one("#json_display", Static).update(self._make_renderable())

    def on_key(self, event) -> None:
        key = event.key
        if key == "up":
            self.offset = max(0, self.offset - 1)
            self._update_display()
        elif key == "down":
            try:
                term_h = max(5, self.app.size.height - 6)
            except Exception:
                term_h = max(5, os.get_terminal_size().lines - 6)
            self.offset = min(max(0, len(self.lines) - term_h), self.offset + 1)
            self._update_display()
        else:
            self.app.pop_screen()


class PokedexScreen(Screen):
    """Full-screen Pokédex overlay."""

    ROUTE_ORDER = [
        "Route 1", "Mt Moon", "Nugget Bridge", "Rock Tunnel",
        "Silph Co", "Safari Zone", "Seafoam Island", "Viridian City", "Victory Road",
    ]
    FLOOR_ORDER = ["Early", "Early-Middle", "Middle", "Middle-Late", "Late"]
    FLOOR_CODES = {
        "Early":        "R1M1, R1M2",
        "Early-Middle": "R1M3, R2M1",
        "Middle":       "R2M1, R2M2",
        "Middle-Late":  "R2M2, R2M3, R3M1",
        "Late":         "R3M2, R3M3",
    }

    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.mode = "search"
        self.query = ""
        self.scroll = 0
        self.route_idx = 0
        self.route_scroll = 0
        self.data: list = []
        self.route_map: dict = {}
        self.all_routes: list = []

    def compose(self) -> ComposeResult:
        yield Static(id="dex_display")

    def on_mount(self) -> None:
        self._load_data()
        self.set_interval(0.5, self._blink)

    @work(thread=True)
    def _load_data(self) -> None:
        try:
            data = self.page.evaluate("""() => {
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
            }""")
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
                idx = self.FLOOR_ORDER.index(floor) if floor in self.FLOOR_ORDER else len(self.FLOOR_ORDER)
                return (1, idx)
            idx = self.ROUTE_ORDER.index(name) if name in self.ROUTE_ORDER else len(self.ROUTE_ORDER)
            return (0, idx)

        all_routes = sorted(route_map.keys(), key=_route_sort_key)
        self.call_from_thread(self._apply_data, data, route_map, all_routes)

    def _apply_data(self, data, route_map, all_routes) -> None:
        self.data = data
        self.route_map = route_map
        self.all_routes = all_routes
        self._update_display()

    def _blink(self) -> None:
        self.query_one("#dex_display", Static).update(self._make_panel())

    def _filtered(self) -> list:
        q = self.query.lower()
        if q:
            return [s for s in self.data if s["name"].lower().startswith(q)]
        return self.data

    @staticmethod
    def _fmt_floors(floors: list) -> str:
        if not floors:
            return "—"
        return ", ".join(floors)

    def _make_panel(self):
        try:
            term_w = self.app.size.width
            term_h = self.app.size.height
        except Exception:
            sz = os.get_terminal_size()
            term_w = sz.columns
            term_h = sz.lines
        panel_w = min(160, max(60, term_w - 10))
        term_h = max(5, term_h - 4)
        visible_rows = max(1, term_h - 6)

        body = Table.grid(padding=(0, 1))
        body.add_column(no_wrap=True, overflow="fold")

        if self.mode == "search":
            cursor = "_" if int(time.monotonic() * 2) % 2 == 0 else " "
            results = self._filtered()
            total = len(results)
            rows_per = 2
            visible_pokes = max(1, visible_rows // rows_per)
            max_scroll = max(0, total - visible_pokes)
            clamped = min(self.scroll, max_scroll)
            page_items = results[clamped:clamped + visible_pokes]

            body.add_row(Text.assemble(
                ("  type to filter · ↑↓ scroll · Tab=route mode · ESC=exit", "dim"),
                (f"   [{clamped+1}-{min(clamped+visible_pokes,total)}/{total}]", "dim"),
            ))
            body.add_row(Text.assemble(
                ("  search: ", "dim"),
                (self.query + cursor, "bold cyan"),
            ))
            body.add_row(Text(""))

            for s in page_items:
                check      = "✓" if s["caught"] else "·"
                c_style    = "bold green" if s["caught"] else "dim"
                types      = "/".join(s["types"]) if s["types"] else ""
                routes_str = ", ".join(s["routes"]) if s["routes"] else "—"
                floors_str = self._fmt_floors(s["floors"])
                indent = "     " + " " * 20 + "  " + " " * 16
                body.add_row(Text.assemble(
                    (f" {check} ", c_style),
                    (f"{s['name']:<20}", "white" if s["caught"] else "dim white"),
                    (f"  {types:<16}", "dim"),
                    ("  Normal: ", "dim"),
                    (routes_str, "dim"),
                ))
                body.add_row(Text.assemble(
                    (indent, ""),
                    ("Tower:  ", "dim"),
                    (floors_str, "dim"),
                ))

            panel_title = Text("  POKÉDEX", style="bold yellow")

        else:
            panel_title = Text("  POKÉDEX", style="bold yellow")
            if not self.all_routes:
                body.add_row(Text("No route data available.", style="dim"))
            else:
                ri = self.route_idx % len(self.all_routes)
                route_name = self.all_routes[ri]
                pokes = self.route_map.get(route_name, [])
                total = len(pokes)
                max_scroll = max(0, total - visible_rows)
                clamped_r = min(self.route_scroll, max_scroll)
                page_items = pokes[clamped_r:clamped_r + visible_rows]

                body.add_row(Text.assemble(
                    ("  ◀▶=route · ↑↓ scroll · Tab=search mode · ESC=exit", "dim"),
                    (f"   [{clamped_r+1}-{min(clamped_r+visible_rows,total)}/{total}]", "dim"),
                ))
                body.add_row(Text.assemble(
                    ("  ◀  ", "dim"),
                    (route_name, "bold cyan"),
                    ("  ▶", "dim"),
                ))
                body.add_row(Text(""))

                for s in page_items:
                    check   = "✓" if s["caught"] else "·"
                    c_style = "bold green" if s["caught"] else "dim"
                    types   = "/".join(s["types"]) if s["types"] else ""
                    body.add_row(Text.assemble(
                        (f" {check} ", c_style),
                        (f"{s['name']:<20}", "white" if s["caught"] else "dim white"),
                        (f"  {types}", "dim"),
                    ))

        return Align.center(Panel(
            body,
            title=panel_title,
            box=box.DOUBLE_EDGE,
            width=panel_w,
        ))

    def _update_display(self) -> None:
        self.query_one("#dex_display", Static).update(self._make_panel())

    def on_key(self, event) -> None:
        key = event.key
        if key == "escape":
            self.app.pop_screen()
            return

        if self.mode == "search":
            if key == "up":
                self.scroll = max(0, self.scroll - 1)
            elif key == "down":
                self.scroll += 1
            elif key == "backspace":
                self.query = self.query[:-1]
                self.scroll = 0
            elif key == "tab":
                self.mode = "route"
                self.route_scroll = 0
            elif len(key) == 1 and key.isprintable():
                self.query += key
                self.scroll = 0
        else:
            if key == "left":
                self.route_idx = (self.route_idx - 1) % max(1, len(self.all_routes))
                self.route_scroll = 0
            elif key == "right":
                self.route_idx = (self.route_idx + 1) % max(1, len(self.all_routes))
                self.route_scroll = 0
            elif key == "up":
                self.route_scroll = max(0, self.route_scroll - 1)
            elif key == "down":
                self.route_scroll += 1
            elif key == "tab":
                self.mode = "search"

        self._update_display()


# ---------------------------------------------------------------------------
# Main Textual app
# ---------------------------------------------------------------------------

class PokelikeApp(App):

    def __init__(self) -> None:
        super().__init__()
        self.page = None
        self.game_screen = ScreenType.UNKNOWN
        self.state: dict = {}
        self.selected = 0
        self.selected_starter = 0
        self.swap_source = [None]
        self.bag_mode = [False]
        self.flash_until = 0.0
        self._items: list[MenuItem] = []
        self._browser_done = threading.Event()

    def compose(self) -> ComposeResult:
        yield Static("[dim]Connecting to Chrome…[/]", id="display")

    def on_mount(self) -> None:
        # Run the browser connection in a dedicated thread so Playwright's
        # internal event loop doesn't conflict with Textual's asyncio loop.
        t = threading.Thread(target=self._browser_thread, daemon=True)
        t.start()

    def _browser_thread(self) -> None:
        try:
            with connect_to_chrome() as page:
                self.call_from_thread(self._on_connected, page)
                self._browser_done.wait()   # keep Playwright context alive
        except Exception as e:
            self.call_from_thread(self._on_connect_error, str(e))

    def _on_connected(self, page) -> None:
        self.page = page
        self._do_refresh()
        self.set_interval(AUTO_REFRESH_INTERVAL, self._do_refresh)

    def _on_connect_error(self, msg: str) -> None:
        self.query_one("#display", Static).update(f"[red][Error][/] {msg}")

    def on_unmount(self) -> None:
        self._browser_done.set()

    @work(thread=True)
    def _do_refresh(self) -> None:
        if self.page is None:
            return
        try:
            prev = self.game_screen
            new_screen = detect(self.page)
            p = PARSER_MAP.get(new_screen)
            new_state = p.parse(self.page) if p else _unknown_state(self.page, new_screen)
            self.call_from_thread(self._apply_state, prev, new_screen, new_state)
        except Exception:
            pass

    def _apply_state(self, prev: ScreenType, new_screen: ScreenType, new_state: dict) -> None:
        screen_changed = (new_screen != prev)
        self.game_screen = new_screen
        self.state = new_state
        self.flash_until = time.monotonic() + 1.2
        if screen_changed:
            self.selected = 0
            self._handle_screen_change(prev, new_screen)
        self._rebuild()

    def _handle_screen_change(self, prev: ScreenType, new: ScreenType) -> None:
        if new == ScreenType.STARTER_SELECT:
            click_starter(self.page, self.selected_starter)
            self.call_later(self._do_refresh)
        elif new == ScreenType.BADGE_OBTAINED:
            self.page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('.btn-primary'))
                    .find(b => b.textContent.includes('Next Map'))
                if (btn) btn.click()
            }""")
            self.call_later(self._do_refresh)
        elif new == ScreenType.GAME_OVER:
            self.page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('.btn-primary'))
                    .find(b => b.textContent.trim() === 'Try Again')
                if (btn) btn.click()
            }""")
            self.call_later(self._do_refresh)
        elif new == ScreenType.EVOLUTION:
            _click_center(self.page)
            self.call_later(self._do_refresh)

    def _rebuild(self) -> None:
        self._items = self._build_current_items()
        if self._items:
            self.selected = max(0, min(self.selected, len(self._items) - 1))
        flash = time.monotonic() < self.flash_until
        renderable = render(
            self.game_screen, self.state, self._items, self.selected,
            flash, self.selected_starter, self.swap_source, self.bag_mode
        )
        self.query_one("#display", Static).update(renderable)

    def _build_current_items(self) -> list[MenuItem]:
        def noop_refresh():
            self._do_refresh()
            return ""

        if self.game_screen == ScreenType.MAP:
            return build_map_items(
                self.state, self.page, noop_refresh, self.selected_starter,
                self.swap_source, self.bag_mode
            )
        else:
            self.swap_source[0] = None
            self.bag_mode[0] = False
            builder = MENU_BUILDERS.get(self.game_screen)
            if builder:
                return builder(self.state, self.page, noop_refresh, self.selected_starter)
            return _fallback_items(noop_refresh, self.page)

    def on_key(self, event) -> None:
        key = event.key
        items = self._items
        if not items:
            return

        if key == "up":
            self.selected = (self.selected - 1) % len(items)
            self._rebuild()
        elif key == "down":
            self.selected = (self.selected + 1) % len(items)
            self._rebuild()
        elif key == "left":
            gen = self.state.get("selected_gen") or "I"
            n = len(get_starters(gen))
            self.selected_starter = (self.selected_starter - 1) % n
            self._rebuild()
        elif key == "right":
            gen = self.state.get("selected_gen") or "I"
            n = len(get_starters(gen))
            self.selected_starter = (self.selected_starter + 1) % n
            self._rebuild()
        elif key == "enter":
            self._execute_item(self.selected)
        elif key in ("escape", "q"):
            self.exit()
        else:
            # single-char shortcut matching
            char = key.lower() if len(key) == 1 else None
            if char:
                for i, item in enumerate(items):
                    if item.shortcut.lower() == char and item.enabled:
                        self._execute_item(i)
                        break

    @work(thread=True)
    def _execute_item(self, index: int) -> None:
        result = _execute(self._items, index)
        if result == "QUIT":
            self.call_from_thread(self.exit)
        elif result == "SHOW_POKEDEX":
            self.call_from_thread(self.push_screen, PokedexScreen(self.page))
        elif result == "SHOW_JSON":
            self.call_from_thread(self.push_screen, JsonScreen(json.dumps(self.state, indent=2)))
        else:
            self.call_from_thread(self._do_refresh_sync)

    def _do_refresh_sync(self) -> None:
        self._do_refresh()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    PokelikeApp().run()


if __name__ == "__main__":
    main()
