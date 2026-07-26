"""Загрузка профиля исполнителя (`profile.md`) с горячей перезагрузкой.

Один общий загрузчик используют и скоринг (:mod:`ai.scoring`), и генератор
откликов (:mod:`ai.responder`), поэтому правка `profile.md` на ходу мгновенно
влияет и на оценку заказов, и на текст откликов — без перезапуска.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class ProfileLoader:
    """Ленивое чтение `profile.md` с перезагрузкой по mtime."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cache = ""
        self._mtime: float | None = None
        self._warned_missing = False

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> str:
        """Возвращает актуальный текст профиля (или пустую строку, если файла нет)."""
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            if not self._warned_missing:
                log.warning("Файл профиля не найден: %s — работаю без профиля", self._path)
                self._warned_missing = True
            return self._cache

        if mtime != self._mtime:
            try:
                self._cache = self._path.read_text(encoding="utf-8").strip()
                self._mtime = mtime
                self._warned_missing = False
                log.info("Профиль загружен: %s (%s символов)", self._path, len(self._cache))
            except OSError as exc:
                log.warning("Не удалось прочитать профиль %s: %s", self._path, exc)
        return self._cache
