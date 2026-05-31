from playwright.sync_api import Page
from parsers.base import AbstractParser


class PokemonReceivedParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return page.evaluate("""() => {
            const card = document.querySelector('.screen.active .poke-card')
            const title = document.querySelector('.shiny-title')?.textContent.trim() || ''

            if (!card) return { screen: 'pokemon_received', title, pokemon: null }

            const name   = card.querySelector('.poke-name')?.textContent.trim() || ''
            const level  = card.querySelector('.poke-level')?.textContent.trim() || ''
            const types  = Array.from(card.querySelectorAll('.poke-types .type-badge')).map(t => t.textContent.trim())
            const hp     = card.querySelector('.hp-text')?.textContent.trim() || ''
            const move   = card.querySelector('.move-name')?.textContent.trim() || ''
            const movePw = card.querySelector('.move-power-badge')?.textContent.trim() || ''
            const moveType = card.querySelector('.move-header .type-badge')?.textContent.trim() || ''
            const stats  = {}
            card.querySelectorAll('.stat-row').forEach(row => {
                const lbl = row.querySelector('.stat-lbl')?.textContent.trim()
                const val = row.querySelector('.stat-val')?.textContent.trim()
                if (lbl && val) stats[lbl] = parseInt(val)
            })
            const is_shiny  = !!card.querySelector('.poke-sprite.shiny')
            const is_caught = !!card.querySelector('.dex-caught-badge')

            const buttons = Array.from(document.querySelectorAll('.btn-primary, .btn-secondary'))
                .filter(b => b.getBoundingClientRect().width > 0)
                .map(b => b.textContent.trim())

            return {
                screen: 'pokemon_received',
                title,
                buttons,
                pokemon: { name, level, types, hp, move, move_type: moveType,
                           move_power: movePw, stats, is_shiny, is_caught }
            }
        }""")
