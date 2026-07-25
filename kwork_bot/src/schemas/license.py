"""Pydantic-схемы лицензии.

Лицензия — это подписанный Ed25519 токен вида `<payload_b64>.<signature_b64>`,
где payload — JSON с полями ниже. Схемы описывают декодированную полезную нагрузку
и результат проверки.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LicensePayload(BaseModel):
    """Полезная нагрузка лицензии (то, что подписано ключом издателя)."""

    model_config = ConfigDict(extra="ignore")

    license_key: str = Field(min_length=1, max_length=256)
    machine_fingerprint: str = ""
    issued_at: datetime | None = None
    expires_at: datetime | None = None


class LicenseStatus(BaseModel):
    """Результат проверки лицензии."""

    valid: bool
    reason: str = ""
    license_key: str = ""
    expires_at: datetime | None = None
    offline_cached: bool = False
