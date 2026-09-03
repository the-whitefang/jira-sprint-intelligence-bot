"""Jira Projects resource client.

Wraps the core API's project endpoints. One narrow class per resource
(Interface Segregation) — callers that only need projects depend on this,
not a monolithic client with every Jira operation on one object.
"""

from __future__ import annotations

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.schemas import JiraProject


class JiraProjectsResource:
    """Read access to Jira projects."""

    def __init__(self, http: JiraHTTPClient) -> None:
        self._http = http

    async def list_projects(self) -> list[JiraProject]:
        """List every project visible to the configured Jira account.

        Returns:
            All projects, fully paginated.
        """
        projects: list[JiraProject] = []
        async for raw in self._http.paginate(
            "GET", "/rest/api/3/project/search", values_key="values"
        ):
            projects.append(JiraProject.model_validate(raw))
        return projects

    async def get_project(self, project_key: str) -> JiraProject:
        """Fetch a single project by its Jira key (e.g. ``"ENG"``).

        Raises:
            JiraNotFoundError: No project exists with that key.
        """
        raw = await self._http.request("GET", f"/rest/api/3/project/{project_key}")
        return JiraProject.model_validate(raw)
