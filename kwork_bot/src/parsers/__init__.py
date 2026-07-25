"""Парсеры: менеджер браузера Playwright и парсер Kwork."""

from parsers.browser import BrowserManager
from parsers.kwork_parser import KworkParser

__all__ = ["BrowserManager", "KworkParser"]
