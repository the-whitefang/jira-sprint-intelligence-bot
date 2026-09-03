"""Risk Analytics module.

Synthesizes sprint signals — pace vs. elapsed time, scope change,
staleness, velocity trend — into a single risk classification.
Deliberately does **not** import
:class:`~app.analytics.sprint_analytics.SprintAnalyticsResult` or any
other analytics module's types: it depends only on the plain numeric
fields defined on :class:`SprintRiskInput` below, so it has zero
import-time coupling to the rest of the analytics engine and can be
exercised in isolation with hand-built numbers. A future orchestration
layer is responsible for populating ``SprintRiskInput`` from whichever
other modules' outputs it has already computed (typically
``SprintAnalyticsResult``, historical velocity figures, and a staleness
count derived separately).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.analytics.base import RiskLevel, safe_mean, safe_percentage


class SprintRiskInput(BaseModel):
    """The subset of sprint signals risk classification actually needs.

    Deliberately a small, flat, independent model rather than a reuse of
    ``SprintAnalyticsResult`` — see the module docstring for why.
    """

    sprint_id: int
    sprint_name: str
    total_issues: int
    completion_rate_points: float
    """Percentage of planned points already completed (0-100)."""
    planned_points: float
    scope_added_points: float
    """Points added to the sprint after it started."""
    historical_velocities: list[float] = Field(default_factory=list)
    """Completed points from the previous N sprints, most recent last —
    used to detect a velocity drop. An empty list disables that check
    rather than raising, since historical data may not exist yet
    (e.g. the team's first sprint)."""
    days_total: int
    days_elapsed: int
    stale_issue_count: int = 0
    """Issues with no recent activity, by whatever threshold the caller
    used to compute this — this module only consumes the count."""

    @model_validator(mode="after")
    def _validate_days(self) -> SprintRiskInput:
        if self.days_total <= 0:
            raise ValueError("days_total must be positive")
        if not (0 <= self.days_elapsed <= self.days_total):
            raise ValueError("days_elapsed must be between 0 and days_total")
        return self


class RiskFlag(BaseModel):
    """A single detected risk condition."""

    name: str
    severity: RiskLevel
    message: str


class RiskAnalyticsResult(BaseModel):
    """Overall risk classification for a sprint."""

    sprint_id: int
    sprint_name: str
    overall_risk: RiskLevel
    risk_score: float
    """0-100; higher means riskier. Derived from the severities of
    ``flags``, not an independent input."""
    flags: list[RiskFlag]


class RiskAnalyticsService:
    """Classifies sprint risk from a small set of configurable threshold checks.

    Every threshold below has a sensible default but is overridable at
    construction time, since "how much scope creep is concerning" is a
    team-specific policy call, not a universal constant.
    """

    def __init__(
        self,
        velocity_drop_threshold: float = 20.0,
        scope_creep_threshold: float = 20.0,
        stale_issue_threshold_count: int = 3,
    ) -> None:
        self._velocity_drop_threshold = velocity_drop_threshold
        self._scope_creep_threshold = scope_creep_threshold
        self._stale_issue_threshold_count = stale_issue_threshold_count

    def compute(self, sprint: SprintRiskInput) -> RiskAnalyticsResult:
        """Run every risk check and combine the results.

        Args:
            sprint: The sprint's risk-relevant signals.

        Returns:
            A populated :class:`RiskAnalyticsResult` with zero or more
            flags and an overall severity derived from them.
        """
        flags: list[RiskFlag] = [
            *self._check_pace(sprint),
            *self._check_scope_creep(sprint),
            *self._check_staleness(sprint),
            *self._check_velocity_trend(sprint),
        ]

        risk_score = self._score(flags)
        return RiskAnalyticsResult(
            sprint_id=sprint.sprint_id,
            sprint_name=sprint.sprint_name,
            overall_risk=self._overall_level(risk_score),
            risk_score=risk_score,
            flags=flags,
        )

    def _check_pace(self, sprint: SprintRiskInput) -> list[RiskFlag]:
        """Flag when completion rate is badly behind elapsed time.

        A sprint 80% through its days but only 30% through its points is
        a strong leading indicator it won't finish on time — this catches
        that while the sprint is still running, not only in retrospect.
        """
        time_elapsed_pct = safe_percentage(sprint.days_elapsed, sprint.days_total)
        pace_gap = time_elapsed_pct - sprint.completion_rate_points

        if pace_gap >= 40:
            severity = RiskLevel.CRITICAL
        elif pace_gap >= 20:
            severity = RiskLevel.HIGH
        else:
            return []

        return [
            RiskFlag(
                name="behind_pace",
                severity=severity,
                message=(
                    f"{time_elapsed_pct:.0f}% of the sprint has elapsed but only "
                    f"{sprint.completion_rate_points:.0f}% of points are complete."
                ),
            )
        ]

    def _check_scope_creep(self, sprint: SprintRiskInput) -> list[RiskFlag]:
        """Flag when a large share of planned points were added mid-sprint."""
        if sprint.planned_points <= 0:
            return []

        scope_creep_pct = safe_percentage(sprint.scope_added_points, sprint.planned_points)
        if scope_creep_pct < self._scope_creep_threshold:
            return []

        severity = (
            RiskLevel.HIGH
            if scope_creep_pct >= self._scope_creep_threshold * 2
            else RiskLevel.MEDIUM
        )
        return [
            RiskFlag(
                name="scope_creep",
                severity=severity,
                message=f"{scope_creep_pct:.0f}% of planned points were added after the sprint started.",
            )
        ]

    def _check_staleness(self, sprint: SprintRiskInput) -> list[RiskFlag]:
        """Flag when too many issues have seen no recent activity."""
        if sprint.stale_issue_count < self._stale_issue_threshold_count:
            return []
        return [
            RiskFlag(
                name="stale_issues",
                severity=RiskLevel.MEDIUM,
                message=f"{sprint.stale_issue_count} issues have seen no activity recently.",
            )
        ]

    def _check_velocity_trend(self, sprint: SprintRiskInput) -> list[RiskFlag]:
        """Flag when the sprint's projected pace is well below historical velocity.

        Projects the sprint's eventual velocity by scaling current
        progress up to a full sprint length (``planned_points *
        completion_rate`` scaled by ``days_total / days_elapsed``), then
        compares that projection against the historical average.
        """
        if not sprint.historical_velocities or sprint.days_elapsed <= 0:
            return []

        avg_historical = safe_mean(sprint.historical_velocities)
        if avg_historical <= 0:
            return []

        completed_points = sprint.completion_rate_points / 100 * sprint.planned_points
        projected_full_sprint = completed_points * (sprint.days_total / sprint.days_elapsed)

        drop_pct = safe_percentage(avg_historical - projected_full_sprint, avg_historical)
        if drop_pct < self._velocity_drop_threshold:
            return []

        return [
            RiskFlag(
                name="velocity_drop",
                severity=RiskLevel.HIGH,
                message=(
                    f"Projected velocity ({projected_full_sprint:.1f} pts) is {drop_pct:.0f}% "
                    f"below the historical average ({avg_historical:.1f} pts)."
                ),
            )
        ]

    @staticmethod
    def _score(flags: list[RiskFlag]) -> float:
        """Combine flag severities into a single 0-100 score, capped at 100."""
        weights = {
            RiskLevel.LOW: 10,
            RiskLevel.MEDIUM: 25,
            RiskLevel.HIGH: 45,
            RiskLevel.CRITICAL: 70,
        }
        return float(min(sum(weights[flag.severity] for flag in flags), 100))

    @staticmethod
    def _overall_level(score: float) -> RiskLevel:
        """Map a combined score back to a single overall severity."""
        if score >= 70:
            return RiskLevel.CRITICAL
        if score >= 45:
            return RiskLevel.HIGH
        if score >= 20:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
