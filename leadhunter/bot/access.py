"""Проверка доступа к боту.

Уровни:
  * **администратор** (``OWNER_ID``) — полный доступ всегда, в таблице ``users``
    не нуждается: его нельзя случайно отозвать через /revoke.
  * **пользователь** — доступ есть, если ``users.paid_status = 1``.
  * **dev-режим** (``DEV_MODE=true``) — доступ у всех. Только для локальной
    отладки.

Раньше отсутствие ``OWNER_ID`` само по себе включало «пускаем всех», и любой
пользователь Telegram становился администратором: мог выдать себе доступ,
посмотреть список пользователей и статистику. Забытая строка в ``.env`` не
должна открывать админку посторонним, поэтому dev-режим теперь включается
только явным флагом, а ненастроенный бот не пускает никого.
"""

from __future__ import annotations

import logging

from database.db import Database

log = logging.getLogger(__name__)


class AccessControl:
    """Единственная точка принятия решения «пускать ли этого пользователя»."""

    def __init__(self, db: Database, owner_id: int, dev_mode: bool = False) -> None:
        self._db = db
        self._owner_id = owner_id
        self._dev_mode = dev_mode

        if dev_mode:
            log.warning(
                "DEV_MODE=true — доступ открыт ВСЕМ. В production так быть не должно."
            )
        elif not owner_id:
            log.error(
                "OWNER_ID не задан и DEV_MODE выключен — бот никого не пустит. "
                "Впишите свой Telegram ID в .env (узнать: @userinfobot)."
            )

    @property
    def owner_id(self) -> int:
        return self._owner_id

    @property
    def dev_mode(self) -> bool:
        """Доступ открыт всем — только по явному ``DEV_MODE=true``."""
        return self._dev_mode

    @property
    def configured(self) -> bool:
        """Настроен ли бот: есть администратор либо осознанный dev-режим."""
        return bool(self._owner_id) or self._dev_mode

    def is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if self._owner_id:
            return user_id == self._owner_id
        # Админа нет вовсе: dev-режим даёт доступ к боту, но не к админке.
        return False

    async def has_access(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if self._dev_mode or self.is_admin(user_id):
            return True
        return await self._db.has_paid_access(user_id)
