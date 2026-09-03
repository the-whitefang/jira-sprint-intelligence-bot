"""Backlog Analytics module.

Computes backlog health metrics — size, age distribution, staleness, and
estimation coverage — from a set of not-yet-started issues. Independent
of every other analytics module; the caller decides what counts as
"backlog" (typically issues with no sprint assigned, or in a
"Backlog"/"To Do" status) and passes that issue list in.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from app.analytics.base import safe_mean, safe_percentage
from app.integrations.jira.schemas import JiraIssue

# Age buckets in days, expressed as [low, high) pairs. A final "N+" bucket
# covering everything older than the last pair's upper bound is added
# automatically in compute().
_AGE_BUCKETS_DAYS: list[tuple[int, int]] = [(0, 7), (7, 30), (30, 90)]


class AgeBucket(BaseModel):
    """One bucket of the backlog's age distribution."""

    label: str
    count: int
    points: float


class BacklogAnalyticsResult(BaseModel):
    """Health metrics for a backlog."""

    total_issues: int
    total_points: float
    issues_missing_estimate: int
    estimate_coverage_rate: float
    """Percentage of issues that have a story-point estimate set."""
    avg_age_days: float
    stale_issue_count: int
    """Issues older than the configured ``stale_threshold_days``."""
    age_distribution: list[AgeBucket]


class BacklogAnalyticsService:
    """Computes backlog health metrics: size, age, staleness, estimate coverage."""

    def __init__(self, stale_threshold_days: int = 90) -> None:
        if stale_threshold_days <= 0:
            raise ValueError("stale_threshold_days must be positive")
        self._stale_threshold_days = stale_threshold_days

    def compute(
        self, issues: list[JiraIssue], *, as_of: datetime | None = None
    ) -> BacklogAnalyticsResult:
        """Compute backlog health metrics.

        Args:
            issues: The backlog's issue set, as defined by the caller.
            as_of: The reference time ages are computed against. Defaults
                to the current UTC time; accepting it as a parameter
                keeps this method deterministic and testable rather than
                implicitly depending on wall-clock time at call time.

        Returns:
            A populated :class:`BacklogAnalyticsResult`.
        """
        reference = as_of or datetime.now(timezone.utc)
        total_issues = len(issues)
        total_points = round(sum(issue.story_points or 0.0 for issue in issues), 2)
        missing_estimate = sum(1 for issue in issues if issue.story_points is None)

        ages_days = [(reference - issue.created).total_seconds() / 86400 for issue in issues]
        stale_count = sum(1 for age in ages_days if age >= self._stale_threshold_days)

        buckets: list[AgeBucket] = []
        for low, high in _AGE_BUCKETS_DAYS:
            bucket_issues = [
                issue for issue, age in zip(issues, ages_days, strict=True) if low <= age < high
            ]
            buckets.append(
                AgeBucket(
                    label=f"{low}-{high}d",
                    count=len(bucket_issues),
                    points=round(sum(issue.story_points or 0.0 for issue in bucket_issues), 2),
                )
            )

        oldest_bound = _AGE_BUCKETS_DAYS[-1][1]
        oldest_issues = [
            issue for issue, age in zip(issues, ages_days, strict=True) if age >= oldest_bound
        ]
        buckets.append(
            AgeBucket(
                label=f"{oldest_bound}d+",
                count=len(oldest_issues),
                points=round(sum(issue.story_points or 0.0 for issue in oldest_issues), 2),
            )
        )

        return BacklogAnalyticsResult(
            total_issues=total_issues,
            total_points=total_points,
            issues_missing_estimate=missing_estimate,
            estimate_coverage_rate=safe_percentage(total_issues - missing_estimate, total_issues),
            avg_age_days=safe_mean(ages_days),
            stale_issue_count=stale_count,
            age_distribution=buckets,
        )
