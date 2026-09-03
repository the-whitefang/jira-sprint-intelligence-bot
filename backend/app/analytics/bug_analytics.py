"""Bug Analytics module.

Computes bug-specific quality metrics — open/closed counts, priority
distribution, and resolution time — from a set of issues. Independent of
every other analytics module; filters to bug-type issues internally, so
the caller can pass a project's or sprint's full issue set without
pre-filtering.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from app.analytics.base import DEFAULT_DONE_STATUSES, safe_mean, safe_percentage
from app.integrations.jira.schemas import JiraIssue

# Jira's default issue type is literally "Bug," but some teams rename or
# add types (e.g. "Defect", "Production Bug") — overridable per instance
# for the same reason `done_statuses` is.
DEFAULT_BUG_ISSUE_TYPES: frozenset[str] = frozenset({"Bug"})


class BugAnalyticsResult(BaseModel):
    """Bug quality metrics for a set of issues."""

    total_bugs: int
    open_bugs: int
    closed_bugs: int
    resolution_rate: float
    bugs_by_priority: dict[str, int]
    """Keyed by priority name; issues with no priority set are grouped under
    ``"Unspecified"``."""
    bugs_by_status: dict[str, int]
    avg_resolution_time_hours: float
    bug_ratio: float
    """Bugs as a percentage of all issues in the input set — a proxy for
    how much of the team's work is defect-driven vs. new development."""


class BugAnalyticsService:
    """Computes bug quality metrics from an issue set."""

    def __init__(
        self,
        done_statuses: frozenset[str] = DEFAULT_DONE_STATUSES,
        bug_issue_types: frozenset[str] = DEFAULT_BUG_ISSUE_TYPES,
    ) -> None:
        self._done_statuses = done_statuses
        self._bug_issue_types = bug_issue_types

    def compute(self, issues: list[JiraIssue]) -> BugAnalyticsResult:
        """Compute bug metrics from a set of issues.

        Args:
            issues: Any set of issues — a sprint, a project, a backlog.
                Non-bug issue types are counted only toward ``bug_ratio``'s
                denominator and are otherwise ignored.

        Returns:
            A populated :class:`BugAnalyticsResult`.
        """
        bugs = [issue for issue in issues if issue.issue_type in self._bug_issue_types]
        total_bugs = len(bugs)
        closed = [bug for bug in bugs if bug.status in self._done_statuses]
        open_bugs = total_bugs - len(closed)

        resolution_times_hours = [
            (bug.updated - bug.created).total_seconds() / 3600
            for bug in closed
            if bug.updated >= bug.created
        ]

        return BugAnalyticsResult(
            total_bugs=total_bugs,
            open_bugs=open_bugs,
            closed_bugs=len(closed),
            resolution_rate=safe_percentage(len(closed), total_bugs),
            bugs_by_priority=dict(Counter(bug.priority or "Unspecified" for bug in bugs)),
            bugs_by_status=dict(Counter(bug.status for bug in bugs)),
            avg_resolution_time_hours=safe_mean(resolution_times_hours),
            bug_ratio=safe_percentage(total_bugs, len(issues)),
        )
