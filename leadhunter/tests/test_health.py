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
