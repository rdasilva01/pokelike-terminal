from playwright.sync_api import Page
from parsers.base import AbstractParser


class TeamSelectParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return page.evaluate("""() => {
            const titleEl = document.querySelector('.pc-box > div, .pc-box-title, .pc-box h3, .pc-box span')
            const titleText = document.querySelector('.pc-box')?.childNodes[0]?.textContent?.trim()
                || document.querySelector('.pc-box')?.firstElementChild?.textContent?.trim()
                || 'HALL OF FAME PC'
            const slots = Array.from(document.querySelectorAll('.pc-box-grid .pc-slot'))
            const pokemon = slots.map((slot, i) => {
                const name   = slot.querySelector('.pc-slot-name')?.textContent.trim() || ''
                const level  = slot.querySelector('.pc-slot-lv')?.textContent.replace('Lv.','').trim() || ''
                const types  = Array.from(slot.querySelectorAll('.type-badge')).map(t => t.textContent.trim())
                const isShiny = !!slot.querySelector('img[title="Shiny!"]')
                const buff   = (slot.textContent.match(/★/g) || []).length
                return { name, level, types, is_shiny: isShiny, buff, index: i }
            })
            return { screen: 'team_select', title: titleText, pokemon }
        }""")
