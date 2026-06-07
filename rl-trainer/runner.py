"""
runner.py — Low-level browser lifecycle and action executor for the RL trainer.

Each GameRunner owns one headless Playwright browser instance with an isolated
profile directory (so multiple envs don't share localStorage).
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, Playwright

# rl-trainer/ must come before repo root so its config.py takes priority
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from screen_detector import detect, ScreenType
from parsers.map_screen import MapParser
from parsers.catch_pokemon import CatchPokemonParser
from parsers.battle import BattleParser
from parsers.item_select import ItemSelectParser
from parsers.starter_select import StarterSelectParser
from parsers.item_equip import ItemEquipParser

from config import (
    LOCAL_URL, ACTION_WAIT_TIMEOUT, SCREEN_SETTLE_DELAY, POKEDEX_JSON
)

# ---------------------------------------------------------------------------
# Type / vocab helpers
# ---------------------------------------------------------------------------

TYPES = [
    "Normal", "Fire", "Water", "Grass", "Electric", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
]
TYPE_IDX = {t.lower(): i + 1 for i, t in enumerate(TYPES)}  # 1-indexed; 0 = none

# Screens the agent should never see as decision points — handled automatically
_AUTO_ADVANCE = {
    ScreenType.BADGE_OBTAINED,
    ScreenType.EVOLUTION,
    ScreenType.POKEMON_RECEIVED,
    ScreenType.STAGE_SELECT,   # handled in reset()
}

# ---------------------------------------------------------------------------
# Pokedex BST lookup (loaded once)
# ---------------------------------------------------------------------------

_POKEDEX: dict[str, dict] = {}       # keyed by lowercase name
_POKEDEX_BY_ID: dict[int, dict] = {}  # keyed by numeric species ID

def _load_pokedex() -> None:
    global _POKEDEX, _POKEDEX_BY_ID
    if _POKEDEX:
        return
    try:
        with open(POKEDEX_JSON, encoding="utf-8") as f:
            raw = json.load(f)
        for sid_str, v in raw.items():
            name = v.get("name", "").lower()
            stats = v.get("baseStats", {})
            bst = sum(stats.values()) if stats else 400
            entry = {"bst": bst, "types": v.get("types", []), "name": v.get("name", "")}
            _POKEDEX[name] = entry
            try:
                _POKEDEX_BY_ID[int(sid_str)] = entry
            except ValueError:
                pass
    except Exception:
        pass

def get_bst(name: str) -> int:
    _load_pokedex()
    return _POKEDEX.get(name.lower(), {}).get("bst", 400)


# ---------------------------------------------------------------------------
# Unlock payload (injected into localStorage on each reset)
# ---------------------------------------------------------------------------

def _build_unlock_payload() -> str:
    # One HoF entry per species (1-649) so all appear in the Battle Tower PC
    hof, run = [], 1
    starter_runs = []
    evo_line_roots = list(range(1, 650))
    for sid in range(1, 650):
        stage = ((sid - 1) % 5) + 1  # spread across stages 1-5
        hof.append({
            "savedAt": run, "runNumber": run,
            "hardMode": False, "endless": True, "gen2Mode": False,
            "stageNumber": stage, "starterSpeciesId": sid,
            "date": "1/1/2024", "team": [{"speciesId": sid}],
        })
        starter_runs.append(f"{stage}:{sid}")
        run += 1
    # One normal-mode win so non-endless content is also unlocked
    hof.append({
        "savedAt": run, "runNumber": run,
        "hardMode": False, "endless": False, "gen2Mode": False,
        "stageNumber": None, "starterSpeciesId": 1,
        "date": "1/1/2024", "team": [{"speciesId": 1}],
    })
    hof_index = {
        "evoLineRoots": evo_line_roots,
        "starterRuns":  starter_runs,
        "maxEndlessStage": 5,
    }
    dex = {str(i): 1 for i in range(1, 650)}
    return json.dumps({"hof": hof, "hofIndex": hof_index, "dex": dex})


# ---------------------------------------------------------------------------
# GameRunner
# ---------------------------------------------------------------------------

class GameRunner:
    """Manages one headless Playwright browser + all game interactions."""

    def __init__(self, env_idx: int = 0):
        self.env_idx = env_idx
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self._map_parser     = MapParser()
        self._catch_parser   = CatchPokemonParser()
        self._battle_parser  = BattleParser()
        self._item_parser    = ItemSelectParser()
        self._starter_parser = StarterSelectParser()
        self._equip_parser   = ItemEquipParser()
        _load_pokedex()

    # ------------------------------------------------------------------ lifecycle

    def start(self, headless: bool = True) -> None:
        self._pw = sync_playwright().start()
        import tempfile
        profile = Path(tempfile.gettempdir()) / f"pokelike_rl_{self.env_idx}"
        profile.mkdir(parents=True, exist_ok=True)
        self._browser = self._pw.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
        )
        self.page = self._browser.new_page()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ reset

    def reset(self, stage: int = 1) -> dict:
        """Navigate to a fresh endless run; return state at starter screen."""
        self.page.goto(LOCAL_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(0.5)

        payload = _build_unlock_payload()
        self.page.evaluate(f"""(p) => {{
            const d = JSON.parse(p);
            localStorage.setItem('poke_hall_of_fame', JSON.stringify(d.hof));
            localStorage.setItem('poke_hof_index',    JSON.stringify(d.hofIndex));
            localStorage.setItem('poke_dex',          JSON.stringify(d.dex));
            localStorage.setItem('poke_elite_wins',   '20');
            localStorage.setItem('poke_tutorial_seen','true');
            localStorage.setItem('poke_trainer',      'boy');
            const settings = JSON.parse(localStorage.getItem('poke_settings') || '{{}}');
            settings.autoSkipBattles    = true;
            settings.autoSkipAllBattles = true;
            settings.autoSkipEvolve     = true;
            localStorage.setItem('poke_settings', JSON.stringify(settings));
        }}""", payload)

        self.page.reload(wait_until="domcontentloaded", timeout=15000)
        time.sleep(1.2)

        self.page.evaluate("""() => {
            const btn = document.getElementById('btn-endless-run');
            if (btn && !btn.disabled) btn.click();
        }""")
        time.sleep(0.6)

        self.page.evaluate(f"""() => {{
            // Try multiple selectors — local copy may differ from live site
            const selectors = [
                '#stage-select-list button:not([disabled])',
                '.stage-select button:not([disabled])',
                '[class*="stage"] button:not([disabled])',
            ];
            let btns = [];
            for (const sel of selectors) {{
                btns = Array.from(document.querySelectorAll(sel))
                    .filter(b => b.getBoundingClientRect().width > 0);
                if (btns.length) break;
            }}
            // Fallback: any visible button containing 'Gen' (stage labels)
            if (!btns.length) {{
                btns = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.getBoundingClientRect().width > 0 && b.textContent.includes('Gen'));
            }}
            const target = btns[{stage - 1}];
            if (target) target.click();
        }}""")
        time.sleep(0.8)

        # Auto-click trainer select if it appears (first run only)
        trainer = self.page.evaluate(
            "document.getElementById('trainer-boy') ? 'visible' : 'none'"
        )
        if trainer == "visible":
            self.page.evaluate("document.getElementById('trainer-boy')?.click()")
            time.sleep(0.8)

        state = self.parse_state()
        self._enable_auto_skip()
        return state

    def _enable_auto_skip(self) -> None:
        """Open settings and enable all auto-skip options via UI so in-memory state updates."""
        self.page.evaluate("""() => {
            const btn = document.querySelector('button[title="Settings"]');
            if (btn) btn.click();
        }""")
        time.sleep(0.3)
        self.page.evaluate("""() => {
            document.querySelectorAll('.settings-checkbox').forEach(cb => {
                const key = cb.dataset.key;
                if (['autoSkipBattles','autoSkipAllBattles','autoSkipEvolve'].includes(key) && !cb.checked) {
                    cb.click();
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                }
            });
        }""")
        time.sleep(0.2)
        # Close the modal
        self.page.evaluate("""() => {
            const close = document.querySelector('.ach-modal-close');
            if (close) close.click();
            const modal = document.getElementById('settings-modal');
            if (modal) modal.remove();
        }""")

    # ------------------------------------------------------------------ state parsing

    def parse_state(self) -> dict:
        screen = detect(self.page)
        state = {"screen": screen}
        try:
            if screen == ScreenType.MAP:
                state.update(self._map_parser.parse(self.page))
            elif screen == ScreenType.CATCH_POKEMON:
                state.update(self._catch_parser.parse(self.page))
            elif screen == ScreenType.BATTLE:
                state.update(self._battle_parser.parse(self.page))
            elif screen == ScreenType.ITEM_SELECT:
                state.update(self._item_parser.parse(self.page))
            elif screen == ScreenType.STARTER_SELECT:
                data = self._starter_parser.parse(self.page)
                for s in data.get("starters", []):
                    s["bst"] = get_bst(s.get("name", ""))
                state.update(data)
            elif screen == ScreenType.ITEM_EQUIP:
                state.update(self._equip_parser.parse(self.page))
            elif screen == ScreenType.TEAM_SELECT:
                state.update(self._parse_team_select())
            elif screen == ScreenType.TEAM_FULL:
                # Extract team + incoming pokemon from DOM for agent decision
                state.update(self._parse_team_full())
        except Exception:
            pass
        return state

    def _parse_team_full(self) -> dict:
        return self.page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('.screen.active .poke-card'))
            return { team_full_cards: cards.map(c => ({
                name:     c.querySelector('.poke-name')?.innerText?.trim() || '',
                level:    parseInt(c.querySelector('.poke-level')?.innerText?.replace(/\\D/g,'') || '0'),
                is_shiny: !!(c.querySelector('.shiny-badge') ||
                             c.classList.contains('shiny') ||
                             c.querySelector('[class*="shiny"]')),
            }))}
        }""")

    def _parse_team_select(self) -> dict:
        """Scroll through the PC grid to collect all available starters."""
        seen: dict[str, dict] = {}
        _load_pokedex()

        for _ in range(60):  # max iterations to avoid infinite loop
            batch = self.page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.pc-slot')).map(slot => {
                    const img = slot.querySelector('img');
                    return {
                        name: img?.alt?.trim() || '',
                        is_shiny: slot.classList.contains('shiny') ||
                                  !!slot.querySelector('.shiny-badge, [class*="shiny"]'),
                    };
                }).filter(s => s.name);
            }""")

            new_found = 0
            for s in batch:
                if s["name"] not in seen:
                    entry = _POKEDEX.get(s["name"].lower())
                    if entry:
                        seen[s["name"]] = {
                            "name":     entry["name"],
                            "types":    entry.get("types", []),
                            "bst":      entry.get("bst", 400),
                            "is_shiny": s["is_shiny"],
                        }
                        new_found += 1

            # Scroll the PC box body down by one page
            at_bottom = self.page.evaluate("""() => {
                const el = document.querySelector('.pc-box-body') ||
                           document.querySelector('.pc-box-grid');
                if (!el) return true;
                el.scrollTop += el.clientHeight;
                return el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
            }""")

            if at_bottom and new_found == 0:
                break

        return {"screen": ScreenType.TEAM_SELECT, "starters": list(seen.values())}

    # ------------------------------------------------------------------ auto-advance helpers

    def auto_advance(self) -> ScreenType:
        """Click through non-decision screens until reaching a decision point.
        Returns the final ScreenType."""
        deadline = time.time() + ACTION_WAIT_TIMEOUT
        while time.time() < deadline:
            screen = detect(self.page)
            if screen not in _AUTO_ADVANCE:
                return screen
            if screen == ScreenType.BADGE_OBTAINED:
                self.page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('.btn-primary'))
                        .find(b => b.textContent.includes('Next Map') && b.getBoundingClientRect().width > 0);
                    if (btn) btn.click();
                }""")
            elif screen in (ScreenType.EVOLUTION, ScreenType.POKEMON_RECEIVED):
                self.page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('button'))
                        .find(b => b.getBoundingClientRect().width > 0 &&
                             (b.textContent.includes('Continue') || b.textContent.includes('OK') ||
                              b.textContent.includes('Next') || b.textContent.includes('Take')));
                    if (btn) btn.click();
                }""")
            time.sleep(SCREEN_SETTLE_DELAY)
        return detect(self.page)

    def handle_battle(self) -> None:
        """Click Continue until battle screen is gone."""
        deadline = time.time() + ACTION_WAIT_TIMEOUT * 3
        while time.time() < deadline:
            screen = detect(self.page)
            if screen != ScreenType.BATTLE:
                break
            self.page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.getBoundingClientRect().width > 0 &&
                         (b.textContent.includes('Continue') || b.textContent.includes('Next')));
                if (btn) btn.click();
            }""")
            time.sleep(SCREEN_SETTLE_DELAY)

    def handle_team_full_auto(self) -> None:
        """Auto-release the lowest-level non-shiny team member to make room.

        If every current team member is shiny, skip the catch (click the skip/flee
        button) rather than releasing a shiny.
        """
        self.page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('.screen.active .poke-card'));
            if (!cards.length) return;
            // Last card is the incoming Pokémon; candidates are the existing team
            const team = cards.slice(0, -1);

            const isShiny = c =>
                !!(c.querySelector('.shiny-badge') ||
                   c.classList.contains('shiny') ||
                   c.querySelector('[class*="shiny"]'));

            // Pick weakest non-shiny member
            let minLv = Infinity, minCard = null;
            for (const c of team) {
                if (isShiny(c)) continue;
                const lv = parseInt(c.querySelector('.poke-level')?.innerText?.replace(/\\D/g,'') || '999');
                if (lv < minLv) { minLv = lv; minCard = c; }
            }

            if (minCard) {
                const releaseBtn = minCard.querySelector('.release-btn, button');
                if (releaseBtn) releaseBtn.click();
            } else {
                // All team members are shiny — skip the catch instead
                const skipBtn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.getBoundingClientRect().width > 0 &&
                          (b.textContent.toLowerCase().includes('skip') ||
                           b.textContent.toLowerCase().includes('flee') ||
                           b.textContent.toLowerCase().includes('cancel')));
                if (skipBtn) skipBtn.click();
            }
        }""")
        time.sleep(SCREEN_SETTLE_DELAY)

    # ------------------------------------------------------------------ wait helper

    def wait_for_decision_screen(self, timeout: float = ACTION_WAIT_TIMEOUT,
                                  leave_screen: ScreenType | None = None) -> dict:
        """Wait until a decision-requiring screen appears, then return parsed state.

        If leave_screen is given, also waits until the current screen is no longer
        that screen type (useful to avoid returning immediately after a click before
        the game has transitioned away).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            screen = self.auto_advance()
            if leave_screen is not None and screen == leave_screen:
                time.sleep(SCREEN_SETTLE_DELAY)
                continue
            if screen == ScreenType.BATTLE:
                self.handle_battle()
                continue
            if screen == ScreenType.TEAM_FULL:
                self.handle_team_full_auto()
                continue
            if screen not in (ScreenType.UNKNOWN,):
                return self.parse_state()
            # UNKNOWN screen — try to click through blocking overlays
            # (move upgrade prompt, shiny event Take button, misc popups)
            clicked = self.page.evaluate("""() => {
                const KEYWORDS = ['Take','Keep','Replace','Continue','OK','Next','Skip','Close','Confirm'];
                const btn = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.getBoundingClientRect().width > 0)
                    .find(b => KEYWORDS.some(kw => b.textContent.trim().includes(kw)));
                if (btn) { btn.click(); return btn.textContent.trim(); }
                return null;
            }""")
            time.sleep(SCREEN_SETTLE_DELAY)
        return self.parse_state()

    # ------------------------------------------------------------------ actions

    def act_move_tutor(self, index: int) -> dict:
        """Teach the move to the Pokémon at the given row index in the tutor overlay."""
        self.page.evaluate(f"""(idx) => {{
            const btns = document.querySelectorAll('.item-equip-overlay .equip-btn[data-tutor]');
            if (btns[idx]) btns[idx].click();
        }}""", index)
        return self.wait_for_decision_screen()

    def act_skip_tutor(self) -> dict:
        """Skip / keep-in-bag on the item equip / move tutor overlay."""
        self.page.evaluate("""() => {
            const btn = document.getElementById('btn-skip-tutor') ||
                Array.from(document.querySelectorAll('.item-equip-overlay button'))
                    .find(b => b.textContent.includes('Skip') || b.textContent.includes('Keep in Bag'));
            if (btn) btn.click();
        }""")
        return self.wait_for_decision_screen()

    def act_node(self, direction: int) -> dict:
        """Click left (0) or right (1) accessible node in the current map layer."""
        self.page.evaluate(f"""(dir) => {{
            const svg = document.querySelector('.screen.active svg');
            if (!svg) return;
            // Accessible nodes use cursor:pointer style
            const nodes = Array.from(svg.querySelectorAll('g')).filter(el =>
                (el.getAttribute('style') || '').includes('cursor: pointer'));
            const target = nodes[dir] ?? nodes[0];
            if (target) target.dispatchEvent(
                new MouseEvent('click', {{bubbles: true, cancelable: true}}));
        }}""", direction)
        return self.wait_for_decision_screen()

    def act_catch(self, slot: int) -> dict:
        """Catch the Pokémon at catch-screen slot index."""
        self.page.evaluate(f"""(slot) => {{
            const wraps = document.querySelectorAll('.screen.active .poke-choice-wrap');
            const card = wraps[slot]?.querySelector('.poke-card');
            if (card) card.click();
        }}""", slot)
        time.sleep(SCREEN_SETTLE_DELAY * 2)
        return self.wait_for_decision_screen(leave_screen=ScreenType.CATCH_POKEMON)

    def act_reroll(self, slot: int) -> dict:
        """Reroll catch slot; stays on same screen."""
        self.page.evaluate(f"""(slot) => {{
            const wraps = document.querySelectorAll('.screen.active .poke-choice-wrap');
            const btn = wraps[slot]?.querySelector('.reroll-btn');
            if (btn) btn.click();
        }}""", slot)
        time.sleep(SCREEN_SETTLE_DELAY)
        return self.parse_state()

    def act_skip_catch(self) -> dict:
        """Skip the catch node."""
        self.page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.getBoundingClientRect().width > 0 &&
                     (b.textContent.toLowerCase().includes('skip') ||
                      b.textContent.toLowerCase().includes('flee')));
            if (btn) btn.click();
        }""")
        return self.wait_for_decision_screen()

    def act_item(self, slot: int) -> dict:
        """Pick item at slot index."""
        self.page.evaluate(f"""(slot) => {{
            const cards = document.querySelectorAll('.screen.active .item-card');
            if (cards[slot]) cards[slot].click();
        }}""", slot)
        return self.wait_for_decision_screen()

    def act_skip_item(self) -> dict:
        """Skip item selection."""
        self.page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.getBoundingClientRect().width > 0 &&
                     b.textContent.toLowerCase().includes('skip'));
            if (btn) btn.click();
        }""")
        return self.wait_for_decision_screen()

    def act_starter(self, slot: int, starters_sorted: list) -> dict:
        """Pick starter at sorted-index slot (top-20 by BST order)."""
        if slot >= len(starters_sorted):
            slot = 0
        name = starters_sorted[slot].get("name", "")
        # Works for both normal starter cards (.poke-card) and PC grid (.pc-slot)
        self.page.evaluate("""(name) => {
            // PC box grid (Battle Tower team select)
            for (const slot of document.querySelectorAll('.pc-slot')) {
                const img = slot.querySelector('img');
                if (img?.alt?.trim().toLowerCase() === name.toLowerCase()) {
                    slot.click();
                    return;
                }
            }
            // Normal starter cards
            for (const card of document.querySelectorAll('.poke-card')) {
                const n = card.querySelector('.poke-name')?.innerText?.trim() || '';
                if (n.toLowerCase() === name.toLowerCase()) {
                    card.click();
                    return;
                }
            }
        }""", name)
        time.sleep(0.5)
        # Confirm if a confirm button appears
        self.page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.getBoundingClientRect().width > 0 &&
                     (b.textContent.includes('Choose') || b.textContent.includes('Confirm') ||
                      b.textContent.includes('Start')));
            if (btn) btn.click();
        }""")
        return self.wait_for_decision_screen()

    def act_swap(self, i: int, j: int) -> dict:
        """Swap team slot i and j (unordered)."""
        try:
            slot_i = self.page.locator(".map-panel-left .team-slot").nth(i)
            slot_j = self.page.locator(".map-panel-left .team-slot").nth(j)
            slot_i.drag_to(slot_j)
        except Exception:
            pass
        time.sleep(SCREEN_SETTLE_DELAY)
        return self.parse_state()

    def act_equip(self, bag_idx: int) -> dict:
        """Equip bag item at bag_idx to the lead Pokémon."""
        self.page.evaluate(f"""(idx) => {{
            const badges = Array.from(document.querySelectorAll('#item-bar .item-badge'))
                .filter(b => b.getBoundingClientRect().width > 0);
            if (badges[idx]) badges[idx].click();
        }}""", bag_idx)
        time.sleep(0.3)
        # Click first team slot to confirm equip to lead
        self.page.evaluate("""() => {
            const slot = document.querySelector('.map-panel-left .team-slot');
            if (slot) slot.click();
        }""")
        time.sleep(SCREEN_SETTLE_DELAY)
        return self.parse_state()

    # ------------------------------------------------------------------ terminal checks

    def is_game_over(self) -> bool:
        return detect(self.page) == ScreenType.GAME_OVER

    def is_stage_complete(self) -> bool:
        """Detect stage/champion completion screen."""
        screen = detect(self.page)
        if screen == ScreenType.CHAMPION:
            return True
        # Endless stage complete: game returns to stage select or shows a custom overlay
        if screen == ScreenType.STAGE_SELECT:
            return True
        # Fallback: check for a visible stage-complete element
        return self.page.evaluate("""() =>
            !!(document.querySelector('.stage-complete') ||
               document.querySelector('.hof-screen'))
        """)
