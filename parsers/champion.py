from playwright.sync_api import Page
from parsers.base import AbstractParser


class ChampionParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return page.evaluate("""() => {
            const title     = document.querySelector('.win-title')?.textContent.replace(/\\s+/g, ' ').trim() || ''
            const run_count = document.querySelector('#win-run-count')?.textContent.trim() || ''
            const team = Array.from(document.querySelectorAll('#win-team .poke-card')).map(card => {
                const name  = card.querySelector('.poke-name')?.textContent.trim() || ''
                const level = card.querySelector('.poke-level')?.textContent.trim() || ''
                const types = Array.from(card.querySelectorAll('.poke-types .type-badge')).map(t => t.textContent.trim())
                const hp    = card.querySelector('.hp-text')?.textContent.trim() || ''
                const move  = card.querySelector('.move-name')?.textContent.trim() || ''
                const stats = {}
                card.querySelectorAll('.stat-row').forEach(row => {
                    const lbl = row.querySelector('.stat-lbl')?.textContent.trim()
                    const val = row.querySelector('.stat-val')?.textContent.trim()
                    if (lbl && val) stats[lbl] = parseInt(val)
                })
                return { name, level, types, hp, move, stats }
            })
            return { screen: 'champion', title, run_count, team }
        }""")
