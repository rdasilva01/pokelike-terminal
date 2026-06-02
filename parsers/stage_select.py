from playwright.sync_api import Page
from parsers.base import AbstractParser


class StageSelectParser(AbstractParser):
    def parse(self, page: Page) -> dict:
        return page.evaluate("""() => {
            const stages = Array.from(document.querySelectorAll('#stage-select-list button'))
                .map(b => {
                    const nameEl = b.querySelector('div > div:first-child')
                    const genEl  = b.querySelector('div > div:last-child')
                    return {
                        name:    (nameEl?.textContent.trim() || b.textContent.trim()).replace(/^[▶🔒]\s*/, ''),
                        gen:     genEl?.textContent.trim() || '',
                        enabled: !b.disabled && b.style.opacity !== '0.45' && b.style.cursor !== 'not-allowed',
                    }
                })
            return { screen: 'stage_select', stages }
        }""")
