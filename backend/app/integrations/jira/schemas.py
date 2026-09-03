"""Normalized data models for Jira API responses.

Jira's raw REST API JSON is deeply nested and inconsistent between
endpoints (the Agile API and the core API don't even agree on pagination
field names — see ``http_client.py::paginate``). Every resource client in
``resources/`` converts raw JSON into one of these models before
returning it, so nothing outside this package ever touches a raw Jira
payload. That's the boundary that lets the rest of the application depend
on a stable shape regardless of what Jira changes on their end.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JiraProject(BaseModel):
    """A Jira project, from ``GET /rest/api/3/project/search`` or `/project/{key}`."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str
    name: str
    project_type_key: str | None = Field(default=None, alias="projectTypeKey")


class JiraBoard(BaseModel):
    """An Agile board, from the Agile API's ``/board`` endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    type: str


class JiraSprint(BaseModel):
    """A sprint, from the Agile API's ``/board/{id}/sprint`` or `/sprint/{id}`."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    state: str
    start_date: datetime | None = Field(default=None, alias="startDate")
    end_date: datetime | None = Field(default=None, alias="endDate")
    complete_date: datetime | None = Field(default=None, alias="completeDate")
    origin_board_id: int | None = Field(default=None, alias="originBoardId")


class JiraUser(BaseModel):
    """A Jira user/assignee.

    Jira Cloud identifies users by ``accountId`` (a stable, opaque string)
    rather than username or email — email may not even be present,
    depending on the requester's permissions and the target user's privacy
    settings, hence ``email_address`` being optional.
    """

    model_config = ConfigDict(populate_by_name=True)

    account_id: str = Field(alias="accountId")
    display_name: str = Field(alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")
    active: bool = True


class JiraIssue(BaseModel):
    """A Jira issue, flattened from the raw ``fields``-nested API payload.

    Built via :meth:`from_api` rather than plain ``model_validate`` because
    the fields we care about (status, issue type, story points) are nested
    under ``fields`` in the raw JSON, and story points specifically lives
    under a Jira-instance-specific custom field ID with no fixed name —
    that requires a small parsing function, not just alias declarations.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str
    summary: str
    issue_type: str
    status: str
    priority: str | None = None
    assignee: JiraUser | None = None
    story_points: float | None = None
    created: datetime
    updated: datetime
    time_spent_seconds: int | None = None
    """Logged work time, from Jira's classic time-tracking `timespent` field.
    ``None`` if time tracking is disabled on this project or no time has
    been logged — not the same as ``0``, which means time tracking is on
    but nothing has been logged yet."""
    time_remaining_seconds: int | None = None
    """Remaining estimate, from Jira's `timeestimate` field. Jira keeps this
    as a distinct, manually-adjustable figure rather than deriving it from
    (original estimate - time spent), so it is fetched separately rather
    than computed."""
    original_estimate_seconds: int | None = None
    """Original estimate, from Jira's `timeoriginalestimate` field. Not used
    by Workload Analytics directly, but fetched alongside the other two
    time-tracking fields since they come from the same Jira feature and a
    future estimate-accuracy module will want it."""

    @classmethod
    def from_api(cls, raw: dict[str, Any], story_points_field: str) -> JiraIssue:
        """Build a :class:`JiraIssue` from one raw Jira issue payload.

        Args:
            raw: A single issue object as returned by Jira (has ``id``,
                ``key``, and a nested ``fields`` dict).
            story_points_field: The custom field ID (e.g.
                ``"customfield_10016"``) that holds story points on this
                Jira instance — passed in from
                :attr:`app.core.config.Settings.JIRA_STORY_POINTS_FIELD`
                rather than hardcoded, since it varies per Jira Cloud site.

        Returns:
            A fully-populated, flattened :class:`JiraIssue`.
        """
        fields = raw.get("fields", {}) or {}
        assignee_raw = fields.get("assignee")
        return cls(
            id=raw["id"],
            key=raw["key"],
            summary=fields.get("summary") or "",
            issue_type=(fields.get("issuetype") or {}).get("name", "Unknown"),
            status=(fields.get("status") or {}).get("name", "Unknown"),
            priority=(fields.get("priority") or {}).get("name"),
            assignee=JiraUser.model_validate(assignee_raw) if assignee_raw else None,
            story_points=fields.get(story_points_field),
            created=fields["created"],
            updated=fields["updated"],
            time_spent_seconds=fields.get("timespent"),
            time_remaining_seconds=fields.get("timeestimate"),
            original_estimate_seconds=fields.get("timeoriginalestimate"),
        )


class JiraIssuePage(BaseModel):
    """One page of issue search results, with pagination metadata.

    Returned by :meth:`app.integrations.jira.jql.service.JQLService.search`
    for callers that want explicit page-by-page control (e.g. an API
    endpoint backing a paginated frontend view), as opposed to
    :meth:`~app.integrations.jira.jql.service.JQLService.search_all`,
    which exhausts every page internally and returns one flat list.
    """

    items: list[JiraIssue]
    start_at: int
    max_results: int
    total: int
    is_last: bool