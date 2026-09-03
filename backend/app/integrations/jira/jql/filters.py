"""Structured filter model for JQL query generation.

:class:`JQLFilter` is the only way callers describe what they want to
query — nobody should hand-write JQL fragments and concatenate them
(that's how JQL injection bugs happen, the same way string-concatenated
SQL causes SQL injection). Every filter field here is a plain, typed
value; ``builder.py`` is solely responsible for turning a validated
:class:`JQLFilter` into a safe JQL string.

Status, priority, and assignee values are intentionally left as
free-form strings rather than a fixed enum: Jira workflows, priority
schemes, and users vary per project and per Jira instance, so there is
no fixed universe of valid values to validate against at this layer —
Jira itself will reject a query naming a status/priority that doesn't
exist, and that rejection surfaces as a normal
:class:`~app.integrations.jira.exceptions.JiraIntegrationError`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Sortable fields are a closed set, unlike filter values — JQL's ORDER BY
# clause takes a bare field name (not a quoted literal), so it cannot be
# safely escaped the way filter values are. A whitelist is the only sound
# way to accept a sort field from a caller without risking JQL injection
# through the ORDER BY clause.
SORTABLE_FIELDS: dict[str, str] = {
    "created": "created",
    "updated": "updated",
    "due_date": "duedate",
    "priority": "priority",
    "status": "status",
    "assignee": "assignee",
    "key": "key",
    "rank": "Rank",  # Jira's default board/backlog order
}


class DateRangeFilter(BaseModel):
    """One date-range condition on a single Jira date field.

    Multiple instances can be combined on :attr:`JQLFilter.date_filters`
    to filter on more than one date field at once (e.g. "created after X
    AND updated before Y").
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    field: Literal["created", "updated", "duedate"] = "created"
    date_from: datetime | None = None
    date_to: datetime | None = None

    @model_validator(mode="after")
    def _require_at_least_one_bound(self) -> DateRangeFilter:
        """Reject a date filter that constrains nothing.

        A :class:`DateRangeFilter` with both bounds unset would silently
        contribute no clause, which is more likely a caller bug (forgot
        to set a bound) than an intentional no-op — failing loudly here
        is cheaper than debugging a query that mysteriously ignored a
        filter later.
        """
        if self.date_from is None and self.date_to is None:
            raise ValueError(
                "DateRangeFilter requires at least one of date_from/date_to to be set"
            )
        return self


class JQLFilter(BaseModel):
    """Structured description of a Jira issue search.

    Every field is optional; an empty :class:`JQLFilter` generates an
    empty JQL string, which Jira's search API treats as "match everything
    the caller has permission to see" — callers that want that behavior
    can pass ``JQLFilter()`` explicitly rather than needing a special case.

    Attributes:
        projects: Project keys to match (``project IN (...)``).
        statuses: Status names to match (``status IN (...)``).
        priorities: Priority names to match (``priority IN (...)``).
        assignee_account_ids: Assignee account IDs to match
            (``assignee IN (...)``). Mutually exclusive with
            ``unassigned``.
        unassigned: If ``True``, match only unassigned issues
            (``assignee IS EMPTY``). Mutually exclusive with
            ``assignee_account_ids``.
        sprint_id: A single sprint's numeric ID (``sprint = <id>``) —
            the field most relevant to this application's domain, since
            almost every query here is scoped to one sprint.
        date_filters: Zero or more date-range conditions; see
            :class:`DateRangeFilter`.
        sort_by: A key from :data:`SORTABLE_FIELDS`, or ``None`` for
            Jira's default ordering.
        sort_direction: ``"ASC"`` or ``"DESC"``.
        extra_jql: An advanced escape hatch — a raw JQL fragment AND-ed
            into the generated query as-is, wrapped in parentheses. This
            bypasses the escaping this module otherwise guarantees, so it
            must **never** be built by directly interpolating end-user
            input; it exists for trusted, developer-authored fragments
            (e.g. a JQL clause with no structured equivalent yet), not as
            a general-purpose text search field.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    projects: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    assignee_account_ids: list[str] = Field(default_factory=list)
    unassigned: bool = False
    sprint_id: int | None = None
    date_filters: list[DateRangeFilter] = Field(default_factory=list)
    sort_by: str | None = None
    sort_direction: Literal["ASC", "DESC"] = "ASC"
    extra_jql: str | None = None

    @model_validator(mode="after")
    def _validate_combination(self) -> JQLFilter:
        """Cross-field validation that can't be expressed per-field.

        Raises:
            ValueError: ``unassigned`` and ``assignee_account_ids`` were
                both set (contradictory — an issue can't be both assigned
                to specific people and unassigned), or ``sort_by`` names
                a field outside :data:`SORTABLE_FIELDS`.
        """
        if self.unassigned and self.assignee_account_ids:
            raise ValueError(
                "JQLFilter cannot combine unassigned=True with assignee_account_ids "
                "— an issue cannot be both unassigned and assigned to specific people"
            )
        if self.sort_by is not None and self.sort_by not in SORTABLE_FIELDS:
            raise ValueError(
                f"Unsupported sort_by '{self.sort_by}'. "
                f"Allowed values: {sorted(SORTABLE_FIELDS)}"
            )
        return self
