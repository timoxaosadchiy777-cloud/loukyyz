"""Общие фикстуры тестов kwork_bot."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from database.session import Database


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    """Изолированная файловая SQLite-БД на тест (со схемой)."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="kwork_test_"))
    db_path = tmp_dir / "test.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}", sqlite_path=db_path)
    await db.create_all()
    try:
        yield db
    finally:
        await db.dispose()
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{db_path}{suffix}")
            if candidate.exists():
                candidate.unlink()
