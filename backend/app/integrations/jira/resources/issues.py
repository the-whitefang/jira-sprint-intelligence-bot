"""Jira Issues resource client.

Wraps issue search (JQL, core API) and per-sprint issue listing (Agile
API) — the two ways the rest of the application will need to pull
tickets.
"""

from __future__ import annotations

from app.integrations.jira.http_client import JiraHTTPClient
from app.integrations.jira.schemas import JiraIssue

# Fields requested by default on every search — kept narrow rather than
# fetching Jira's full field set, since a full-field response is
# significantly larger and slower for no benefit here. Callers needing
# something outside this set can pass their own `fields` list.
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


class JiraIssuesResource:
    """Read access to Jira issues."""

    def __init__(self, http: JiraHTTPClient, story_points_field: str) -> None:
        self._http = http
        self._story_points_field = story_points_field

    async def search_issues(
        self, jql: str, *, fields: list[str] | None = None
    ) -> list[JiraIssue]:
        """Search issues using JQL (Jira Query Language).

        Args:
            jql: A JQL query string, e.g.
                ``'project = ENG AND sprint = 123'``.
            fields: Field names to request. Defaults to a narrow set
                (summary/type/status/assignee/timestamps) plus the
                configured story-points custom field.

        Returns:
            Every matching issue, fully paginated.

        Raises:
            JiraIntegrationError: The JQL was rejected as invalid — this
                is a genuine bad-request, not a transient failure, so it
                is not retried.
        """
        requested_fields = list(fields or _DEFAULT_FIELDS)
        if self._story_points_field not in requested_fields:
            requested_fields.append(self._story_points_field)

        params = {"jql": jql, "fields": ",".join(requested_fields)}
        issues: list[JiraIssue] = []
        async for raw in self._http.paginate(
            "GET", "/rest/api/3/search", params=params, values_key="issues"
        ):
            issues.append(JiraIssue.from_api(raw, self._story_points_field))
        return issues

    async def get_issue(self, issue_key: str) -> JiraIssue:
        """Fetch a single issue by its key (e.g. ``"ENG-123"``).

        Raises:
            JiraNotFoundError: No issue exists with that key.
        """
        raw = await self._http.request("GET", f"/rest/api/3/issue/{issue_key}")
        return JiraIssue.from_api(raw, self._story_points_field)

    async def list_sprint_issues(self, sprint_id: int) -> list[JiraIssue]:
        """List every issue assigned to a given sprint, via the Agile API.

        Preferred over ``search_issues(f"sprint = {sprint_id}")`` when the
        caller already has a sprint ID, since it hits the Agile API's
        purpose-built endpoint rather than a JQL search.
        """
        issues: list[JiraIssue] = []
        async for raw in self._http.paginate(
            "GET", f"/rest/agile/1.0/sprint/{sprint_id}/issue", values_key="issues"
        ):
            issues.append(JiraIssue.from_api(raw, self._story_points_field))
        return issues