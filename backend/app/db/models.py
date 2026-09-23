from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="processing")
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Figures lifted verbatim from the document during structured extraction.
    # All nullable: they are only populated for the document type they belong
    # to (room_rent_per_day for bills, the settlement_total_* trio for
    # settlement letters), and only when the extractor actually found them.
    # The reconciliation engine prefers these over its own reconstructions and
    # falls back to heuristics when they are None.
    room_rent_per_day: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    settlement_total_claimed: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    settlement_total_approved: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    settlement_total_deducted: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(nullable=False)
    contextual_text: Mapped[str] = mapped_column(nullable=False)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    claimed_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    approved_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deducted_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deduction_reason: Mapped[str | None] = mapped_column(nullable=True)


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    sum_insured: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    room_rent_limit_per_day: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    room_rent_limit_type: Mapped[str] = mapped_column(nullable=False)
    co_pay_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    sub_limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    citations: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
