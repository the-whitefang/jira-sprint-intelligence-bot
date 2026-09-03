"""Jira Users resource client.

Wraps user lookup — used to resolve `assignee` account IDs seen on issues
into full user records (display name, email) when needed.
"""

from __future__ import annotations

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.schemas import JiraUser


class JiraUsersResource:
    """Read access to Jira users."""

    def __init__(self, http: JiraHTTPClient) -> None:
        self._http = http

    async def get_user(self, account_id: str) -> JiraUser:
        """Fetch a single user by their Jira account ID.

        Raises:
            JiraNotFoundError: No user exists with that account ID.
        """
        raw = await self._http.request(
            "GET", "/rest/api/3/user", params={"accountId": account_id}
        )
        return JiraUser.model_validate(raw)

    async def search_users(self, query: str) -> list[JiraUser]:
        """Search users by display name or email fragment.

        Args:
            query: A partial name or email to match.

        Returns:
            Matching users. This endpoint is not paginated by Jira the
            same way list endpoints are (it returns a plain array capped
            at a server-side limit), so no ``paginate()`` call is used
            here.
        """
        raw = await self._http.request(
            "GET", "/rest/api/3/user/search", params={"query": query}
        )
        return [JiraUser.model_validate(item) for item in (raw or [])]
