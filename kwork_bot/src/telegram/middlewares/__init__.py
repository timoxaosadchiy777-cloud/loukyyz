"""Middlewares Telegram (порядок применения: license → ratelimit → dedup)."""

from telegram.middlewares.dedup import DedupMiddleware
from telegram.middlewares.license import LicenseMiddleware
from telegram.middlewares.ratelimit import RateLimitMiddleware

__all__ = ["LicenseMiddleware", "RateLimitMiddleware", "DedupMiddleware"]
