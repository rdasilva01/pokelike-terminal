from playwright.sync_api import Page
from parsers.base import AbstractParser


class ItemSelectParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        choices = []
        for card in page.locator(".screen.active .item-card").all():
            name = self._txt(card, ".item-name")
            desc = self._txt(card, ".item-desc")
            choices.append({"name": name, "description": desc})
        return {
            "screen": "item_select",
            "choices": choices,
        }

    def _txt(self, locator, selector: str) -> str:
        try:
            return locator.locator(selector).first.inner_text(timeout=2000).strip()
        except Exception:
            return ""
