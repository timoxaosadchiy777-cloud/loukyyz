#!/usr/bin/env python3
"""Диагностика потока лидов: какие биржи реально опрашиваются и почему.

Отвечает на один вопрос — «почему лиды не идут» — по шагам, на которых поток
может оборваться:

    реестр → выбор пользователя → сборка парсера → запрос к бирже → свежесть

Запуск (из каталога leadhunter/):

    python -m tools.check_sources            # без сети: состояние и причины
    python -m tools.check_sources --poll     # плюс один реальный опрос каждой
    python -m tools.check_sources --poll --source freelancer

Ничего не меняет: только читает базу и, с ``--poll``, ходит на биржи.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from config import get_settings
from core.freshness import age_hours, is_fresh
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from core.sources import SOURCES, get_source
from database.db import Database
from parsers.registry import build_one

OK, OFF, BAD = "🟢", "⚪", "🔴"


def line(text: str = "") -> None:
    print(text, flush=True)


def rule(title: str) -> None:
    line()
    line(f"── {title} " + "─" * max(0, 60 - len(title)))


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Диагностика источников лидов")
    parser.add_argument("--poll", action="store_true",
                        help="сделать один реальный запрос к каждой активной бирже")
    parser.add_argument("--source", default="",
                        help="проверять только эту биржу (id из реестра)")
    args = parser.parse_args(argv)

    # Лишний лог парсеров мешает читать отчёт; ошибки всё равно покажем сами.
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")

    settings = get_settings()
    config = RuntimeConfigStore(settings.runtime_config_file, defaults=RuntimeConfig())

    line("LeadHunter — проверка источников")
    line(f"База:      {settings.database_file}")
    line(f"Настройки: {settings.runtime_config_file}")
    line(f"Свежесть:  лиды не старше {settings.max_lead_age_hours} ч")

    db = Database(str(settings.database_file))
    await db.connect()
    try:
        wanted, has_recipients = await _report_users(db, settings)
        allowed = _report_owner_switch(config, wanted)
        active = _report_parsers(wanted & allowed, settings, args.source, has_recipients)
        await _report_stored_leads(db, settings)
        if args.poll:
            await _poll(active, settings)
    finally:
        await db.close()

    rule("Итог")
    line("Пусто в «найдено N новых»? Смотрите раздел «Парсеры»: там причина.")
    line("Биржа выключена у пользователя — она не опрашивается вообще, это норма.")
    return 0


# --- Шаг 1: кто и что выбрал ----------------------------------------------


async def _report_users(db: Database, settings) -> tuple[set[str], bool]:
    rule("Пользователи и их выбор бирж")

    recipients = await db.list_recipients(settings.owner_id)
    if not recipients:
        line("Получателей нет: никому не выдан доступ и не задан OWNER_ID.")
        line("Ни один парсер не запустится — некому отправлять лиды.")
        return set(), False

    for telegram_id, user in recipients:
        who = f"{telegram_id}" + (" (владелец)" if telegram_id == settings.owner_id else "")
        enabled = ", ".join(user.sources) or "НИ ОДНОЙ"
        line(f"  {who}: {enabled}")
        if not user.sources:
            line("     ⚠️  все биржи выключены — этот пользователь лидов не получит")

    wanted = await db.sources_with_subscribers(settings.owner_id)
    line()
    line(f"Нужно опрашивать (объединение выбора): {', '.join(sorted(wanted)) or 'ничего'}")
    return wanted, True


# --- Шаг 2: глобальный рубильник ------------------------------------------


def _report_owner_switch(config: RuntimeConfigStore, wanted: set[str]) -> set[str]:
    rule("Рубильник владельца (settings.yaml)")

    cfg = config.current()
    if not cfg.enabled_sources:
        line("enabled_sources пуст — ничего не запрещено. Так и надо.")
        return {s.id for s in SOURCES}

    allowed = set(cfg.enabled_sources)
    line(f"enabled_sources: {', '.join(cfg.enabled_sources)}")
    blocked = wanted - allowed
    if blocked:
        line(f"⚠️  ЗАГЛУШЕНЫ, хотя пользователи их включили: {', '.join(sorted(blocked))}")
        line("    Исправить: enabled_sources: []  (биржи выбирают пользователи в боте)")
    return allowed


# --- Шаг 3: собирается ли парсер ------------------------------------------


def _report_parsers(wanted: set[str], settings, only: str, has_recipients: bool) -> dict:
    rule("Парсеры")

    active: dict = {}
    queue: asyncio.Queue = asyncio.Queue()
    for source in SOURCES:
        if only and source.id != only:
            continue

        if not source.available:
            line(f"{BAD} {source.id:<15} парсера нет — {source.note}")
            continue
        if source.id not in wanted:
            why = "выключена всеми" if has_recipients else "получателей нет"
            line(f"{OFF} {source.id:<15} {why} — запросов к сайту не будет")
            continue

        parser = build_one(source, queue, settings, None)
        if parser is None:
            need = f" (нужна переменная {source.needs} в .env)" if source.needs else ""
            line(f"{BAD} {source.id:<15} ВКЛЮЧЕНА, но парсер не собрался{need}")
            continue

        active[source.id] = parser
        line(f"{OK} {source.id:<15} {type(parser).__name__} — будет опрашиваться")

    if not active:
        line()
        line("Ни один парсер не запущен: лидов не будет ни у кого.")
    return active


# --- Шаг 4: что уже лежит в базе ------------------------------------------


async def _report_stored_leads(db: Database, settings) -> None:
    rule("Лиды в базе")

    fresh = await db.recent_orders(limit=500, max_age_hours=settings.max_lead_age_hours)
    stored = await db.recent_orders(limit=500)
    line(f"Со статусом new: всего {len(stored)}, из них свежих "
         f"(до {settings.max_lead_age_hours} ч) — {len(fresh)}")

    by_source: dict[str, int] = {}
    for row in stored:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    for source_id, count in sorted(by_source.items(), key=lambda item: -item[1]):
        label = (get_source(source_id) or source_id)
        name = getattr(label, "label", source_id)
        line(f"  {name:<24} {count}")

    if stored and not fresh:
        line()
        line("⚠️  Все лиды в базе устарели. Именно они и видны в «🔍 Проверить сейчас»,")
        line("    если не чистить базу. Новые появятся после успешного опроса бирж.")
    line()
    line("Важно: уже сохранённый лид повторно НЕ приходит (дедуп по source+external_id).")
    line("Для чистого теста базу нужно обнулить — см. README, «Чистый тестовый запуск».")


# --- Шаг 5: настоящий запрос к бирже --------------------------------------


async def _poll(active: dict, settings) -> None:
    rule("Реальный опрос (--poll)")

    if not active:
        line("Опрашивать нечего.")
        return

    for source_id, parser in active.items():
        line()
        line(f"→ {source_id}: {parser.page_url(1) if hasattr(parser, 'page_url') else '…'}")
        try:
            orders = await _fetch(parser)
        except Exception as exc:  # noqa: BLE001 — печатаем настоящую причину
            line(f"   ❌ {type(exc).__name__}: {exc}")
            continue

        fresh = [o for o in orders
                 if is_fresh(o, max_age_hours=settings.max_lead_age_hours)]
        dated = [o for o in orders if o.published_at is not None]
        line(f"   ✅ распознано заказов: {len(orders)}, свежих: {len(fresh)}, "
             f"с датой публикации: {len(dated)}/{len(orders)}")
        if orders and not fresh:
            oldest = min((age_hours(o) or 0) for o in dated) if dated else 0
            line(f"   ⚠️  все старше {settings.max_lead_age_hours} ч "
                 f"(самый свежий — {oldest:.0f} ч назад)")
        for order in fresh[:3]:
            budget = order.budget_raw or "бюджет не указан"
            line(f"      • {order.title[:60]} — {budget}")
        await _close(parser)


async def _fetch(parser):
    """Один запрос к бирже без публикации в очередь."""
    payload = await parser._fetcher.get_text(parser.page_url(1), label="check")
    return parser.extract(payload)


async def _close(parser) -> None:
    closer = getattr(parser, "aclose", None)
    if closer is not None:
        try:
            await closer()
        except Exception:  # noqa: BLE001 — диагностике не важно
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
