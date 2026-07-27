"""Супервизор парсеров: биржи опрашиваются ровно те, что выбрали пользователи.

Главное требование, которое здесь проверяется: **выключенная биржа не
опрашивается**. Никаких запросов к сайту, а не «запросы есть, лиды выбрасываем».
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from database.db import Database
from parsers.supervisor import SourceSupervisor
from tests.helpers import USER

OWNER = 100
OTHER = 501


class _Settings:
    """Владельца по умолчанию нет: иначе он сам был бы получателем и его
    дефолтные биржи запускали бы всё независимо от выбора пользователей."""

    def __init__(self, owner_id: int = 0) -> None:
        self.owner_id = owner_id


class _FakeParser:
    """Парсер-пустышка: считает опросы и запуски, в сеть не ходит."""

    def __init__(self, source_id: str) -> None:
        self.name = source_id
        self.runs = 0
        self.polls = 0
        self.closed = False
        self.started = asyncio.Event()

    async def run_safe(self) -> None:
        self.runs += 1
        self.started.set()
        # Настоящий run_safe не возвращает управление — только отмена.
        await asyncio.Event().wait()

    async def poll_once(self) -> int:
        self.polls += 1
        return 7

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def built(monkeypatch) -> dict[str, _FakeParser]:
    """Подменяет сборку парсеров: реестр настоящий, парсеры — пустышки."""
    made: dict[str, _FakeParser] = {}

    def _build_one(source, queue, settings, alerter):
        parser = _FakeParser(source.id)
        made[source.id] = parser
        return parser

    monkeypatch.setattr("parsers.supervisor.build_one", _build_one)
    return made


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "sup.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


def _supervisor(db, *, owner_id: int = 0, **kwargs) -> SourceSupervisor:
    return SourceSupervisor(asyncio.Queue(), _Settings(owner_id), db, **kwargs)


# --- Состав парсеров ------------------------------------------------------


async def test_nothing_runs_without_users(db, built) -> None:
    """Никого нет — ни одного запроса к биржам."""
    supervisor = _supervisor(db)
    started, stopped = await supervisor.reconcile()

    assert started == set()
    assert supervisor.active == set()
    assert built == {}


async def test_defaults_start_for_paid_user(db, built) -> None:
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    started, _ = await supervisor.reconcile()

    # Ровно умолчания реестра: WeWorkRemotely выключен, Fiverr вне игры.
    assert "kwork" in started and "freelancer" in started
    assert "weworkremotely" not in supervisor.active
    assert "fiverr" not in supervisor.active
    await supervisor.aclose()


async def test_disabled_source_is_not_polled(db, built) -> None:
    """Выключил единственный пользователь — парсер не стартует вовсе."""
    await db.set_paid_status(USER, True)
    await db.set_source_enabled(USER, "guru", False)

    supervisor = _supervisor(db)
    await supervisor.reconcile()

    assert "guru" not in supervisor.active
    assert "guru" not in built  # парсер даже не создавался
    await supervisor.aclose()


async def test_enabling_source_starts_parser_without_restart(db, built) -> None:
    await db.set_paid_status(USER, True)
    await db.set_source_enabled(USER, "weworkremotely", False)
    supervisor = _supervisor(db)
    await supervisor.reconcile()
    assert "weworkremotely" not in supervisor.active

    await db.set_source_enabled(USER, "weworkremotely", True)
    started, _ = await supervisor.reconcile()

    assert started == {"weworkremotely"}
    assert "weworkremotely" in supervisor.active
    await supervisor.aclose()


async def test_last_user_off_stops_the_parser(db, built) -> None:
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()
    parser = built["guru"]
    await asyncio.wait_for(parser.started.wait(), timeout=1)

    await db.set_source_enabled(USER, "guru", False)
    _, stopped = await supervisor.reconcile()

    assert stopped == {"guru"}
    assert "guru" not in supervisor.active
    assert parser.closed is True  # сокеты закрыты, опроса больше нет
    await supervisor.aclose()


async def test_parser_survives_while_someone_needs_it(db, built) -> None:
    """Один выключил, другой оставил — биржа продолжает опрашиваться."""
    await db.set_paid_status(USER, True)
    await db.set_paid_status(OTHER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()

    await db.set_source_enabled(USER, "guru", False)
    _, stopped = await supervisor.reconcile()

    assert stopped == set()
    assert "guru" in supervisor.active
    await supervisor.aclose()


async def test_reconcile_is_idempotent(db, built) -> None:
    """Повторная сверка не перезапускает уже работающие парсеры."""
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()
    parser = built["kwork"]

    started, stopped = await supervisor.reconcile()

    assert (started, stopped) == (set(), set())
    assert built["kwork"] is parser
    await supervisor.aclose()


async def test_unconfigured_source_is_not_retried_every_minute(db, monkeypatch) -> None:
    """Нет ключа — причина сама не рассосётся: не дёргаем фабрику каждую сверку."""
    attempts: list[str] = []

    def _build_one(source, queue, settings, alerter):
        attempts.append(source.id)
        return None if source.id == "guru" else _FakeParser(source.id)

    monkeypatch.setattr("parsers.supervisor.build_one", _build_one)
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)

    for _ in range(3):
        await supervisor.reconcile()

    assert attempts.count("guru") == 1
    assert "guru" not in supervisor.active
    await supervisor.aclose()


async def test_retoggling_retries_a_broken_source(db, monkeypatch) -> None:
    """Владелец дописал ключ — переключение биржи даёт парсеру второй шанс."""
    attempts: list[str] = []
    broken = True

    def _build_one(source, queue, settings, alerter):
        attempts.append(source.id)
        if source.id == "guru" and broken:
            return None
        return _FakeParser(source.id)

    monkeypatch.setattr("parsers.supervisor.build_one", _build_one)
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()

    broken = False
    await db.set_source_enabled(USER, "guru", False)
    await supervisor.reconcile()
    await db.set_source_enabled(USER, "guru", True)
    await supervisor.reconcile()

    assert "guru" in supervisor.active
    await supervisor.aclose()


async def test_owner_alone_gets_parsers(db, built) -> None:
    """Владелец — получатель даже без записи в users, биржи для него работают."""
    supervisor = _supervisor(db, owner_id=OWNER)
    await supervisor.reconcile()

    assert "freelancer" in supervisor.active
    await supervisor.aclose()


# --- Глобальный рубильник владельца ---------------------------------------


async def test_settings_yaml_can_block_a_source(db, built, tmp_path) -> None:
    await db.set_paid_status(USER, True)
    path = tmp_path / "settings.yaml"
    path.write_text("enabled_sources: [kwork]\n", encoding="utf-8")
    config = RuntimeConfigStore(path, defaults=RuntimeConfig())

    supervisor = _supervisor(db, config=config)
    await supervisor.reconcile()

    assert supervisor.active == {"kwork"}
    # Запрет должен быть виден в интерфейсе, а не молчаливым.
    assert "freelancer" in supervisor.blocked
    await supervisor.aclose()


async def test_empty_settings_yaml_blocks_nothing(db, built, tmp_path) -> None:
    await db.set_paid_status(USER, True)
    config = RuntimeConfigStore(tmp_path / "settings.yaml", defaults=RuntimeConfig())

    supervisor = _supervisor(db, config=config)
    await supervisor.reconcile()

    assert supervisor.blocked == set()
    assert "freelancer" in supervisor.active
    await supervisor.aclose()


# --- «Проверить сейчас» ---------------------------------------------------


async def test_poll_now_runs_one_source(db, built) -> None:
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()

    found = await supervisor.poll_now("guru")

    assert found == 7
    assert built["guru"].polls == 1
    assert built["kwork"].polls == 0  # соседей не трогаем
    await supervisor.aclose()


async def test_poll_now_on_stopped_source_returns_none(db, built) -> None:
    supervisor = _supervisor(db)
    assert await supervisor.poll_now("guru") is None


async def test_aclose_stops_everything(db, built) -> None:
    await db.set_paid_status(USER, True)
    supervisor = _supervisor(db)
    await supervisor.reconcile()

    await supervisor.aclose()

    assert supervisor.active == set()
    assert all(parser.closed for parser in built.values())
