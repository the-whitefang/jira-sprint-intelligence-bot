"""Jira integration facade.

:class:`JiraClient` is the single object the rest of the application
depends on — it composes the low-level HTTP client with each resource
client (projects/boards/sprints/issues/users) so callers write
``jira_client.sprints.get_sprint(123)`` rather than importing five
separate classes. This mirrors how most well-designed third-party SDKs
(e.g. ``stripe.Client().customers``) group operations by resource under
one entry point.
"""

from __future__ import annotations

from app.core.config import Settings
from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.jql.service import JQLService
from app.integrations.jira.resources.boards import JiraBoardsResource
from app.integrations.jira.resources.issues import JiraIssuesResource
from app.integrations.jira.resources.projects import JiraProjectsResource
from app.integrations.jira.resources.sprints import JiraSprintsResource
from app.integrations.jira.resources.users import JiraUsersResource


class JiraClient:
    """Single entry point for all Jira Cloud API access.

    Attributes:
        projects: Project read operations.
        boards: Agile board read operations.
        sprints: Sprint read operations.
        issues: Issue search and lookup operations.
        users: User lookup operations.
        jql: Structured JQL query generation and execution — the
            reusable filter-builder for issue search, distinct from
            ``issues`` (which covers direct JQL strings and per-sprint
            listing).
    """

    def __init__(self, settings: Settings) -> None:
        self._http = JiraHTTPClient(settings)
        self.projects = JiraProjectsResource(self._http)
        self.boards = JiraBoardsResource(self._http)
        self.sprints = JiraSprintsResource(self._http)
        self.issues = JiraIssuesResource(self._http, settings.JIRA_STORY_POINTS_FIELD)
        self.users = JiraUsersResource(self._http)
        self.jql = JQLService(self._http, settings.JIRA_STORY_POINTS_FIELD)

    async def test_connection(self) -> bool:
        """Verify Jira credentials and connectivity.

        See :meth:`JiraHTTPClient.test_connection` for details.
        """
        return await self._http.test_connection()

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool. Call once, on app shutdown."""
        await self._http.aclose()

    async def __aenter__(self) -> JiraClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()