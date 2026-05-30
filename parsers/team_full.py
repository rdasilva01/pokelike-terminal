from playwright.sync_api import Page
from parsers.base import AbstractParser


class TeamFullParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return page.evaluate("""() => {
            const screen = document.querySelector('.screen.active')

            // All poke-cards in screen.active — last one is the incoming pokemon
            const allCards = Array.from(screen?.querySelectorAll('.poke-card') || [])
            const parseCard = c => ({
                name:      c.querySelector('.poke-name')?.textContent.trim()  || '',
                level:     c.querySelector('.poke-level')?.textContent.trim() || '',
                types:     Array.from(c.querySelectorAll('.poke-types .type-badge')).map(t => t.textContent.trim()),
                is_shiny:  !!c.querySelector('.shiny-badge'),
                is_caught: !!c.querySelector('.dex-caught-badge'),
            })

            const incoming = allCards.length > 0 ? [parseCard(allCards[allCards.length - 1])] : []
            const team = allCards.slice(0, allCards.length - 1).map((c, i) => ({
                index: i, ...parseCard(c)
            }))

            const prompt = document.querySelector('.swap-prompt')?.textContent.trim() || ''

            return { screen: 'team_full', prompt, incoming, team }
        }""")
