"""ORM-модель заказа (Lead)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.delivery import Delivery


class Lead(Base, TimestampMixin):
    """Заказ с биржи: уникален по паре (source, external_id)."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_leads_source_external"),
        Index("ix_leads_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    budget_raw: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    budget_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    # new | sent | accepted | skipped | filtered
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
    )

    @property
    def dedup_key(self) -> str:
        return f"{self.source}:{self.external_id}"

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"Lead(id={self.id!r}, source={self.source!r}, external_id={self.external_id!r})"
