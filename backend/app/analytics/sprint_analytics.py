"""Sprint Analytics module.

Computes per-sprint delivery metrics — velocity, completion rate, scope
change, and cycle time — from a sprint's issue set. Independent of every
other analytics module: it needs nothing but a
:class:`~app.integrations.jira.schemas.JiraSprint` and the
:class:`~app.integrations.jira.schemas.JiraIssue`\\ s that belong to it.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from app.analytics.base import DEFAULT_DONE_STATUSES, safe_mean, safe_percentage
from app.integrations.jira.schemas import JiraIssue, JiraSprint


class SprintAnalyticsResult(BaseModel):
    """Delivery metrics for one sprint."""

    sprint_id: int
    sprint_name: str
    total_issues: int
    completed_issues: int
    completion_rate_issues: float
    """Percentage of *issues* (not points) that are in a done status."""
    planned_points: float
    completed_points: float
    velocity: float
    """Alias for ``completed_points`` — the term most teams actually use."""
    completion_rate_points: float
    """Percentage of *points* that are in a done status."""
    scope_added_count: int
    """Issues created after the sprint's start date — i.e. added mid-sprint."""
    scope_added_points: float
    avg_cycle_time_hours: float
    status_breakdown: dict[str, int]


class IssueCounts(BaseModel):
    """Lighter-weight shape for just the issue totals, used by cache."""

    total_issues: int
    completed_issues: int
    status_breakdown: dict[str, int]


class SprintAnalyticsService:
    """Computes delivery metrics for a single sprint."""

    def __init__(self, done_statuses: frozenset[str] = DEFAULT_DONE_STATUSES) -> None:
        self._done_statuses = done_statuses

    def compute_issue_counts(self, issues: list[JiraIssue]) -> IssueCounts:
        """Compute just the issue counts.

        More lightweight than the full compute() function.
        """
        total_issues = len(issues)
        completed_issues = sum(1 for issue in issues if issue.status in self._done_statuses)
        return IssueCounts(
            total_issues=total_issues,
            completed_issues=completed_issues,
            status_breakdown=dict(Counter(issue.status for issue in issues)),
        )

    def compute(self, sprint: JiraSprint, issues: list[JiraIssue]) -> SprintAnalyticsResult:
        """Compute sprint analytics.

        Args:
            sprint: The sprint's metadata (id, name, start/end dates).
            issues: Every issue assigned to this sprint at the time of
                computation — e.g. from
                ``JiraIssuesResource.list_sprint_issues()`` or
                ``JQLService.search_all(JQLFilter(sprint_id=...))``.

        Returns:
            A populated :class:`SprintAnalyticsResult`. Every field is
            well-defined even for an empty sprint (``issues == []``) —
            rates come back as ``0.0`` rather than raising, since an
            empty sprint is a valid state to report on, not an error.

        Note:
            ``avg_cycle_time_hours`` is computed as ``updated - created``
            for completed issues, which approximates but is not equal to
            true cycle time (time actively spent "In Progress"). Precise
            cycle time requires each issue's full status-transition
            history, which is not available at this layer — see the
            module-level note in ``time_analytics.py`` for the same
            caveat and what would resolve it.
        """
        total_issues = len(issues)
        completed = [issue for issue in issues if issue.status in self._done_statuses]
        completed_issues = len(completed)

        planned_points = round(sum(issue.story_points or 0.0 for issue in issues), 2)
        completed_points = round(sum(issue.story_points or 0.0 for issue in completed), 2)

        scope_added: list[JiraIssue] = []
        if sprint.start_date is not None:
            scope_added = [issue for issue in issues if issue.created > sprint.start_date]
        scope_added_points = round(sum(issue.story_points or 0.0 for issue in scope_added), 2)

        cycle_times_hours = [
            (issue.updated - issue.created).total_seconds() / 3600
            for issue in completed
            if issue.updated >= issue.created
        ]

        return SprintAnalyticsResult(
            sprint_id=sprint.id,
            sprint_name=sprint.name,
            total_issues=total_issues,
            completed_issues=completed_issues,
            completion_rate_issues=safe_percentage(completed_issues, total_issues),
            planned_points=planned_points,
            completed_points=completed_points,
            velocity=completed_points,
            completion_rate_points=safe_percentage(completed_points, planned_points),
            scope_added_count=len(scope_added),
            scope_added_points=scope_added_points,
            avg_cycle_time_hours=safe_mean(cycle_times_hours),
            status_breakdown=dict(Counter(issue.status for issue in issues)),
        )
