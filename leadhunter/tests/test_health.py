"""Тесты сигнала живости и ротации логов."""

from __future__ import annotations

import logging
import time

from core.health import STALE_FACTOR, Heartbeat, is_alive
from core.logging import setup_logging


def test_beat_creates_fresh_marker(tmp_path) -> None:
    beat = Heartbeat(tmp_path / "health", interval=30)
    beat.beat()

    alive, reason = is_alive(beat.path, beat.interval)
    assert alive is True
    assert reason == ""


def test_missing_file_is_not_alive(tmp_path) -> None:
    alive, reason = is_alive(tmp_path / "нет-такого", 30)
    assert alive is False
    assert "не стартовал" in reason


def test_stale_marker_is_not_alive(tmp_path) -> None:
    """Главный сценарий: процесс жив, но event loop встал."""
    path = tmp_path / "health"
    interval = 10
    path.write_text(str(int(time.time()) - interval * STALE_FACTOR - 5), encoding="utf-8")

    alive, reason = is_alive(path, interval)
    assert alive is False
    assert "завис" in reason


def test_garbage_marker_is_not_alive(tmp_path) -> None:
    path = tmp_path / "health"
    path.write_text("не число", encoding="utf-8")
    assert is_alive(path, 30)[0] is False


def test_beat_creates_missing_directory(tmp_path) -> None:
    beat = Heartbeat(tmp_path / "нет" / "каталога" / "health", interval=30)
    beat.beat()
    assert is_alive(beat.path, 30)[0] is True


def test_beat_does_not_raise_on_bad_path(tmp_path) -> None:
    """Сбой записи маркера не должен ронять бота."""
    blocker = tmp_path / "файл"
    blocker.write_text("x", encoding="utf-8")
    Heartbeat(blocker / "health", interval=30).beat()  # каталог = файл


def test_interval_has_lower_bound(tmp_path) -> None:
    assert Heartbeat(tmp_path / "h", interval=1).interval == 5


def test_log_rotation_configured(tmp_path) -> None:
    log_file = tmp_path / "logs" / "app.log"
    setup_logging("INFO", log_file=log_file, max_bytes=1024, backups=2)
    logging.getLogger("тест").info("строка")

    assert log_file.exists()
    handlers = logging.getLogger().handlers
    assert any(getattr(h, "maxBytes", 0) == 1024 for h in handlers)
    setup_logging("INFO")  # возвращаем консольную конфигурацию


def test_repeat_setup_does_not_duplicate_handlers() -> None:
    setup_logging("INFO")
    first = len(logging.getLogger().handlers)
    setup_logging("INFO")
    assert len(logging.getLogger().handlers) == first


def test_unwritable_log_file_falls_back_to_stdout(tmp_path) -> None:
    """Нет прав на каталог логов — не повод не запускаться."""
    blocker = tmp_path / "файл"
    blocker.write_text("x", encoding="utf-8")
    setup_logging("INFO", log_file=blocker / "app.log")
    assert logging.getLogger().handlers  # консольный хендлер на месте
    setup_logging("INFO")


# --- Производительность и память ------------------------------------------


async def test_recipients_load_in_single_query(tmp_path) -> None:
    """Раньше было 1+N запросов НА КАЖДЫЙ лид — при 50 юзерах это тысячи."""
    from core.user_settings import UserSettings
    from database.db import Database

    db = Database(str(tmp_path / "r.db"))
    await db.connect()
    try:
        for uid in (201, 202, 203):
            await db.set_paid_status(uid, True)
        await db.save_user_settings(202, UserSettings(min_budget=300, onboarded=True))

        recipients = await db.list_recipients(owner_id=100)
        assert [uid for uid, _ in recipients] == [100, 201, 202, 203]
        by_id = dict(recipients)
        assert by_id[202].min_budget == 300
        assert by_id[201] == UserSettings()  # LEFT JOIN без настроек
    finally:
        await db.close()


async def test_owner_not_duplicated_in_recipients(tmp_path) -> None:
    from database.db import Database

    db = Database(str(tmp_path / "r2.db"))
    await db.connect()
    try:
        await db.set_paid_status(100, True)
        recipients = await db.list_recipients(owner_id=100)
        assert [uid for uid, _ in recipients] == [100]
    finally:
        await db.close()


async def test_wal_mode_enabled(tmp_path) -> None:
    """Без WAL нажатие кнопки могло словить «database is locked»."""
    from database.db import Database

    db = Database(str(tmp_path / "w.db"))
    await db.connect()
    try:
        cur = await db._connection.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0].lower() == "wal"
    finally:
        await db.close()


async def test_seen_set_is_bounded() -> None:
    """Множество виденных лидов росло вечно — утечка при аптайме в месяцы."""
    import asyncio

    from core.models import Order
    from parsers.base import SEEN_LIMIT, BaseParser

    class _P(BaseParser):
        name = "t"

        async def run(self) -> None:
            pass

    queue: asyncio.Queue = asyncio.Queue()
    parser = _P(queue)
    for i in range(SEEN_LIMIT + 200):
        await parser.emit(
            Order(source="s", external_id=str(i), title="t", url="u", description="d")
        )
        queue.get_nowait()

    assert len(parser._seen) == SEEN_LIMIT
    # Свежий ключ всё ещё отсекается — окно работает как надо.
    repeat = Order(
        source="s", external_id=str(SEEN_LIMIT + 199), title="t", url="u", description="d"
    )
    assert await parser.emit(repeat) is False
