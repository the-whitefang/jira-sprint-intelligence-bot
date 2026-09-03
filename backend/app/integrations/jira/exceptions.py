"""Jira integration exception hierarchy.

Every exception here subclasses :class:`app.core.exceptions.ExternalServiceException`,
so the global exception handler (``app/middleware/error_handler.py``) already
knows how to turn any of these into a clean HTTP 502 without any Jira-specific
code in the presentation layer — that mapping is free.

This module exists on top of that for a narrower reason: callers *inside*
the integration (the retry logic in ``http_client.py``, and later the
ingestion worker) need to distinguish *why* a Jira call failed, because the
right response differs by cause:

* A rate limit or transient server error should be retried.
* An authentication failure should not be retried — retrying with the same
  bad credentials just wastes time and hits Jira's rate limit harder.
* A 404 means the resource is gone, not that Jira is unhappy.
"""

from __future__ import annotations

from app.core.exceptions import ExternalServiceException


class JiraIntegrationError(ExternalServiceException):
    """Base class for all Jira integration failures.

    Catch this in calling code (e.g. the future ingestion worker) to handle
    "something about Jira went wrong" generically, or catch one of the
    subclasses below to handle a specific failure mode.
    """

    error_code = "JIRA_INTEGRATION_ERROR"


class JiraAuthenticationError(JiraIntegrationError):
    """Jira rejected the configured email/API token (HTTP 401/403).

    Deliberately **not** in the retryable set (see ``http_client.py``) —
    retrying an auth failure with the same credentials will just fail
    again and burn through the retry budget for no benefit.
    """

    error_code = "JIRA_AUTHENTICATION_ERROR"


class JiraNotFoundError(JiraIntegrationError):
    """The requested Jira resource (project/board/sprint/issue/user) doesn't exist.

    Maps to 502 (not 404) at the HTTP layer, per :class:`ExternalServiceException`
    — from our API's perspective this is an upstream data problem, not a
    missing resource in *our* system. Callers that need to translate this
    into a domain-level "not found" (e.g. a sync job skipping a deleted
    ticket) should catch this specifically and decide what that means for
    their own data.
    """

    error_code = "JIRA_NOT_FOUND"


class JiraRateLimitError(JiraIntegrationError):
    """Jira responded with HTTP 429.

    In the retryable set. Carries ``retry_after`` (seconds, from Jira's
    ``Retry-After`` header when present) so retry/backoff logic can honor
    what Jira actually asked for instead of guessing.
    """

    error_code = "JIRA_RATE_LIMIT_EXCEEDED"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after


class JiraServerError(JiraIntegrationError):
    """Jira returned a 5xx — their side is having a problem, not ours.

    In the retryable set, since these are typically transient.
    """

    error_code = "JIRA_SERVER_ERROR"


class JiraConnectionError(JiraIntegrationError):
    """A network-level failure talking to Jira (timeout, DNS, connection refused).

    In the retryable set.
    """

    error_code = "JIRA_CONNECTION_ERROR"
