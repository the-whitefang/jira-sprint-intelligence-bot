"""JQL generation and execution service.

:class:`JQLService` is the single reusable entry point for querying Jira
issues by structured criteria — every future consumer (the sync worker,
the sprints/tickets modules, an ad-hoc admin query endpoint) should go
through this rather than hand-building JQL or calling the search API
directly, so filtering/pagination/sorting behavior stays consistent
everywhere it's used.

It deliberately depends on :class:`JiraHTTPClient` directly rather than
on :class:`~app.integrations.jira.resources.issues.JiraIssuesResource`:
the issues resource is built for "fetch everything matching this JQL,"
while this service also needs single-page fetches with pagination
metadata (:meth:`search`) — a different contract that would have forced
either duplicating pagination logic or overloading the resource client
with a second, differently-shaped method. Talking to the HTTP client
directly keeps both call sites simple.
"""

from __future__ import annotations

from typing import Any

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.jql.builder import build_jql
from app.integrations.jira.jql.filters import JQLFilter
from app.integrations.jira.schemas import JiraIssue, JiraIssuePage

# Fields requested on every search — kept narrow rather than fetching
# Jira's full field set (summary/type/status/assignee/timestamps cover
# every filter this service supports), plus whichever custom field holds
# story points on this Jira instance. Callers needing additional fields
# should use JiraIssuesResource.search_issues directly.
_DEFAULT_FIELDS = [
    "summary",
    "issuetype",
    "status",
    "priority",
    "assignee",
    "created",
    "updated",
    "timespent",
    "timeestimate",
    "timeoriginalestimate",
]


class JQLService:
    """Generates and executes JQL queries, returning structured models."""

    def __init__(self, http: JiraHTTPClient, story_points_field: str) -> None:
        self._http = http
        self._story_points_field = story_points_field
        self._fields = [*_DEFAULT_FIELDS, story_points_field]

    def generate_jql(self, filter_: JQLFilter) -> str:
        """Build the JQL string for a filter without executing it.

        Exposed separately from :meth:`search`/:meth:`search_all` so
        callers can log, cache, or display the generated query — e.g. an
        admin debugging tool that shows "here's the JQL this filter
        produced" before running it.
        """
        return build_jql(filter_)

    async def search(
        self,
        filter_: JQLFilter,
        *,
        start_at: int = 0,
        page_size: int = 50,
    ) -> JiraIssuePage:
        """Execute one page of a JQL search, with pagination metadata.

        Use this when the caller wants explicit control over which page
        it's on — e.g. an API endpoint serving a paginated frontend list,
        where fetching everything into memory up front would be wasteful.

        Args:
            filter_: The structured filter describing what to match, how
                to sort, etc.
            start_at: Zero-based offset of the first result to return.
            page_size: Maximum results to return in this page (Jira may
                return fewer, but not more).

        Returns:
            One page of matching issues plus pagination metadata
            (``total``, ``is_last``) so the caller can decide whether to
            fetch another page.
        """
        jql = self.generate_jql(filter_)
        params: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": page_size,
            "fields": ",".join(self._fields),
        }
        raw = await self._http.request("GET", "/rest/api/3/search", params=params)
        assert isinstance(raw, dict), (
            f"Expected a dict response from /rest/api/3/search, got {type(raw).__name__}"
        )

        issues = [
            JiraIssue.from_api(item, self._story_points_field)
            for item in raw.get("issues", [])
        ]
        returned_start_at = raw.get("startAt", start_at)
        returned_max_results = raw.get("maxResults", page_size)
        total = raw.get("total", len(issues))

        return JiraIssuePage(
            items=issues,
            start_at=returned_start_at,
            max_results=returned_max_results,
            total=total,
            is_last=(returned_start_at + len(issues)) >= total,
        )

    async def search_all(self, filter_: JQLFilter, *, page_size: int = 100) -> list[JiraIssue]:
        """Execute a JQL search and return every matching issue across all pages.

        Use this when the caller genuinely needs the full result set at
        once (e.g. computing sprint-wide metrics) rather than paging
        through it — internally this still fetches page by page via
        :meth:`JiraHTTPClient.paginate`, it just does so transparently
        instead of handing pagination control back to the caller.

        Args:
            filter_: The structured filter describing what to match, how
                to sort, etc.
            page_size: Page size used internally for each underlying
                request; does not affect the returned result, which is
                always the complete match set.

        Returns:
            Every matching issue, in the order Jira returned them.
        """
        jql = self.generate_jql(filter_)
        params: dict[str, Any] = {"jql": jql, "fields": ",".join(self._fields)}

        issues: list[JiraIssue] = []
        async for raw in self._http.paginate(
            "GET",
            "/rest/api/3/search",
            params=params,
            values_key="issues",
            page_size=page_size,
        ):
            issues.append(JiraIssue.from_api(raw, self._story_points_field))
        return issues