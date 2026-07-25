"""Тесты парсера Kwork через фиктивный DOM (без обращения к Kwork)."""

from __future__ import annotations

from parsers.kwork_parser import (
    BUDGET_SELECTOR,
    CARD_SELECTOR,
    DESC_SELECTOR,
    TITLE_SELECTOR,
    KworkParser,
)


class FakeElement:
    def __init__(self, text: str = "", href: str | None = None) -> None:
        self._text = text
        self._href = href

    async def inner_text(self) -> str:
        return self._text

    async def get_attribute(self, name: str) -> str | None:
        return self._href if name == "href" else None


class FakeCard:
    def __init__(self, title: str, href: str, desc: str, budget: str) -> None:
        self.title = title
        self.href = href
        self.desc = desc
        self.budget = budget

    async def query_selector(self, selector: str) -> FakeElement | None:
        if selector == TITLE_SELECTOR:
            return FakeElement(self.title, self.href) if (self.title and self.href) else (
                FakeElement(self.title, self.href)
            )
        if selector == DESC_SELECTOR:
            return FakeElement(self.desc)
        if selector == BUDGET_SELECTOR:
            return FakeElement(self.budget)
        return None


class FakePage:
    def __init__(self, cards: list[FakeCard], url: str = "https://kwork.ru/projects") -> None:
        self._cards = cards
        self.url = url

    async def wait_for_selector(self, selector: str, timeout: int = 0) -> bool:
        return True

    async def query_selector_all(self, selector: str) -> list[FakeCard]:
        return self._cards if selector == CARD_SELECTOR else []


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    async def goto(self, url: str, *, retries: int = 3) -> FakePage:
        return self._page


async def test_parses_valid_card() -> None:
    cards = [
        FakeCard("Нужен парсер на Python", "/projects/view/123", "Собрать данные", "5 000 ₽"),
        FakeCard("", "/projects/view/999", "нет заголовка", "1 000 ₽"),  # без title — отсеивается
    ]
    parser = KworkParser(FakeBrowser(FakePage(cards)), "https://kwork.ru/projects")

    leads = await parser.fetch_leads()

    assert len(leads) == 1
    lead = leads[0]
    assert lead.source == "kwork"
    assert lead.external_id == "123"
    assert lead.url == "https://kwork.ru/projects/view/123"
    assert lead.budget_value == 5000
    assert "Python" in lead.title


async def test_absolute_url_preserved() -> None:
    cards = [FakeCard("Python бот", "https://kwork.ru/projects/view/77", "описание", "договорная")]
    parser = KworkParser(FakeBrowser(FakePage(cards)), "https://kwork.ru/projects")

    leads = await parser.fetch_leads()

    assert len(leads) == 1
    assert leads[0].url == "https://kwork.ru/projects/view/77"
    assert leads[0].external_id == "77"
    assert leads[0].budget_value is None  # «договорная» → бюджет не распознан


async def test_logged_out_returns_empty() -> None:
    page = FakePage([], url="https://kwork.ru/login")
    parser = KworkParser(FakeBrowser(page), "https://kwork.ru/projects")
    assert await parser.fetch_leads() == []


async def test_no_cards_returns_empty() -> None:
    parser = KworkParser(FakeBrowser(FakePage([])), "https://kwork.ru/projects")
    assert await parser.fetch_leads() == []
