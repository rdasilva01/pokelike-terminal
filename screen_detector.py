from enum import Enum, auto
from playwright.sync_api import Page


class ScreenType(Enum):
    MAIN_MENU = auto()
    STARTER_SELECT = auto()
    MAP = auto()
    CATCH_POKEMON = auto()
    BATTLE_TOWER_REGION_SELECT = auto()
    STAGE_SELECT = auto()
    TEAM_SELECT = auto()
    BATTLE = auto()
    POKEMON_CENTER = auto()
    UNKNOWN = auto()


def detect(page: Page) -> ScreenType:
    """Identify the current game screen by unique DOM fingerprints."""
    if _has_text(page, "Choose Your Starter"):
        return ScreenType.STARTER_SELECT
    if _has_class(page, ".poke-choice-wrap"):
        return ScreenType.CATCH_POKEMON
    if _has_class(page, ".team-slot"):
        return ScreenType.MAP
    if _has_text_button(page, "Normal Mode"):
        return ScreenType.MAIN_MENU
    return ScreenType.UNKNOWN


def _has_class(page: Page, selector: str) -> bool:
    try:
        return page.locator(selector).first.is_visible(timeout=300)
    except Exception:
        return False


def _has_text(page: Page, text: str) -> bool:
    try:
        return page.locator(f"text={text}").first.is_visible(timeout=300)
    except Exception:
        return False


def _has_text_button(page: Page, text: str) -> bool:
    try:
        return page.locator(f"text={text}").first.is_visible(timeout=500)
    except Exception:
        return False
