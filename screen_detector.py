from enum import Enum, auto
from playwright.sync_api import Page


class ScreenType(Enum):
    MAIN_MENU = auto()
    STARTER_SELECT = auto()
    MAP = auto()
    CATCH_POKEMON = auto()
    ITEM_SELECT = auto()
    ITEM_EQUIP = auto()
    BATTLE_TOWER_REGION_SELECT = auto()
    STAGE_SELECT = auto()
    TEAM_SELECT = auto()
    BATTLE = auto()
    BADGE_OBTAINED = auto()
    TRADE_OFFER = auto()
    POKEMON_RECEIVED = auto()
    POKEMON_CENTER = auto()
    GAME_OVER = auto()
    UNKNOWN = auto()


def detect(page: Page) -> ScreenType:
    """Identify the current game screen with a single JS round-trip."""
    try:
        result = page.evaluate("""() => {
            const vis = sel => { const el = document.querySelector(sel); return !!(el && el.getBoundingClientRect().width > 0) }
            const has = sel => !!document.querySelector(sel)
            if (vis('.gameover-title'))     return 'GAME_OVER'
            if (vis('.battle-header'))      return 'BATTLE'
            if (vis('.poke-choice-wrap'))   return 'CATCH_POKEMON'
            if (vis('.item-equip-overlay')) return 'ITEM_EQUIP'
            if (vis('.trade-member-row'))   return 'TRADE_OFFER'
            if (vis('.shiny-title'))        return 'POKEMON_RECEIVED'
            if (vis('.item-card'))          return 'ITEM_SELECT'
            const btnsAll = Array.from(document.querySelectorAll('.btn-primary'))
            if (btnsAll.some(b => b.textContent.includes('Next Map') && b.getBoundingClientRect().width > 0)) return 'BADGE_OBTAINED'
            if (btnsAll.some(b => b.textContent.trim() === 'Normal Mode' && b.getBoundingClientRect().width > 0)) return 'MAIN_MENU'
            const text = document.body.innerText || ''
            if (text.includes('Choose Your Starter')) return 'STARTER_SELECT'
            if (vis('.team-slot'))          return 'MAP'
            return 'UNKNOWN'
        }""")
        return ScreenType[result]
    except Exception:
        return ScreenType.UNKNOWN
