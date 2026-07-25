"""Telegram-слой (aiogram 3.x): бот, роутеры, middlewares, доставка."""

from telegram.bot import build_bot, build_dispatcher
from telegram.delivery import DeliveryService

__all__ = ["build_bot", "build_dispatcher", "DeliveryService"]
