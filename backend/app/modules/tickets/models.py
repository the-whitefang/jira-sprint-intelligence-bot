"""SQLAlchemy models for tickets, ticket history, and ticket comments.

Corresponds to the ``tickets``, ``ticket_history``, and
``ticket_comments`` tables from the MySQL schema designed earlier.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Ticket(Base, TimestampMixin):
    """A synced Jira issue."""

    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_sprint_id_status", "sprint_id", "status"),
        Index("ix_tickets_assignee_jira_id", "assignee_jira_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sprint_id: Mapped[int] = mapped_column(
        ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False
    )
    jira_issue_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    assignee_jira_id: Mapped[str | None] = mapped_column(String(255))
    """Soft reference to a Jira account ID, not a foreign key. Jira's
    assignee set is a superset of this app's user accounts (someone can
    be assigned a ticket without ever logging into this tool), so this
    is resolved in the service layer rather than enforced at the DB
    level — matching the schema design's original note on this field."""
    story_points: Mapped[float | None] = mapped_column(Float)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Soft-delete marker. A ticket is never hard-deleted, since it may
    still be referenced by historical reports even after being removed
    from Jira — see `TicketRepository.soft_delete`."""

    sprint: Mapped["sprint"] = relationship(back_populates="tickets")  # noqa: F821
    history: Mapped[list[TicketHistory]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )
    comments: Mapped[list[TicketComment]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True
    )


class TicketHistory(Base):
    """One status/field transition for a ticket. Append-only, never updated."""

    __tablename__ = "ticket_history"
    __table_args__ = (Index("ix_ticket_history_ticket_id_changed_at", "ticket_id", "changed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    field_changed: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(255))
    new_value: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="history")


class TicketComment(Base):
    """A comment on a ticket — also the source text for ChromaDB embeddings."""

    __tablename__ = "ticket_comments"
    __table_args__ = (Index("ix_ticket_comments_pending_embedding", "pending_embedding"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pending_embedding: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    """Outbox-pattern flag consumed by the future embedding indexer worker
    — see the ChromaDB architecture design's note on keeping embedding
    generation out of the request path entirely."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
