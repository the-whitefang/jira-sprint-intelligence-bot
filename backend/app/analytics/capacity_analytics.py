"""Capacity Analytics module.

Compares planned team capacity against allocated work to flag over- and
under-allocated team members. Independent of every other analytics
module by design — it takes plain allocation figures as input rather
than depending on :class:`~app.analytics.workload_analytics.WorkloadAnalyticsResult`,
so it can be driven by allocation data from any source (Jira-derived,
a planning spreadsheet, a capacity-planning tool) and has zero
import-time coupling to any other analytics module.

Capacity itself — how many points or hours a person can realistically
take on in a given period — is not something Jira exposes; it comes from
team planning (PTO, part-time allocation, meeting load, on-call
rotations) that lives entirely outside Jira. This module therefore takes
capacity as caller-supplied input rather than trying to infer it from
Jira data.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.analytics.base import RiskLevel, safe_percentage


class TeamMemberCapacity(BaseModel):
    """One team member's planned capacity vs. currently allocated work.

    Both figures are supplied by the caller — this module performs no
    lookup of its own.
    """

    account_id: str
    display_name: str
    capacity_points: float
    """Planned available capacity for the period being analyzed."""
    allocated_points: float
    """Points currently assigned to this person for the same period."""


class MemberCapacityResult(BaseModel):
    """Utilization outcome for a single team member."""

    account_id: str
    display_name: str
    capacity_points: float
    allocated_points: float
    utilization_rate: float
    status: RiskLevel
    """``LOW`` = under-utilized, ``MEDIUM`` = healthy, ``HIGH`` = over-allocated,
    ``CRITICAL`` = severely over-allocated. See threshold constructor args."""


class CapacityAnalyticsResult(BaseModel):
    """Team-wide capacity utilization."""

    per_member: list[MemberCapacityResult]
    total_capacity_points: float
    total_allocated_points: float
    team_utilization_rate: float
    over_allocated_count: int
    under_allocated_count: int


class CapacityAnalyticsService:
    """Computes utilization and over/under-allocation flags per team member.

    Thresholds are utilization-rate percentages, configurable at
    construction time — "how much over 100% counts as concerning" is a
    team or organizational policy choice, not a universal constant.
    """

    def __init__(
        self,
        under_threshold: float = 70.0,
        over_threshold: float = 100.0,
        critical_threshold: float = 120.0,
    ) -> None:
        if not (0 <= under_threshold < over_threshold < critical_threshold):
            raise ValueError(
                "Thresholds must satisfy "
                "0 <= under_threshold < over_threshold < critical_threshold"
            )
        self._under_threshold = under_threshold
        self._over_threshold = over_threshold
        self._critical_threshold = critical_threshold

    def compute(self, members: list[TeamMemberCapacity]) -> CapacityAnalyticsResult:
        """Compute utilization for each team member and the team as a whole.

        Args:
            members: Each team member's planned capacity and currently
                allocated points for the period being analyzed.

        Returns:
            A populated :class:`CapacityAnalyticsResult`.
        """
        per_member: list[MemberCapacityResult] = []
        for member in members:
            utilization = safe_percentage(member.allocated_points, member.capacity_points)
            per_member.append(
                MemberCapacityResult(
                    account_id=member.account_id,
                    display_name=member.display_name,
                    capacity_points=member.capacity_points,
                    allocated_points=member.allocated_points,
                    utilization_rate=utilization,
                    status=self._classify(utilization),
                )
            )

        total_capacity = round(sum(member.capacity_points for member in members), 2)
        total_allocated = round(sum(member.allocated_points for member in members), 2)

        return CapacityAnalyticsResult(
            per_member=per_member,
            total_capacity_points=total_capacity,
            total_allocated_points=total_allocated,
            team_utilization_rate=safe_percentage(total_allocated, total_capacity),
            over_allocated_count=sum(
                1 for member in per_member if member.utilization_rate > self._over_threshold
            ),
            under_allocated_count=sum(
                1 for member in per_member if member.utilization_rate < self._under_threshold
            ),
        )

    def _classify(self, utilization_rate: float) -> RiskLevel:
        """Map a utilization percentage to a severity level using the configured thresholds."""
        if utilization_rate >= self._critical_threshold:
            return RiskLevel.CRITICAL
        if utilization_rate > self._over_threshold:
            return RiskLevel.HIGH
        if utilization_rate < self._under_threshold:
            return RiskLevel.LOW
        return RiskLevel.MEDIUM
