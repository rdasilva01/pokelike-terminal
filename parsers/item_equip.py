from playwright.sync_api import Page
from parsers.base import AbstractParser


class ItemEquipParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        result = page.evaluate("""() => {
            const overlay = document.querySelector('.item-equip-overlay')
            if (!overlay) return null

            const item_name = overlay.querySelector('.equip-item-name')?.textContent.trim() || ''
            const item_desc = overlay.querySelector('.equip-item-desc')?.textContent.trim() || ''
            const is_move_tutor = item_name === 'Move Tutor'

            const pokemon = Array.from(overlay.querySelectorAll('.equip-pokemon-row')).map(row => {
                const name    = row.querySelector('.equip-poke-name')?.textContent.trim() || ''
                const info    = row.querySelector('.equip-poke-lv')?.textContent.trim() || ''
                const heldEl  = row.querySelector('.equip-held-item')
                const emptyEl = row.querySelector('.equip-empty-slot')
                const held_item = heldEl ? heldEl.textContent.trim() : null
                const action  = row.querySelector('.equip-btn')?.textContent.trim() || ''
                return { name, info, held_item, action }
            })

            const hasKeepInBag = !!Array.from(overlay.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Keep in Bag')

            return { item_name, item_desc, is_move_tutor, pokemon, has_keep_in_bag: hasKeepInBag }
        }""")

        if not result:
            return {"screen": "item_equip", "item_name": "", "item_desc": "",
                    "is_move_tutor": False, "pokemon": [], "has_keep_in_bag": False}
        result["screen"] = "item_equip"
        return result
