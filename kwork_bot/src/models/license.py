"""ORM-модель лицензии (локальный кэш криптографически проверенной лицензии)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.user import User


class License(Base, TimestampMixin):
    """Кэш последней успешно проверенной лицензии с TTL.

    Подпись (`signature`) валидируется по публичному ключу Ed25519 в слое security;
    здесь хранится результат проверки и метаданные для оффлайн-режима в пределах TTL.
    """

    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    license_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # base64 Ed25519
    machine_fingerprint: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="licenses")

    def __repr__(self) -> str:  # pragma: no cover
        return f"License(id={self.id!r}, key={self.license_key!r}, revoked={self.revoked!r})"
