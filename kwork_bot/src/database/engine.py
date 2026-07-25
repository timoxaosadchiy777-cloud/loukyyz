"""Создание async-движка SQLAlchemy для SQLite в режиме WAL."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def build_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Строит async-движок и включает нужные PRAGMA для SQLite при каждом коннекте."""
    engine = create_async_engine(url, echo=echo, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine
