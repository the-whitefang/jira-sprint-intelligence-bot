"""Shared utilities and value objects for the analytics engine.

Every module in ``app/analytics/`` is a pure computation layer: no Jira
API calls, no database access, no Gemini calls (explicitly out of scope
for this build — see each module's docstring). Each module takes
already-fetched data — Jira integration models like
:class:`~app.integrations.jira.schemas.JiraIssue`, or plain values the
caller supplies — and returns a structured Pydantic result. That is what
makes each module independently usable and independently testable: a
caller can construct a handful of ``JiraIssue`` objects by hand and
assert on the output, with no mocking of any kind required, and no
module in this package imports another.

This module holds the small set of things every analytics module would
otherwise duplicate: a default "done" status set, a shared risk-severity
scale, and numeric helpers that avoid division-by-zero without littering
every module with the same guard clause. Importing this module is not
considered a violation of "each module is independent" — it is a shared
kernel of genuinely common, side-effect-free utilities, not shared
business logic.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from statistics import mean, median

# Jira workflows are configured per-project/per-site, so there is no
# universally correct set of "done" status names. This is the sensible
# default most out-of-the-box Jira workflows use; every module that needs
# it accepts a `done_statuses` parameter defaulting to this constant, so
# a caller with a customized workflow can override it without editing
# this package.
DEFAULT_DONE_STATUSES: frozenset[str] = frozenset({"Done", "Closed", "Resolved"})


class RiskLevel(str, Enum):
    """Shared severity scale used by every analytics module that classifies risk."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def safe_percentage(part: float, whole: float) -> float:
    """Return ``part / whole * 100``, rounded to 1 decimal place, or 0.0 if ``whole <= 0``.

    Nearly every analytics module computes multiple percentages
    (completion rate, bug ratio, utilization, estimate coverage, ...)
    against a denominator that can legitimately be zero — an empty
    sprint, a backlog with no bugs, a team with no configured capacity.
    Centralizing the zero-guard here means no module repeats it, and no
    module can accidentally raise ``ZeroDivisionError`` on an empty input.
    """
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100, 1)


def safe_mean(values: Iterable[float]) -> float:
    """``statistics.mean``, returning ``0.0`` for an empty input instead of raising."""
    materialized = list(values)
    return round(mean(materialized), 2) if materialized else 0.0


def safe_median(values: Iterable[float]) -> float:
    """``statistics.median``, returning ``0.0`` for an empty input instead of raising."""
    materialized = list(values)
    return round(median(materialized), 2) if materialized else 0.0
