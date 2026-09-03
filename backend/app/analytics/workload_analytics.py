"""Workload Analytics module.

Computes per-employee workload — issue counts, story points, logged and
remaining time, and sprint utilization — from a set of issues, and flags
employees as overloaded or idle. Independent of sprint boundaries (works
over a single sprint, a backlog, or any issue set the caller assembles)
and independent of every other analytics module.

Two things this module needs are configuration, not derivable from Jira
alone, so both are accepted as inputs rather than guessed:

* **Sprint capacity per person** — how many hours someone can realistically
  contribute in the period being analyzed. Jira has no concept of this; it
  depends on sprint length, working days, and hours/day, which is a team
  planning decision. Set via ``sprint_capacity_hours_per_person`` at
  construction time.
* **The full team roster** — to detect *idle* employees (people with zero
  assigned work), this module needs to know who's on the team, not just
  who happens to already be an assignee on an issue. Pass ``team_members``
  to ``compute()`` to enable this; without it, idle detection still works
  for anyone who *is* an assignee but is barely utilized, it just can't
  surface someone with literally zero issues.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.analytics.base import DEFAULT_DONE_STATUSES, safe_mean, safe_percentage
from app.integrations.jira.schemas import JiraIssue


class TeamMember(BaseModel):
    """Identifies one member of the team roster, for idle-detection purposes.

    Deliberately a separate, minimal model from
    :class:`~app.analytics.capacity_analytics.TeamMemberCapacity` — that
    model carries a specific capacity figure per person for allocation
    planning; this one is just an identity, used to detect team members
    who have no assigned work at all. Keeping them separate avoids this
    module depending on Capacity Analytics' types.
    """

    account_id: str
    display_name: str


class WorkloadStatus(str, Enum):
    """Classification of an employee's workload for this period."""

    IDLE = "idle"
    """Zero assigned issues, or utilization at/below `idle_threshold_pct`."""
    UNDER_UTILIZED = "under_utilized"
    OVERLOADED = "overloaded"
    """Utilization above `overload_threshold_pct`."""
    BALANCED = "balanced"


class EmployeeWorkload(BaseModel):
    """Workload figures for a single employee."""

    account_id: str
    display_name: str
    issue_count: int
    story_points: float
    completed_issue_count: int
    completed_story_points: float
    time_spent_hours: float
    """Sum of logged work time across assigned issues. Will be ``0.0`` for
    every employee if the Jira project doesn't use time tracking — that is
    a valid, non-error state, not a computation failure."""
    time_remaining_hours: float
    """Sum of remaining estimate across assigned issues."""
    allocated_hours: float
    """``time_spent_hours + time_remaining_hours`` — what utilization is
    measured against."""
    sprint_utilization_rate: float
    """``allocated_hours / sprint_capacity_hours_per_person * 100``."""
    status: WorkloadStatus


class WorkloadAnalyticsResult(BaseModel):
    """Team-wide workload distribution and utilization."""

    per_employee: list[EmployeeWorkload]
    """Sorted by ``story_points`` descending."""
    unassigned_issue_count: int
    unassigned_story_points: float
    total_employees: int
    avg_story_points_per_employee: float
    workload_balance_ratio: float | None
    """``max story_points / min story_points`` across employees with at least
    one point assigned. ``None`` when fewer than two such employees exist,
    or the minimum is zero (making a ratio undefined rather than merely
    large)."""
    sprint_capacity_hours_per_person: float
    """Echoes the capacity figure this result was computed against, so a
    caller displaying this data can show what it was measured relative to."""
    total_capacity_hours: float
    total_allocated_hours: float
    team_utilization_rate: float
    """Computed from ``total_allocated_hours / total_capacity_hours`` — the
    aggregate rate, not an average of individual rates, so it stays correct
    even if a future version allows per-person capacity overrides."""
    overloaded_employees: list[str]
    """Display names of employees with :attr:`WorkloadStatus.OVERLOADED`."""
    idle_employees: list[str]
    """Display names of employees with :attr:`WorkloadStatus.IDLE`."""


