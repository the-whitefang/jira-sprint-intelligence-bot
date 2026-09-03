"""Jira Boards resource client.

Wraps the Agile API's board endpoints.
"""

from __future__ import annotations

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.schemas import JiraBoard


class JiraBoardsResource:
    """Read access to Jira Agile boards."""

    def __init__(self, http: JiraHTTPClient) -> None:
        self._http = http

    async def list_boards(self, project_key_or_id: str | None = None) -> list[JiraBoard]:
        """List boards, optionally scoped to a single project.

        Args:
            project_key_or_id: If given, only boards belonging to this
                project are returned; if omitted, every board visible to
                the configured account is returned.
        """
        params = {"projectKeyOrId": project_key_or_id} if project_key_or_id else None
        boards: list[JiraBoard] = []
        async for raw in self._http.paginate(
            "GET", "/rest/agile/1.0/board", params=params, values_key="values"
        ):
            boards.append(JiraBoard.model_validate(raw))
        return boards

    async def get_board(self, board_id: int) -> JiraBoard:
        """Fetch a single board by its numeric ID.

        Raises:
            JiraNotFoundError: No board exists with that ID.
        """
        raw = await self._http.request("GET", f"/rest/agile/1.0/board/{board_id}")
        return JiraBoard.model_validate(raw)
