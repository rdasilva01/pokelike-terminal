import re
from urllib.parse import unquote
from playwright.sync_api import Page
from parsers.base import AbstractParser


# Sprite filename → node type
SPRITE_TYPE = {
    "catchPokemon": "catch_pokemon",
    "grass":        "wild_encounter",
    "moveTutor":    "move_tutor",
    "questionMark": "mystery",
    "Poke%20Center": "pokecenter",
    "pokeCenter":   "pokecenter",
    "shop":         "shop",
    "itemDrop":     "item",
    "coin":         "item",
}

# Boss sprites (gym leaders / elite four names as they appear in filenames)
BOSS_SPRITES = {
    "brock", "misty", "surge", "erika", "koga", "janine",
    "sabrina", "blaine", "giovanni", "lorelei", "bruno",
    "agatha", "lance", "gary", "red",
    "falkner", "bugsy", "whitney", "morty", "chuck", "jasmine",
    "pryce", "clair", "will", "karen",
}


class MapParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return {
            "screen": "map",
            "stage":  self._parse_header(page),
            "team":   self._parse_team(page),
            "bag":    self._parse_bag(page),
            "badges": self._parse_badges(page),
            "nodes":  self._parse_nodes(page),
        }

    # ------------------------------------------------------------------ header

    def _parse_header(self, page: Page) -> dict:
        try:
            # map-header has display:none so use JS textContent directly
            text = page.evaluate(
                "() => document.querySelector('.map-header')?.textContent || ''"
            ).strip()
            m = re.search(r"Map\s+(\d+).*?vs\s+(.+?)\s+\((.+?)\)", text, re.IGNORECASE)
            if m:
                return {"number": int(m.group(1)), "boss": m.group(2).strip(), "boss_type": m.group(3).strip()}
            return {"number": None, "boss": None, "boss_type": None, "raw": text}
        except Exception:
            return {"number": None, "boss": None, "boss_type": None}

    # ------------------------------------------------------------------ team

    def _parse_team(self, page: Page) -> list:
        slots = page.locator(".team-slot").all()
        team = []
        for slot in slots:
            name  = self._txt(slot, ".team-slot-name")
            level = self._parse_level(self._txt(slot, ".team-slot-lv"))
            hp_pct = self._parse_hp_pct(slot)
            team.append({"name": name, "level": level, "hp_pct": hp_pct})
        return team

    def _parse_level(self, text: str) -> int | None:
        m = re.search(r"\d+", text)
        return int(m.group()) if m else None

    def _parse_hp_pct(self, slot) -> int:
        try:
            fill = slot.locator(".hp-bar-fill").first
            style = fill.get_attribute("style") or ""
            m = re.search(r"width\s*:\s*([\d.]+)%", style)
            return int(float(m.group(1))) if m else 100
        except Exception:
            return 100

    # ------------------------------------------------------------------ bag & badges

    def _parse_bag(self, page: Page) -> list:
        try:
            panel = page.locator(".map-panel-right").first
            text = panel.inner_text()
            if "Bag empty" in text:
                return []
            # TODO: parse actual item names when bag has items
            return []
        except Exception:
            return []

    def _parse_badges(self, page: Page) -> int:
        try:
            return len(page.locator(".badge-icon:not(.badge-icon-empty)").all())
        except Exception:
            return 0

    # ------------------------------------------------------------------ nodes

    def _parse_nodes(self, page: Page) -> list:
        nodes = page.evaluate("""() => {
            const svg = document.querySelector('.screen.active svg')
            if (!svg) return []
            return Array.from(svg.children)
                .filter(el => el.tagName === 'g')
                .map((g, i) => {
                    const img = g.querySelector('image')
                    const src = img?.getAttribute('href') || img?.getAttribute('xlink:href') || ''
                    const sprite = src.split('/').pop()?.replace('.png','') || ''
                    const style = g.getAttribute('style') || ''
                    const tx = g.getAttribute('transform') || ''
                    return {
                        index: i,
                        sprite: sprite,
                        completed: g.querySelector('circle') !== null,
                        accessible: style.includes('pointer'),
                        locked: style.includes('0.75'),
                        transform: tx
                    }
                })
        }""")

        result = []
        for n in nodes:
            sprite = unquote(n["sprite"])
            node_type = self._sprite_to_type(sprite)
            if n["completed"]:
                state = "completed"
            elif n["accessible"]:
                state = "available"
            else:
                state = "locked"
            result.append({
                "index":      n["index"],
                "type":       node_type,
                "state":      state,
                "accessible": n["accessible"],
                "sprite":     sprite,
            })
        return result

    def _sprite_to_type(self, sprite: str) -> str:
        if sprite in SPRITE_TYPE:
            return SPRITE_TYPE[sprite]
        if sprite.lower() in BOSS_SPRITES:
            return "boss"
        if sprite == "":
            return "start"
        return "trainer"

    # ------------------------------------------------------------------ util

    def _txt(self, locator, selector: str) -> str:
        try:
            return locator.locator(selector).first.inner_text().strip()
        except Exception:
            return ""
