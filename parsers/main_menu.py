import re
from playwright.sync_api import Page
from parsers.base import AbstractParser
from models.screens import MainMenuState


class MainMenuParser(AbstractParser):
    def parse(self, page: Page) -> MainMenuState:
        return {
            "screen": "main_menu",
            "selected_gen": self._selected_gen(page),
            "available_gens": self._available_gens(page),
            "logged_in_user": self._logged_in_user(page),
        }

    def _available_gens(self, page: Page) -> list[str]:
        gen_buttons = page.locator(".gen-btn").all()
        return [btn.inner_text().strip() for btn in gen_buttons if btn.is_visible()]

    def _selected_gen(self, page: Page) -> str | None:
        active = page.locator(".gen-btn--active").first
        try:
            if active.is_visible(timeout=500):
                return active.inner_text().strip()
        except Exception:
            pass
        gens = self._available_gens(page)
        return gens[0] if gens else None

    def _logged_in_user(self, page: Page) -> str | None:
        try:
            chip = page.locator("text=cloud save active").locator("xpath=..").first
            if chip.is_visible(timeout=300):
                raw = chip.inner_text().strip().splitlines()[0].strip()
                return re.sub(r"[^\w.\-_ ]", "", raw).strip()
        except Exception:
            pass
        return None
