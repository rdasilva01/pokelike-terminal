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
        team            = self._parse_team(page)
        static          = self._parse_static(page)
        stage           = static["stage"]
        stage["boss_team"] = static["boss_team"]
        return {
            "screen": "map",
            "stage":  stage,
            "team":   team,
            "bag":    static["bag"],
            "badges": static["badges"],
            "nodes":  self._process_nodes(static["nodes"]),
        }

    # ------------------------------------------------------------------ team (1 round-trip)

    def _parse_team(self, page: Page) -> list:
        try:
            return page.evaluate("""() => {
                let runTeam = []
                try {
                    runTeam = JSON.parse(localStorage.getItem('poke_current_run') || '{}').team || []
                } catch(e) {}
                const lsByName = {}
                runTeam.forEach(e => {
                    for (const f of ['name','species','speciesName','nickname','pokemon']) {
                        if (typeof e[f] === 'string' && e[f]) { lsByName[e[f].toLowerCase()] = e; break }
                    }
                })
                return Array.from(document.querySelectorAll('.map-panel-left .team-slot')).map((slot, i) => {
                    const name   = slot.querySelector('.team-slot-name')?.innerText.trim() || ''
                    const lvText = slot.querySelector('.team-slot-lv')?.innerText.trim() || ''
                    const lv     = parseInt(lvText.match(/[0-9]+/)?.[0]) || null
                    const style  = slot.querySelector('.hp-bar-fill')?.getAttribute('style') || ''
                    const hpPct  = parseInt(style.match(/([0-9.]+)%/)?.[1]) || 100
                    const ls     = lsByName[name.toLowerCase()] || runTeam[i] || {}
                    let held = ls.heldItem || ls.item || ls.equippedItem || ls.heldItemName || ''
                    if (held && typeof held === 'object') held = held.name || held.id || ''
                    // DOM fallback for held item
                    if (!held) {
                        for (const sel of ['.held-item','.item-badge','[class*="held"]','[class*="equip"]']) {
                            const el = slot.querySelector(sel)
                            if (el) { held = el.innerText.trim() || el.alt || el.title || ''; if (held) break }
                        }
                    }
                    return {
                        name,
                        level:      lv,
                        hp_pct:     hpPct,
                        hp_current: ls.currentHp  ?? null,
                        hp_max:     ls.maxHp       ?? null,
                        move_tier:  ls.moveTier    ?? null,
                        types:      ls.types       || [],
                        held_item:  held           || null,
                    }
                })
            }""")
        except Exception:
            return []

    # ------------------------------------------------------------------ everything else (1 round-trip)

    def _parse_static(self, page: Page) -> dict:
        try:
            return page.evaluate("""() => {
                const run = (() => {
                    try { return JSON.parse(localStorage.getItem('poke_current_run') || '{}') } catch(e) { return {} }
                })()

                // --- header ---
                const headerText = document.querySelector('.map-header')?.textContent || ''
                const hm = headerText.match(/Map\\s+(\\d+).*?vs\\s+(.+?)\\s+\\((.+?)\\)/i)
                const stage = hm
                    ? { number: parseInt(hm[1]), boss: hm[2].trim(), boss_type: hm[3].trim() }
                    : { number: null, boss: null, boss_type: null, raw: headerText.trim() }

                // --- boss team ---
                let boss_team = []
                try {
                    const mapIdx  = run.currentMap ?? (typeof state !== 'undefined' ? state.currentMap : null)
                    const gen2    = run.gen2Mode || (typeof state !== 'undefined' ? !!state.gen2Mode : false)
                    const leaders = gen2 ? JOHTO_GYM_LEADERS : GYM_LEADERS
                    const leader  = leaders?.[mapIdx]
                    if (leader?.team?.length) {
                        boss_team = leader.team.map(p => ({
                            name:  p.name || p.species || String(p.speciesId || ''),
                            level: p.level || p.lv || 0,
                        }))
                    }
                } catch(e) {}

                // --- bag ---
                const bag = Array.from(document.querySelectorAll('#item-bar .item-badge'))
                    .filter(b => b.getBoundingClientRect().width > 0)
                    .map((b, i) => ({ name: b.querySelector('img')?.alt?.trim() || b.textContent.trim(), index: i }))

                // --- badges ---
                const badges = Array.from(document.querySelectorAll('.badge-icon'))
                    .filter(img => img.src && img.src !== window.location.href).length

                // --- nodes ---
                const svg = document.querySelector('.screen.active svg')
                let nodes = []
                if (svg) {
                    let lsNodes = []
                    const indexLabelMap = {}
                    try {
                        const lsMap = run.map?.nodes || {}
                        lsNodes = Object.values(lsMap)
                        lsNodes.forEach((n, i) => {
                            try {
                                let label = ''
                                if (typeof getNodeLabel === 'function') label = getNodeLabel(n, run) || ''
                                if (!label) {
                                    const t = n.pokemonType || n.trainerType || n.pokeType
                                           || n.pokemon_type || n.poke_type || ''
                                    if (t) label = t + ' Pokemon'
                                }
                                if (label) indexLabelMap[i] = label
                            } catch(e) {}
                        })
                    } catch(e) {}

                    nodes = Array.from(svg.children)
                        .filter(el => el.tagName === 'g')
                        .map((g, i) => {
                            const img    = g.querySelector('image')
                            const src    = img?.getAttribute('href') || img?.getAttribute('xlink:href') || ''
                            const sprite = src.split('/').pop()?.replace('.png','') || ''
                            const style  = g.getAttribute('style') || ''
                            const lsNode = lsNodes[i] || {}
                            const lsDone = lsNode.done === true || lsNode.completed === true
                                || lsNode.state === 'done' || lsNode.state === 'completed'
                                || lsNode.cleared === true || lsNode.visited === true
                            const svgTitle = g.querySelector('title')?.textContent || ''
                            const svgType  = g.getAttribute('data-pokemon-type') || g.getAttribute('data-type') || ''
                            return {
                                index:      i,
                                sprite,
                                accessible: lsNode.accessible || style.includes('pointer'),
                                ls_done:    lsDone,
                                ls_raw:     lsNode,
                                nodeLabel:  indexLabelMap[i] || svgTitle || svgType || '',
                                ls_type:    lsNode.type || lsNode.nodeType || lsNode.kind || '',
                                ls_sprite:  lsNode.trainerSprite || lsNode.sprite || lsNode.spriteKey || '',
                            }
                        })
                }

                return { stage, boss_team, bag, badges, nodes }
            }""")
        except Exception:
            return {"stage": {"number": None, "boss": None, "boss_type": None},
                    "boss_team": [], "bag": [], "badges": 0, "nodes": []}

    # ------------------------------------------------------------------ nodes post-processing (CPU only)

    def _process_nodes(self, nodes: list) -> list:

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

