from abc import ABC, abstractmethod
from playwright.sync_api import Page


class AbstractParser(ABC):
    @abstractmethod
    def parse(self, page: Page) -> dict:
        ...
