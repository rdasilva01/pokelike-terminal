import re
from playwright.sync_api import Page
from parsers.base import AbstractParser


class CatchPokemonParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        choices = []
        for wrap in page.locator(".screen.active .poke-choice-wrap").all():
            choices.append(self._parse_card(wrap))
        return {
            "screen": "catch_pokemon",
            "choices": choices,
        }

    def _parse_card(self, wrap) -> dict:
        name    = self._txt(wrap, ".poke-name")
        level   = self._parse_level(self._txt(wrap, ".poke-level"))
        types   = [t.inner_text().strip() for t in wrap.locator(".poke-types .type-badge").all()]
        is_shiny = wrap.locator(".shiny-badge").count() > 0
        is_caught = wrap.locator(".dex-caught-badge").count() > 0

        hp_text = self._txt(wrap, ".hp-text")
        hp_current, hp_max = self._parse_hp(hp_text)

        stats = {}
        for row in wrap.locator(".stat-row").all():
            lbl = self._txt(row, ".stat-lbl")
            val = self._txt(row, ".stat-val")
            if lbl and val.isdigit():
                stats[lbl] = int(val)

        move_name  = self._txt(wrap, ".move-name")
        move_types = [t.inner_text().strip() for t in wrap.locator(".move-header .type-badge").all()]
        move_type  = move_types[0] if move_types else ""
        power_text = self._txt(wrap, ".move-power-badge")
        move_power = int(re.search(r"\d+", power_text).group()) if re.search(r"\d+", power_text) else None
        move_cat_el = wrap.locator("[class*='move-cat-']")
        move_cat = move_cat_el.first.inner_text().strip() if move_cat_el.count() > 0 else ""

        return {
            "name":       name,
            "level":      level,
            "types":      types,
            "is_shiny":   is_shiny,
            "is_caught":  is_caught,
            "hp_current": hp_current,
            "hp_max":     hp_max,
            "stats":      stats,
            "move": {
                "name":     move_name,
                "type":     move_type,
                "category": move_cat,
                "power":    move_power,
            },
        }

    def _parse_level(self, text: str) -> int | None:
        m = re.search(r"\d+", text)
        return int(m.group()) if m else None

    def _parse_hp(self, text: str):
        m = re.search(r"(\d+)/(\d+)", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    def _txt(self, locator, selector: str) -> str:
        try:
            return locator.locator(selector).first.inner_text(timeout=2000).strip()
        except Exception:
            return ""
