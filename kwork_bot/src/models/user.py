"""ORM-модель пользователя (владельца/покупателя лицензии)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.license import License


class User(Base, TimestampMixin):
    """Пользователь Telegram, к которому привязана лицензия."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)

    licenses: Mapped[list["License"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"User(id={self.id!r}, telegram_id={self.telegram_id!r}, role={self.role!r})"
