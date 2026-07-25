"""Репозиторий лицензий: кэш проверенной лицензии с временем последней проверки."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from database.repositories.base import BaseRepository
from models.license import License
from schemas.license import LicensePayload


class LicenseRepository(BaseRepository[License]):
    """Доступ к таблице `licenses` (локальный кэш верификации)."""

    model = License

    async def get_by_key(self, license_key: str) -> License | None:
        result = await self._session.execute(
            select(License).where(License.license_key == license_key)
        )
        return result.scalar_one_or_none()

    async def upsert_verified(
        self,
        payload: LicensePayload,
        signature: str,
        *,
        user_id: int | None = None,
    ) -> License:
        """Создаёт или обновляет кэш успешно проверенной лицензии."""
        now = datetime.now(timezone.utc)
        license_obj = await self.get_by_key(payload.license_key)
        if license_obj is None:
            license_obj = License(license_key=payload.license_key, signature=signature)
            self._session.add(license_obj)

        license_obj.signature = signature
        license_obj.machine_fingerprint = payload.machine_fingerprint
        license_obj.issued_at = payload.issued_at
        license_obj.expires_at = payload.expires_at
        license_obj.revoked = False
        license_obj.last_checked_at = now
        if user_id is not None:
            license_obj.user_id = user_id

        await self._session.flush()
        return license_obj

    async def mark_revoked(self, license_key: str) -> None:
        license_obj = await self.get_by_key(license_key)
        if license_obj is not None:
            license_obj.revoked = True
            license_obj.last_checked_at = datetime.now(timezone.utc)
            await self._session.flush()
