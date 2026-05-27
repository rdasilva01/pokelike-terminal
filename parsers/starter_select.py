from playwright.sync_api import Page
from parsers.base import AbstractParser


class StarterSelectParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        cards = page.locator(".poke-card").all()
        starters = []
        for card in cards:
            name  = self._text(card, ".poke-name")
            level = self._text(card, ".poke-level")
            unique_types = [t.inner_text().strip() for t in card.locator(".poke-types .type-badge").all()]
            move  = self._text(card, ".move-name")
            starters.append({
                "name": name,
                "level": level,
                "types": unique_types,
                "move": move,
            })

        return {
            "screen": "starter_select",
            "starters": starters,
        }

    def _text(self, locator, selector: str) -> str:
        try:
            return locator.locator(selector).first.inner_text().strip()
        except Exception:
            return ""
