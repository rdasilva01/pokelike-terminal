from playwright.sync_api import Page
from parsers.base import AbstractParser


class TradeOfferParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        result = page.evaluate("""() => {
            const members = Array.from(document.querySelectorAll('.trade-member-row')).map(row => ({
                name:  row.querySelector('.trade-member-name')?.textContent.trim() || '',
                level: row.querySelector('.trade-member-level')?.textContent.trim() || '',
                types: Array.from(row.querySelectorAll('.type-badge')).map(t => t.textContent.trim()),
            }))
            return { members }
        }""")
        return {
            "screen":  "trade_offer",
            "members": result["members"],
        }
