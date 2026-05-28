import re
from playwright.sync_api import Page
from parsers.base import AbstractParser


class BattleParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        header = self._txt(page.locator(".battle-header").first)

        sides = page.locator(".battle-side").all()
        your_team = self._parse_side(sides[0]) if len(sides) > 0 else []
        enemy     = self._parse_side(sides[1]) if len(sides) > 1 else []

        can_continue = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.btn-primary'))
                .some(b => b.textContent.trim().startsWith('Continue') && b.getBoundingClientRect().width > 0)
        }""")

        return {
            "screen":       "battle",
            "header":       header,
            "your_team":    your_team,
            "enemy":        enemy,
            "can_continue": can_continue,
        }

    def _parse_side(self, side) -> list:
        result = []
        for poke in side.locator(".battle-pokemon").all():
            name_lv = self._txt(poke.locator(".battle-poke-name").first)
            name, level = self._split_name_level(name_lv)
            hp_text = self._txt(poke.locator(".hp-text").first)
            hp_cur, hp_max = self._parse_hp(hp_text)
            classes = poke.get_attribute("class") or ""
            result.append({
                "name":      name,
                "level":     level,
                "hp_current": hp_cur,
                "hp_max":    hp_max,
                "is_active":  "active-pokemon" in classes,
                "is_fainted": "fainted" in classes,
            })
        return result

    def _split_name_level(self, text: str):
        m = re.match(r"(.+?)\s+Lv(\d+)", text)
        if m:
            return m.group(1).strip(), int(m.group(2))
        return text, None

    def _parse_hp(self, text: str):
        m = re.search(r"(\d+)/(\d+)", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    def _txt(self, locator) -> str:
        try:
            return locator.inner_text(timeout=2000).strip()
        except Exception:
            return ""
