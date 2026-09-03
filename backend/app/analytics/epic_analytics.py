"""Epic Analytics module.

Computes progress metrics for a single epic — completion rate, points
burned down, and status breakdown of its child issues. Independent of
every other analytics module.

Epic linkage in Jira is configuration-dependent: company-managed
projects use a custom "Epic Link" field with a site-specific field ID,
while team-managed projects use the built-in ``parent`` field — the same
kind of per-instance variability that story points has (see
:attr:`app.core.config.Settings.JIRA_STORY_POINTS_FIELD`). Rather than
bake a particular epic-link field into
:class:`~app.integrations.jira.schemas.JiraIssue` — which would make
every consumer of that model fragile across Jira configurations for a
field most of them don't need — this module accepts the epic's
identifying info and its already-grouped child issues directly. Grouping
issues by epic is the caller's responsibility (typically the future sync
worker, which will read the site's actual epic-link field once it's
built), keeping that Jira-instance-specific concern out of this module
entirely.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from app.analytics.base import DEFAULT_DONE_STATUSES, safe_percentage
from app.integrations.jira.schemas import JiraIssue


class EpicAnalyticsResult(BaseModel):
    """Progress metrics for a single epic."""

    epic_key: str
    epic_summary: str
    total_issues: int
    completed_issues: int
    completion_rate: float
    total_points: float
    completed_points: float
    remaining_points: float
    status_breakdown: dict[str, int]


class EpicAnalyticsService:
    """Computes progress metrics for a single epic's child issues."""

    def __init__(self, done_statuses: frozenset[str] = DEFAULT_DONE_STATUSES) -> None:
        self._done_statuses = done_statuses

    def compute(
        self, epic_key: str, epic_summary: str, issues: list[JiraIssue]
    ) -> EpicAnalyticsResult:
        """Compute progress metrics for one epic.

        Args:
            epic_key: The epic's own issue key (e.g. ``"ENG-100"``).
            epic_summary: The epic's title, for display purposes.
            issues: The epic's child issues, already resolved by the
                caller via whatever epic-link mechanism this Jira
                instance uses.

        Returns:
            A populated :class:`EpicAnalyticsResult`. Well-defined even
            for an epic with no child issues yet (all rates come back as
            ``0.0``).
        """
        total_issues = len(issues)
        completed = [issue for issue in issues if issue.status in self._done_statuses]
        total_points = round(sum(issue.story_points or 0.0 for issue in issues), 2)
        completed_points = round(sum(issue.story_points or 0.0 for issue in completed), 2)

        return EpicAnalyticsResult(
            epic_key=epic_key,
            epic_summary=epic_summary,
            total_issues=total_issues,
            completed_issues=len(completed),
            completion_rate=safe_percentage(len(completed), total_issues),
            total_points=total_points,
            completed_points=completed_points,
            remaining_points=round(total_points - completed_points, 2),
            status_breakdown=dict(Counter(issue.status for issue in issues)),
        )
