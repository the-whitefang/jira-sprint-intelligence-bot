"""Time Analytics module.

Computes time-based delivery metrics — lead time and issue age — from a
set of issues. Independent of every other analytics module.

**Important limitation:** true *cycle time* (time actively spent
"In Progress," excluding time sitting untouched in a backlog) requires
each issue's full status-transition history. Jira only exposes that via
a separate changelog API call, which this module does not have access to
at this layer. What this module computes instead is **lead time** —
``updated - created`` for completed issues — which measures total
elapsed time including backlog wait time, not active work time. These
are genuinely different metrics, and reporting one as the other would be
misleading, so this module is explicit in its naming about which one it
provides. True cycle time becomes available once the sync worker
persists Jira's changelog into a ``ticket_history`` table (per the MySQL
schema designed earlier); a history-aware module can be added alongside
this one at that point, not as a replacement for it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from app.analytics.base import DEFAULT_DONE_STATUSES, safe_mean, safe_median
from app.integrations.jira.schemas import JiraIssue


class TimeAnalyticsResult(BaseModel):
    """Lead-time and age metrics for a set of issues."""

    completed_issue_count: int
    avg_lead_time_hours: float
    median_lead_time_hours: float
    min_lead_time_hours: float
    max_lead_time_hours: float
    open_issue_count: int
    avg_open_age_hours: float
    oldest_open_issue_key: str | None
    oldest_open_issue_age_hours: float


class TimeAnalyticsService:
    """Computes lead-time and age metrics from an issue set.

    See the module docstring for the distinction between lead time
    (computed here) and cycle time (not available at this layer).
    """

    def __init__(self, done_statuses: frozenset[str] = DEFAULT_DONE_STATUSES) -> None:
        self._done_statuses = done_statuses

    def compute(
        self, issues: list[JiraIssue], *, as_of: datetime | None = None
    ) -> TimeAnalyticsResult:
        """Compute lead-time and age metrics.

        Args:
            issues: Any set of issues.
            as_of: Reference time for open-issue age calculations.
                Defaults to the current UTC time; accepted as a parameter
                to keep this method deterministic and testable.

        Returns:
            A populated :class:`TimeAnalyticsResult`.
        """
        reference = as_of or datetime.now(timezone.utc)

        completed = [issue for issue in issues if issue.status in self._done_statuses]
        open_issues = [issue for issue in issues if issue.status not in self._done_statuses]

        lead_times_hours = [
            (issue.updated - issue.created).total_seconds() / 3600
            for issue in completed
            if issue.updated >= issue.created
        ]
        open_ages_hours = [
            (reference - issue.created).total_seconds() / 3600 for issue in open_issues
        ]

        oldest_open_key: str | None = None
        oldest_open_age_hours = 0.0
        if open_issues:
            oldest = max(open_issues, key=lambda issue: reference - issue.created)
            oldest_open_key = oldest.key
            oldest_open_age_hours = round((reference - oldest.created).total_seconds() / 3600, 2)

        return TimeAnalyticsResult(
            completed_issue_count=len(completed),
            avg_lead_time_hours=safe_mean(lead_times_hours),
            median_lead_time_hours=safe_median(lead_times_hours),
            min_lead_time_hours=round(min(lead_times_hours), 2) if lead_times_hours else 0.0,
            max_lead_time_hours=round(max(lead_times_hours), 2) if lead_times_hours else 0.0,
            open_issue_count=len(open_issues),
            avg_open_age_hours=safe_mean(open_ages_hours),
            oldest_open_issue_key=oldest_open_key,
            oldest_open_issue_age_hours=oldest_open_age_hours,
        )
