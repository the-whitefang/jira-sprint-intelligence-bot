"""JQL string generation.

This module has exactly one job: turn a validated
:class:`~app.integrations.jira.jql.filters.JQLFilter` into a JQL string
that means what the filter says and nothing else. Every value that ends
up inside a JQL string literal goes through :func:`_escape_jql_literal`
first — this is the JQL equivalent of parameterized queries in SQL, and
it's what keeps a value like ``O'Brien`` or a status name containing a
quote from breaking out of its literal and altering the query.

``build_jql`` is a pure function (no I/O, no side effects) specifically
so it can be unit tested and reasoned about independently of anything
that executes the result — see ``service.py`` for execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.integrations.jira.jql.filters import JQLFilter, SORTABLE_FIELDS

# Jira's JQL date literal format: quoted "yyyy-MM-dd HH:mm".
_JQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def _escape_jql_literal(value: str) -> str:
    """Escape and quote a single JQL string literal.

    JQL string literals use double quotes, with ``\\`` and ``"`` as the
    only two characters requiring backslash-escaping inside them (per
    Atlassian's JQL grammar). Every filter value that becomes part of a
    literal must pass through this function — this is the single
    chokepoint that prevents JQL injection via filter values.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _in_clause(field: str, values: Sequence[str]) -> str:
    """Build a ``field IN ("a", "b", "c")`` clause with every value escaped."""
    literals = ", ".join(_escape_jql_literal(value) for value in values)
    return f"{field} IN ({literals})"


def _format_jql_datetime(value: datetime) -> str:
    """Format a datetime as an escaped JQL date literal."""
    return _escape_jql_literal(value.strftime(_JQL_DATETIME_FORMAT))


def build_jql(filter_: JQLFilter) -> str:
    """Generate a JQL query string from a validated :class:`JQLFilter`.

    Args:
        filter_: The structured filter to translate. Already validated
            by Pydantic (e.g. ``sort_by`` is guaranteed to be a key in
            :data:`SORTABLE_FIELDS`, and ``unassigned``/
            ``assignee_account_ids`` are guaranteed not to conflict) —
            this function trusts that validation rather than re-checking it.

    Returns:
        A JQL string. May be empty (before any ``ORDER BY``) if the
        filter has no conditions set — Jira's search API treats an empty
        JQL string as "match everything visible to the caller."

    Example:
        >>> build_jql(JQLFilter(projects=["ENG"], statuses=["To Do", "In Progress"]))
        'project IN ("ENG") AND status IN ("To Do", "In Progress")'
    """
    clauses: list[str] = []

    if filter_.projects:
        clauses.append(_in_clause("project", filter_.projects))
    if filter_.statuses:
        clauses.append(_in_clause("status", filter_.statuses))
    if filter_.priorities:
        clauses.append(_in_clause("priority", filter_.priorities))

    if filter_.unassigned:
        clauses.append("assignee IS EMPTY")
    elif filter_.assignee_account_ids:
        clauses.append(_in_clause("assignee", filter_.assignee_account_ids))

    if filter_.sprint_id is not None:
        # Safe to interpolate directly: Pydantic guarantees this is an
        # int, not caller-supplied text, so there is no literal to escape
        # and no injection surface.
        clauses.append(f"sprint = {filter_.sprint_id}")

    for date_filter in filter_.date_filters:
        if date_filter.date_from is not None:
            clauses.append(f"{date_filter.field} >= {_format_jql_datetime(date_filter.date_from)}")
        if date_filter.date_to is not None:
            clauses.append(f"{date_filter.field} <= {_format_jql_datetime(date_filter.date_to)}")

    if filter_.extra_jql:
        # Wrapped in parentheses so its internal OR/AND precedence can't
        # silently reshape the clauses generated above.
        clauses.append(f"({filter_.extra_jql})")

    jql = " AND ".join(clauses)

    if filter_.sort_by is not None:
        order_field = SORTABLE_FIELDS[filter_.sort_by]
        order_clause = f"ORDER BY {order_field} {filter_.sort_direction}"
        jql = f"{jql} {order_clause}".strip()

    return jql
