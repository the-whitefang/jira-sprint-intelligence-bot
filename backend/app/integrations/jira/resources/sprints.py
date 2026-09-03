"""Jira Sprints resource client.

Wraps the Agile API's sprint endpoints.
"""

from __future__ import annotations

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.schemas import JiraSprint


class JiraSprintsResource:
    """Read access to sprints belonging to a board."""

    def __init__(self, http: JiraHTTPClient) -> None:
        self._http = http

    async def list_sprints(self, board_id: int, state: str | None = None) -> list[JiraSprint]:
        """List sprints on a board, optionally filtered by state.

        Args:
            board_id: The Agile board's numeric ID.
            state: Optional Jira sprint state filter — one of
                ``"active"``, ``"future"``, ``"closed"``. Omit for all
                states.
        """
        params = {"state": state} if state else None
        sprints: list[JiraSprint] = []
        async for raw in self._http.paginate(
            "GET",
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params=params,
            values_key="values",
        ):
            sprints.append(JiraSprint.model_validate(raw))
        return sprints

    async def get_sprint(self, sprint_id: int) -> JiraSprint:
        """Fetch a single sprint by its numeric ID.

        Raises:
            JiraNotFoundError: No sprint exists with that ID.
        """
        raw = await self._http.request("GET", f"/rest/agile/1.0/sprint/{sprint_id}")
        return JiraSprint.model_validate(raw)
