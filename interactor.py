import json
import msvcrt
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable

from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from browser import connect_to_chrome
from screen_detector import detect, ScreenType
from parsers.battle import BattleParser
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
# Key reading (Windows, non-blocking)
# ---------------------------------------------------------------------------

def read_key() -> str:
    ch = msvcrt.getwch()
    if ch in ('\x00', '\xe0'):
        ch2 = msvcrt.getwch()
        return {'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT'}.get(ch2, '')
    if ch == '\r':
        return 'ENTER'
    if ch == '\x1b':
        return 'ESC'
    return ch.lower()


def poll_key(timeout: float = 0.1) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            return read_key()
        time.sleep(0.02)
    return None


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
    term_w = console.size.width
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

def click_starter(page, starter_idx: int) -> str:
    """Click the poke-card at starter_idx (0=grass, 1=fire, 2=water)."""
    page.locator(".poke-card").nth(starter_idx).click()
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

    items += [
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


def show_raw_json(state: dict) -> str:
    lines = json.dumps(state, indent=2).splitlines()
    offset = 0

    def make_panel():
        term_h = max(5, console.size.height - 6)
        visible = lines[offset:offset + term_h]
        syntax = Syntax("\n".join(visible), "json", theme="monokai", line_numbers=True, start_line=offset + 1)
        pct = f"{offset + 1}-{min(offset + term_h, len(lines))}/{len(lines)}"
        return Panel(
            syntax,
            title=f"[bold yellow]RAW JSON[/] [dim](↑↓ scroll · any other key to go back)[/]",
            subtitle=f"[dim]{pct}[/]",
            box=box.DOUBLE_EDGE,
        )

    with Live(make_panel(), console=console, screen=True, refresh_per_second=4) as live:
        while True:
            key = read_key()
            if key == 'UP':
                offset = max(0, offset - 1)
            elif key == 'DOWN':
                term_h = max(5, console.size.height - 6)
                offset = min(max(0, len(lines) - term_h), offset + 1)
            else:
                break
            live.update(make_panel())
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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

    items += [
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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
                .find(b => b.textContent.includes('Skip'));
            if (btn) btn.click();
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
        MenuItem("Raw JSON", "J", lambda: show_raw_json(state)),
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
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
        MenuItem("Raw JSON",    "J", lambda: show_raw_json(state)),
        MenuItem("Reload Page", "P", reload_page),
        MenuItem("Refresh",     "R", refresh_fn),
        MenuItem("Quit",        "Q", lambda: "QUIT"),
    ]
    return items


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
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    console.print("[dim]Connecting to Chrome...[/]")
    try:
        with connect_to_chrome() as page:
            console.print(f"[green]Connected[/] {page.url}\n")
            run_tui(page)
    except RuntimeError as e:
        console.print(f"[red][Error][/] {e}")
        sys.exit(1)


def run_tui(page):
    screen = ScreenType.UNKNOWN
    state: dict = {}
    selected = 0
    selected_starter = 0
    swap_source = [None]   # [None] | ["src"] | [int index]
    bag_mode   = [False]   # [False] | [True]
    refresh_flash_until = 0.0
    last_auto_refresh = 0.0  # triggers immediate refresh on first iteration

    def handle_screen_change(prev: ScreenType, new: ScreenType) -> str:
        """Fire auto-actions on screen transitions. Returns a status message."""
        if new == ScreenType.STARTER_SELECT:
            return click_starter(page, selected_starter)
        if new == ScreenType.BADGE_OBTAINED:
            page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('.btn-primary'))
                    .find(b => b.textContent.includes('Next Map'))
                if (btn) btn.click()
            }""")
            return "Badge obtained — clicked Next Map"
        if new == ScreenType.GAME_OVER:
            page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('.btn-primary'))
                    .find(b => b.textContent.trim() === 'Try Again')
                if (btn) btn.click()
            }""")
            return "Game over — clicked Try Again"
        return ""

    def apply_change(prev_screen: ScreenType) -> None:
        """Detect new screen, fire auto-actions if changed, re-detect after auto-action."""
        nonlocal screen, state, selected, last_auto_refresh, refresh_flash_until
        screen = detect(page)
        p = PARSER_MAP.get(screen)
        state = p.parse(page) if p else _unknown_state(page, screen)
        last_auto_refresh = time.monotonic()
        refresh_flash_until = time.monotonic() + 1.2
        if screen != prev_screen:
            selected = 0
            auto_msg = handle_screen_change(prev_screen, screen)
            if auto_msg:
                time.sleep(0.8)
                screen = detect(page)
                p = PARSER_MAP.get(screen)
                state = p.parse(page) if p else _unknown_state(page, screen)

    def do_refresh():
        prev = screen
        apply_change(prev)

    with Live(console=console, screen=True, refresh_per_second=10) as live:
        while True:
            if screen == ScreenType.MAP:
                items = build_map_items(state, page, do_refresh, selected_starter, swap_source, bag_mode)
            else:
                swap_source[0] = None   # reset modes when leaving MAP
                bag_mode[0]    = False
                builder = MENU_BUILDERS.get(screen)
                items = (
                    builder(state, page, do_refresh, selected_starter)
                    if builder else
                    _fallback_items(do_refresh, page)
                )
            selected = max(0, min(selected, len(items) - 1))

            flash = time.monotonic() < refresh_flash_until
            live.update(render(screen, state, items, selected, flash, selected_starter, swap_source, bag_mode))

            key = poll_key(timeout=0.5)

            if key is None:
                if time.monotonic() - last_auto_refresh >= AUTO_REFRESH_INTERVAL:
                    do_refresh()
                continue

            if key == 'UP':
                selected = (selected - 1) % len(items)
            elif key == 'DOWN':
                selected = (selected + 1) % len(items)
            elif key == 'LEFT':
                gen = state.get("selected_gen") or "I"
                n = len(get_starters(gen))
                selected_starter = (selected_starter - 1) % n
            elif key == 'RIGHT':
                gen = state.get("selected_gen") or "I"
                n = len(get_starters(gen))
                selected_starter = (selected_starter + 1) % n
            elif key == 'ENTER':
                result = _execute(items, selected)
                if result == "QUIT":
                    break
                apply_change(screen)
            elif key in ('ESC', 'q'):
                break
            else:
                for i, item in enumerate(items):
                    if item.shortcut.lower() == key and item.enabled:
                        result = _execute(items, i)
                        if result == "QUIT":
                            live.stop()
                            return
                        apply_change(screen)
                        break


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


if __name__ == "__main__":
    main()
