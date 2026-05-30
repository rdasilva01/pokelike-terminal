import json
import re
from urllib.parse import unquote
from playwright.sync_api import Page
from parsers.base import AbstractParser


# Sprite filename → node type
KNOWN_TYPES = {
    "normal", "fire", "water", "grass", "electric", "ice", "fighting",
    "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
    "dragon", "dark", "steel", "fairy",
}

# Fallback type per known boss sprite name (gym leaders / elite four).
BOSS_SPRITE_TYPE = {
    "brock":    "Rock",     "misty":    "Water",    "surge":    "Electric",
    "erika":    "Grass",    "koga":     "Poison",   "janine":   "Poison",
    "sabrina":  "Psychic",  "blaine":   "Fire",     "giovanni": "Ground",
    "lorelei":  "Ice",      "bruno":    "Fighting", "agatha":   "Ghost",
    "lance":    "Dragon",   "gary":     "Normal",   "red":      "Normal",
    "falkner":  "Flying",   "bugsy":    "Bug",      "whitney":  "Normal",
    "morty":    "Ghost",    "chuck":    "Fighting", "jasmine":  "Steel",
    "pryce":    "Ice",      "clair":    "Dragon",   "will":     "Psychic",
    "karen":    "Dark",
}

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
        stage = self._parse_header(page)
        stage["boss_team"] = self._parse_boss_team(page)
        return {
            "screen": "map",
            "stage":  stage,
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

    def _parse_boss_team(self, page: Page) -> list:
        try:
            return page.evaluate("""() => {
                try {
                    const run = JSON.parse(localStorage.getItem('poke_current_run') || '{}')
                    const mapIdx = run.currentMap
                                ?? (typeof state !== 'undefined' ? state.currentMap : null)
                    const gen2   = run.gen2Mode
                                || (typeof state !== 'undefined' ? !!state.gen2Mode : false)
                    const leaders = gen2 ? JOHTO_GYM_LEADERS : GYM_LEADERS
                    const leader  = leaders?.[mapIdx]
                    if (!leader?.team?.length) return []
                    return leader.team.map(p => ({
                        name:  p.name || p.species || String(p.speciesId || ''),
                        level: p.level || p.lv || 0,
                    }))
                } catch(e) { return [] }
            }""")
        except Exception:
            return []

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
        # Build name→entry map so swapped DOM order still finds the right LS data.
        # Try common field names the game might use for species/name.
        ls_by_name: dict[str, dict] = {}
        for entry in run_team:
            for field in ("name", "species", "speciesName", "nickname", "pokemon"):
                val = entry.get(field)
                if isinstance(val, str) and val:
                    ls_by_name[val.lower()] = entry
                    break
        team = []
        for i, slot in enumerate(slots):
            name   = self._txt(slot, ".team-slot-name")
            level  = self._parse_level(self._txt(slot, ".team-slot-lv"))
            hp_pct = self._parse_hp_pct(slot)
            # Match by name first; fall back to positional if name not found in LS.
            ls = ls_by_name.get(name.lower()) or (run_team[i] if i < len(run_team) else {})
            # Held item: try several known LS field names then fall back to DOM
            raw_held = (
                ls.get("heldItem")
                or ls.get("item")
                or ls.get("equippedItem")
                or ls.get("heldItemName")
                or self._held_item_from_dom(slot)
            )
            # Item may be a dict {"name": "...", "id": "...", ...} or a plain string
            if isinstance(raw_held, dict):
                held = raw_held.get("name") or raw_held.get("id") or ""
            else:
                held = raw_held or ""
            team.append({
                "name":       name,
                "level":      level,
                "hp_pct":     hp_pct,
                "hp_current": ls.get("currentHp"),
                "hp_max":     ls.get("maxHp"),
                "move_tier":  ls.get("moveTier"),
                "types":      ls.get("types", []),
                "held_item":  held or None,
            })
        return team

    def _held_item_from_dom(self, slot) -> str:
        """Try to scrape held-item name from the team-slot DOM element."""
        for sel in (".held-item", ".item-badge", "[class*='held']", "[class*='equip']"):
            try:
                el = slot.locator(sel).first
                if el.count() == 0:
                    continue
                text = el.inner_text(timeout=300).strip()
                if text:
                    return text
                alt = el.get_attribute("alt") or el.get_attribute("title") or ""
                if alt:
                    return alt
            except Exception:
                pass
        return ""

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

            let lsNodes = []
            const indexLabelMap = {}
            try {
                const run = JSON.parse(localStorage.getItem('poke_current_run') || '{}')
                const lsMap = run.map?.nodes || {}
                lsNodes = Object.values(lsMap)
                lsNodes.forEach((n, i) => {
                    try {
                        // 1. Try the game's own label function (works for nodes with trainerSprite)
                        let label = ''
                        if (typeof getNodeLabel === 'function') {
                            label = getNodeLabel(n, run) || ''
                        }
                        // 2. Direct field fallback for nodes the game hasn't fully initialised
                        if (!label) {
                            const t = n.pokemonType || n.trainerType || n.pokeType
                                   || n.pokemon_type || n.poke_type || ''
                            if (t) label = t + ' Pokemon'
                        }
                        if (label) indexLabelMap[i] = label
                    } catch(e) {}
                })
            } catch(e) {}

            return Array.from(svg.children)
                .filter(el => el.tagName === 'g')
                .map((g, i) => {
                    const img = g.querySelector('image')
                    const src = img?.getAttribute('href') || img?.getAttribute('xlink:href') || ''
                    const sprite = src.split('/').pop()?.replace('.png','') || ''
                    const style = g.getAttribute('style') || ''
                    const lsNode = lsNodes[i] || {}
                    const lsDone = lsNode.done === true || lsNode.completed === true
                        || lsNode.state === 'done' || lsNode.state === 'completed'
                        || lsNode.cleared === true || lsNode.visited === true
                    // SVG title/data-attribute fallback for type info
                    const svgTitle = g.querySelector('title')?.textContent || ''
                    const svgType  = g.getAttribute('data-pokemon-type')
                                  || g.getAttribute('data-type') || ''
                    const extraLabel = svgTitle || svgType
                    return {
                        index:      i,
                        sprite:     sprite,
                        accessible: lsNode.accessible || style.includes('pointer'),
                        ls_done:    lsDone,
                        ls_raw:     lsNode,
                        nodeLabel:  indexLabelMap[i] || extraLabel || '',
                        ls_type:    lsNode.type || lsNode.nodeType || lsNode.kind || '',
                        ls_sprite:  lsNode.trainerSprite || lsNode.sprite || lsNode.spriteKey || ''
                    }
                })
        }""")

        result = []
        for n in nodes:
            sprite    = unquote(n["sprite"])
            ls_sprite = unquote(n.get("ls_sprite", ""))
            ls_type   = (n.get("ls_type") or "").lower()
            label     = (n.get("nodeLabel") or "").lower()
            node_type = self._sprite_to_type(sprite, ls_sprite, ls_type, label)
            if n["ls_done"]:
                state = "completed"
            elif n["accessible"]:
                state = "available"
            else:
                state = "locked"
            # Extract Pokémon type from label.
            # Primary: "Fire Pokemon" / "Fire Type" patterns.
            # Fallback: any segment that is itself a known type name (e.g. boss labels
            # like "Gym Leader — Lance — Dragon" have no "Pokemon" keyword).
            poke_type = ""
            if n.get("nodeLabel"):
                parts = [p.strip() for p in n["nodeLabel"].split("—")]
                for part in reversed(parts):
                    if "Pokemon" in part or "Type" in part:
                        poke_type = part.replace("Pokemon", "").replace("Type", "").strip()
                        break
                if not poke_type:
                    for part in reversed(parts):
                        if part.strip().lower() in KNOWN_TYPES:
                            poke_type = part.strip().title()
                            break
            # For boss nodes whose label has no type info, fall back to the
            # known-boss sprite→type table (covers all gen 1/2 gym leaders + E4).
            if not poke_type and node_type == "boss":
                for s in (unquote(n.get("ls_sprite", "")), unquote(n.get("sprite", ""))):
                    t = BOSS_SPRITE_TYPE.get(s.lower())
                    if t:
                        poke_type = t
                        break
            result.append({
                "index":      n["index"],
                "type":       node_type,
                "state":      state,
                "accessible": n["accessible"],
                "sprite":     sprite,
                "poke_type":  poke_type,
                "_ls":        n.get("ls_raw", {}),  # raw LS node — remove once correct field found
            })
        return result

    _BOSS_LABEL_KEYWORDS = ("gym leader", "elite four", "elite 4", "champion", "boss")

    def _sprite_to_type(self, sprite: str, ls_sprite: str = "",
                        ls_type: str = "", label: str = "") -> str:
        if sprite in SPRITE_TYPE:
            return SPRITE_TYPE[sprite]
        # Check both the rendered SVG sprite and the LS trainerSprite field
        for s in (sprite.lower(), ls_sprite.lower()):
            if s in BOSS_SPRITES:
                return "boss"
        # LS type field may explicitly say "boss" / "gym" / etc.
        if any(kw in ls_type for kw in ("boss", "gym", "elite", "champion")):
            return "boss"
        # Node label (from getNodeLabel) often names the role
        if any(kw in label for kw in self._BOSS_LABEL_KEYWORDS):
            return "boss"
        if sprite == "" and ls_sprite == "":
            return "start"
        return "trainer"

    # ------------------------------------------------------------------ util

    def _txt(self, locator, selector: str) -> str:
        try:
            return locator.locator(selector).first.inner_text(timeout=2000).strip()
        except Exception:
            return ""
