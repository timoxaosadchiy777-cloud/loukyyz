"""Проверка коммерческой лицензии (Ed25519) с TTL-кэшем и привязкой к машине.

Модель доверия:
- Право на запуск даёт ТОЛЬКО криптографическая проверка подписанного токена из
  окружения (`LICENSE_KEY`) по публичному ключу издателя (`LICENSE_PUBLIC_KEY`).
- Локальная БД используется лишь как аудит/кэш метаданных. Подмена строк в БД не
  может выдать или продлить доступ: решение о валидности принимается по подписи,
  а не по колонкам `revoked`/`expires_at` в таблице. Подделать подпись без
  приватного ключа издателя нельзя.
- TTL-кэш в памяти избавляет от повторной проверки на каждой операции.

Формат токена: ``<payload_b64url>.<signature_b64url>`` — подпись покрывает строку
``payload_b64url``. Payload — JSON, соответствующий `schemas.license.LicensePayload`.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import uuid
from datetime import datetime, timezone

from config.settings import Settings
from schemas.license import LicensePayload, LicenseStatus
from security.cache import TTLCache
from security.signature import b64decode, b64encode, sign_ed25519, verify_ed25519

log = logging.getLogger(__name__)

_CACHE_KEY = "license"


def machine_fingerprint() -> str:
    """Стабильный отпечаток машины (MAC + имя хоста → sha256, 32 hex-символа)."""
    raw = f"{uuid.getnode()}::{platform.node()}::{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def issue_license(private_key_b64: str, payload: LicensePayload) -> str:
    """Выпускает подписанный токен лицензии (для тулинга/тестов издателя)."""
    payload_b64 = b64encode(payload.model_dump_json().encode("utf-8"))
    signature_b64 = sign_ed25519(private_key_b64, payload_b64.encode("ascii"))
    return f"{payload_b64}.{signature_b64}"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class LicenseVerifier:
    """Проверяет лицензию из настроек; кэширует результат на TTL."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: TTLCache[LicenseStatus] = TTLCache(ttl=float(settings.license_cache_ttl))
        self._last_token: str | None = None

    def verify(self) -> LicenseStatus:
        """Проверяет лицензию. Возвращает `LicenseStatus` (не бросает исключений)."""
        token = self._settings.license_key.strip()

        if not self._settings.license_configured:
            return LicenseStatus(valid=False, reason="Лицензия не настроена (LICENSE_KEY / LICENSE_PUBLIC_KEY).")

        # TTL-кэш: возвращаем закэшированный результат, если токен не менялся.
        if token == self._last_token:
            cached = self._cache.get(_CACHE_KEY)
            if cached is not None:
                return cached.model_copy(update={"offline_cached": True})

        status = self._verify_token(token)
        self._last_token = token
        if status.valid:
            self._cache.set(_CACHE_KEY, status)
        else:
            self._cache.invalidate(_CACHE_KEY)
        return status

    def _verify_token(self, token: str) -> LicenseStatus:
        parts = token.split(".")
        if len(parts) != 2 or not all(parts):
            return LicenseStatus(valid=False, reason="Неверный формат токена лицензии.")
        payload_b64, signature_b64 = parts

        if not verify_ed25519(self._settings.license_public_key, payload_b64.encode("ascii"), signature_b64):
            return LicenseStatus(valid=False, reason="Подпись лицензии недействительна.")

        try:
            payload_json = b64decode(payload_b64).decode("utf-8")
            payload = LicensePayload.model_validate_json(payload_json)
        except (ValueError, TypeError) as exc:
            return LicenseStatus(valid=False, reason=f"Не удалось разобрать лицензию: {exc}")

        now = datetime.now(timezone.utc)
        if payload.expires_at is not None and _as_utc(payload.expires_at) <= now:
            return LicenseStatus(
                valid=False,
                reason="Срок действия лицензии истёк.",
                license_key=payload.license_key,
                expires_at=payload.expires_at,
            )

        if payload.machine_fingerprint and payload.machine_fingerprint != machine_fingerprint():
            return LicenseStatus(
                valid=False,
                reason="Лицензия привязана к другой машине.",
                license_key=payload.license_key,
            )

        return LicenseStatus(
            valid=True,
            reason="OK",
            license_key=payload.license_key,
            expires_at=payload.expires_at,
        )

    @property
    def payload_signature(self) -> tuple[LicensePayload, str] | None:
        """Разбирает токен на (payload, signature) без проверки срока — для кэша в БД."""
        token = self._settings.license_key.strip()
        parts = token.split(".")
        if len(parts) != 2 or not all(parts):
            return None
        try:
            payload = LicensePayload.model_validate_json(b64decode(parts[0]).decode("utf-8"))
        except (ValueError, TypeError):
            return None
        return payload, parts[1]