class WorkloadAnalyticsService:
    """Computes per-employee workload, time tracking, and utilization.

    Every threshold has a sensible default but is overridable at
    construction time, since "how much is overloaded" is a team policy
    choice, not a universal constant.

    Args:
        done_statuses: Status names counted as complete.
        sprint_capacity_hours_per_person: Hours one person can realistically
            contribute in the period being analyzed. Defaults to 60 (a
            common approximation: 6 productive hours/day over a 10-working-day
            two-week sprint) — override with ``working_days * hours_per_day``
            for the team's actual sprint length and working norms.
        idle_threshold_pct: Utilization at or below this is IDLE.
        balanced_low_threshold_pct: Utilization at or above this (and at or
            below ``overload_threshold_pct``) is BALANCED; below it (and
            above the idle threshold) is UNDER_UTILIZED.
        overload_threshold_pct: Utilization above this is OVERLOADED.
    """

    def __init__(
        self,
        done_statuses: frozenset[str] = DEFAULT_DONE_STATUSES,
        sprint_capacity_hours_per_person: float = 60.0,
        idle_threshold_pct: float = 10.0,
        balanced_low_threshold_pct: float = 50.0,
        overload_threshold_pct: float = 100.0,
    ) -> None:
        if sprint_capacity_hours_per_person <= 0:
            raise ValueError("sprint_capacity_hours_per_person must be positive")
        if not (0 <= idle_threshold_pct < balanced_low_threshold_pct < overload_threshold_pct):
            raise ValueError(
                "Thresholds must satisfy "
                "0 <= idle_threshold_pct < balanced_low_threshold_pct < overload_threshold_pct"
            )
        self._done_statuses = done_statuses
        self._sprint_capacity_hours_per_person = sprint_capacity_hours_per_person
        self._idle_threshold_pct = idle_threshold_pct
        self._balanced_low_threshold_pct = balanced_low_threshold_pct
        self._overload_threshold_pct = overload_threshold_pct

    def compute(
        self,
        issues: list[JiraIssue],
        *,
        team_members: list[TeamMember] | None = None,
    ) -> WorkloadAnalyticsResult:
        """Compute workload, time tracking, and utilization across employees.

        Args:
            issues: Any set of issues — a sprint, a backlog, a project's
                full issue list.
            team_members: The full team roster. When given, any member with
                zero assigned issues still appears in the result (correctly
                classified IDLE) instead of being silently omitted — without
                it, only people who already appear as an assignee on at
                least one issue can be reported on.

        Returns:
            A populated :class:`WorkloadAnalyticsResult`.
        """
        by_assignee: dict[str, list[JiraIssue]] = {}
        display_names: dict[str, str] = {}
        unassigned: list[JiraIssue] = []

        for issue in issues:
            if issue.assignee is None:
                unassigned.append(issue)
            else:
                by_assignee.setdefault(issue.assignee.account_id, []).append(issue)
                display_names[issue.assignee.account_id] = issue.assignee.display_name

        for member in team_members or []:
            by_assignee.setdefault(member.account_id, [])
            display_names.setdefault(member.account_id, member.display_name)

        per_employee = [
            self._build_employee_workload(account_id, display_names[account_id], assignee_issues)
            for account_id, assignee_issues in by_assignee.items()
        ]
        per_employee.sort(key=lambda employee: employee.story_points, reverse=True)

        return self._build_result(per_employee, unassigned)

    def _build_employee_workload(
        self, account_id: str, display_name: str, issues: list[JiraIssue]
    ) -> EmployeeWorkload:
        """Compute one employee's workload figures from their assigned issues."""
        completed = [issue for issue in issues if issue.status in self._done_statuses]

        story_points = round(sum(issue.story_points or 0.0 for issue in issues), 2)
        completed_points = round(sum(issue.story_points or 0.0 for issue in completed), 2)

        time_spent_hours = round(
            sum(issue.time_spent_seconds or 0 for issue in issues) / 3600, 2
        )
        time_remaining_hours = round(
            sum(issue.time_remaining_seconds or 0 for issue in issues) / 3600, 2
        )
        allocated_hours = round(time_spent_hours + time_remaining_hours, 2)
        utilization_rate = safe_percentage(
            allocated_hours, self._sprint_capacity_hours_per_person
        )

        return EmployeeWorkload(
            account_id=account_id,
            display_name=display_name,
            issue_count=len(issues),
            story_points=story_points,
            completed_issue_count=len(completed),
            completed_story_points=completed_points,
            time_spent_hours=time_spent_hours,
            time_remaining_hours=time_remaining_hours,
            allocated_hours=allocated_hours,
            sprint_utilization_rate=utilization_rate,
            status=self._classify(utilization_rate, len(issues)),
        )

    def _classify(self, utilization_rate: float, issue_count: int) -> WorkloadStatus:
        """Map a utilization rate (and issue count, for the zero-issue case) to a status."""
        if issue_count == 0 or utilization_rate <= self._idle_threshold_pct:
            return WorkloadStatus.IDLE
        if utilization_rate > self._overload_threshold_pct:
            return WorkloadStatus.OVERLOADED
        if utilization_rate < self._balanced_low_threshold_pct:
            return WorkloadStatus.UNDER_UTILIZED
        return WorkloadStatus.BALANCED

    def _build_result(
        self, per_employee: list[EmployeeWorkload], unassigned: list[JiraIssue]
    ) -> WorkloadAnalyticsResult:
        """Assemble the final result, including team-wide aggregates and balance ratio."""
        points_list = [employee.story_points for employee in per_employee]
        max_employee = per_employee[0] if per_employee else None
        min_employee = (
            min(per_employee, key=lambda employee: employee.story_points)
            if per_employee
            else None
        )

        balance_ratio: float | None = None
        if (
            max_employee is not None
            and min_employee is not None
            and min_employee.story_points > 0
        ):
            balance_ratio = round(max_employee.story_points / min_employee.story_points, 2)

        total_capacity_hours = round(
            self._sprint_capacity_hours_per_person * len(per_employee), 2
        )
        total_allocated_hours = round(
            sum(employee.allocated_hours for employee in per_employee), 2
        )

        return WorkloadAnalyticsResult(
            per_employee=per_employee,
            unassigned_issue_count=len(unassigned),
            unassigned_story_points=round(
                sum(issue.story_points or 0.0 for issue in unassigned), 2
            ),
            total_employees=len(per_employee),
            avg_story_points_per_employee=safe_mean(points_list),
            workload_balance_ratio=balance_ratio,
            sprint_capacity_hours_per_person=self._sprint_capacity_hours_per_person,
            total_capacity_hours=total_capacity_hours,
            total_allocated_hours=total_allocated_hours,
            team_utilization_rate=safe_percentage(total_allocated_hours, total_capacity_hours),
            overloaded_employees=[
                employee.display_name
                for employee in per_employee
                if employee.status is WorkloadStatus.OVERLOADED
            ],
            idle_employees=[
                employee.display_name
                for employee in per_employee
                if employee.status is WorkloadStatus.IDLE
            ],
        )