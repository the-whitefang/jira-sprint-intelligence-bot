"""Repositories for tickets, ticket history, and ticket comments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tickets.models import Ticket, TicketComment, TicketHistory
from app.shared.base_repository import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    """Data access for tickets."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Ticket)

    async def get_by_jira_key(self, jira_issue_key: str) -> Ticket | None:
        """Fetch a ticket by its Jira issue key — the sync worker's upsert lookup."""
        stmt = select(Ticket).where(Ticket.jira_issue_key == jira_issue_key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_sprint(self, sprint_id: int, *, status: str | None = None) -> list[Ticket]:
        """List a sprint's tickets, optionally filtered by status.

        Excludes soft-deleted tickets by default, matching the soft-delete
        convention from the schema design — code that specifically needs
        deleted rows (e.g. an audit view) should query ``Ticket`` directly
        rather than through this method.
        """
        stmt = select(Ticket).where(Ticket.sprint_id == sprint_id, Ticket.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Ticket.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def soft_delete(self, ticket: Ticket) -> Ticket:
        """Mark a ticket deleted without removing the row.

        Preserves foreign key integrity with ``ticket_history`` and
        ``ticket_comments``, and keeps the ticket available for
        historical/retrospective reporting even after it's gone from Jira.
        """
        return await self.update(ticket, deleted_at=datetime.now(timezone.utc))


class TicketHistoryRepository(BaseRepository[TicketHistory]):
    """Data access for ticket status-transition history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TicketHistory)

    async def list_for_ticket(self, ticket_id: int) -> list[TicketHistory]:
        """List a ticket's full transition history, oldest first — the cycle-time query path."""
        stmt = (
            select(TicketHistory)
            .where(TicketHistory.ticket_id == ticket_id)
            .order_by(TicketHistory.changed_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class TicketCommentRepository(BaseRepository[TicketComment]):
    """Data access for ticket comments."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TicketComment)

    async def list_pending_embedding(self, *, limit: int = 100) -> list[TicketComment]:
        """List comments awaiting ChromaDB indexing.

        The embedding indexer worker's poll query, per the ChromaDB
        architecture design's outbox pattern.
        """
        stmt = (
            select(TicketComment).where(TicketComment.pending_embedding.is_(True)).limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
