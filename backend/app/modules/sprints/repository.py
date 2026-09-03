"""Repositories for projects and sprints."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sprints.models import Project, Sprint
from app.shared.base_repository import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Data access for projects."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_by_jira_key(self, jira_project_key: str) -> Project | None:
        """Fetch a project by its natural Jira key (e.g. ``"ENG"``).

        The lookup the sync worker uses to decide insert-vs-update for
        each project it pulls from Jira.
        """
        stmt = select(Project).where(Project.jira_project_key == jira_project_key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class SprintRepository(BaseRepository[Sprint]):
    """Data access for sprints."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Sprint)

    async def get_by_jira_sprint_id(self, jira_sprint_id: str) -> Sprint | None:
        """Fetch a sprint by its Jira sprint ID — the sync worker's upsert lookup."""
        stmt = select(Sprint).where(Sprint.jira_sprint_id == jira_sprint_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_project(self, project_id: int) -> list[Sprint]:
        """List a project's currently active sprints — the dashboard's hot path."""
        stmt = select(Sprint).where(Sprint.project_id == project_id, Sprint.status == "active")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
