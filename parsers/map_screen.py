import json
import re
from urllib.parse import unquote
from playwright.sync_api import Page
from parsers.base import AbstractParser


# Sprite filename → node type
SPRITE_TYPE = {
    "catchPokemon":  "catch_pokemon",
    "grass":         "wild_encounter",
    "moveTutor":     "move_tutor",
    "questionMark":  "mystery",
    "Poke Center":   "pokecenter",
    "Poke%20Center": "pokecenter",
    "pokeCenter":    "pokecenter",
    "shop":          "shop",
    "itemDrop":      "item",
    "itemIcon":      "item",
    "coin":          "item",
    "tradeIcon":     "trade",
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

    def _load_run_team(self, page: Page) -> list:
        try:
            raw = page.evaluate("() => localStorage.getItem('poke_current_run')")
            return json.loads(raw).get("team", []) if raw else []
        except Exception:
            return []

    def _parse_team(self, page: Page) -> list:
        slots = page.locator(".map-panel-left .team-slot").all()
        run_team = self._load_run_team(page)
        team = []
        for i, slot in enumerate(slots):
            name   = self._txt(slot, ".team-slot-name")
            level  = self._parse_level(self._txt(slot, ".team-slot-lv"))
            hp_pct = self._parse_hp_pct(slot)
            ls = run_team[i] if i < len(run_team) else {}
            team.append({
                "name":       name,
                "level":      level,
                "hp_pct":     hp_pct,
                "hp_current": ls.get("currentHp"),
                "hp_max":     ls.get("maxHp"),
                "move_tier":  ls.get("moveTier"),
                "types":      ls.get("types", []),
            })
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
            return page.evaluate("""() =>
                Array.from(document.querySelectorAll('#item-bar .item-badge'))
                    .filter(b => b.getBoundingClientRect().width > 0)
                    .map((b, i) => ({ name: b.querySelector('img')?.alt?.trim() || b.textContent.trim(), index: i }))
            """)
        except Exception:
            return []

    def _parse_badges(self, page: Page) -> int:
        try:
            return page.evaluate("""() =>
                Array.from(document.querySelectorAll('.badge-icon'))
                     .filter(img => img.src && img.src !== window.location.href)
                     .length
            """)
        except Exception:
            return 0

    # ------------------------------------------------------------------ nodes

    def _parse_nodes(self, page: Page) -> list:
        nodes = page.evaluate("""() => {
            const svg = document.querySelector('.screen.active svg')
            if (!svg) return []

            // Build sprite -> label map from localStorage for accessible trainer nodes
            const spriteLabelMap = {}
            try {
                const run = JSON.parse(localStorage.getItem('poke_current_run') || '{}')
                Object.values(run.map?.nodes || {}).filter(n => n.accessible && n.trainerSprite).forEach(n => {
                    try { spriteLabelMap[n.trainerSprite] = getNodeLabel(n, run) } catch(e) {}
                })
            } catch(e) {}

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
                        transform: tx,
                        nodeLabel: spriteLabelMap[sprite] || ''
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
            # Extract Pokémon type from label e.g. "Officer — +2 Levels — Fire Pokemon"
            poke_type = ""
            if n.get("nodeLabel"):
                parts = [p.strip() for p in n["nodeLabel"].split("—")]
                for part in reversed(parts):
                    if "Pokemon" in part or "Type" in part:
                        poke_type = part.replace("Pokemon", "").replace("Type", "").strip()
                        break
            result.append({
                "index":      n["index"],
                "type":       node_type,
                "state":      state,
                "accessible": n["accessible"],
                "sprite":     sprite,
                "poke_type":  poke_type,
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
            return locator.locator(selector).first.inner_text(timeout=2000).strip()
        except Exception:
            return ""
