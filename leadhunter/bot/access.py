"""Проверка доступа к боту.

Три уровня:
  * **dev-режим** (``OWNER_ID`` не задан, == 0) — доступ у всех, как и раньше.
    Так бот остаётся запускаемым «из коробки» без настройки.
  * **администратор** (``OWNER_ID``) — полный доступ всегда, в таблице ``users``
    не нуждается: его нельзя случайно отозвать через /revoke.
  * **пользователь** — доступ есть, если ``users.paid_status = 1``.
"""

from __future__ import annotations

from database.db import Database


class AccessControl:
    """Единственная точка принятия решения «пускать ли этого пользователя»."""

    def __init__(self, db: Database, owner_id: int) -> None:
        self._db = db
        self._owner_id = owner_id

    @property
    def owner_id(self) -> int:
        return self._owner_id

    @property
    def dev_mode(self) -> bool:
        """OWNER_ID не настроен — ограничений нет (поведение до мультиюзера)."""
        return self._owner_id == 0

    def is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return self.dev_mode or user_id == self._owner_id

    async def has_access(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if self.is_admin(user_id):
            return True
        return await self._db.has_paid_access(user_id)
