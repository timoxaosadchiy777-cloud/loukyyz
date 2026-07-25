"""ORM-модель доставки карточки в Telegram (антидубль сообщений)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.lead import Lead


class Delivery(Base, TimestampMixin):
    """Факт отправки заказа в конкретный чат. Уникальна по (lead_id, chat_id)."""

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("lead_id", "chat_id", name="uq_deliveries_lead_chat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # queued | sent | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="deliveries")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Delivery(id={self.id!r}, lead_id={self.lead_id!r}, chat_id={self.chat_id!r})"
