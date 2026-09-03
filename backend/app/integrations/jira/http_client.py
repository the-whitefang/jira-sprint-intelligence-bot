"""Low-level async HTTP client for the Jira Cloud REST API.

This is the single file in the codebase that knows about Jira's raw HTTP
semantics — base URL, authentication, retry/backoff, rate-limit handling,
and status-code-to-exception mapping. Every resource client under
``resources/`` is built on top of this and never imports ``httpx``
directly, mirroring how ``app/modules/ai_insights/gemini_client.py``
isolates the Gemini SDK as the sole import point for that vendor. If Jira
ever changes API versions or the client library changes, this is the only
file that needs to change.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.integrations.jira.exceptions import (
    JiraAuthenticationError,
    JiraConnectionError,
    JiraIntegrationError,
    JiraNotFoundError,
    JiraRateLimitError,
    JiraServerError,
)

logger = logging.getLogger(__name__)

# Only transient failures are retried. Authentication failures and generic
# 4xx client errors are not — retrying those wastes the retry budget on a
# request that will fail identically every time.
_RETRYABLE_EXCEPTIONS = (JiraRateLimitError, JiraServerError, JiraConnectionError)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Wait according to Jira's ``Retry-After`` header when it's given us one.

    Plain exponential backoff is a reasonable default when we're guessing
    at how long a failure might last, but a 429 response tells us exactly
    how long to wait via ``Retry-After`` — ignoring that and backing off
    on our own schedule either waits longer than necessary (wasting time)
    or retries before Jira's rate-limit window has actually reset
    (guaranteeing another 429. Falls back to exponential backoff + jitter
       for server errors and connection failures, which carry no such hint.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, JiraRateLimitError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=20)(retry_state)


class JiraHTTPClient:
    """Thin async wrapper around a single ``httpx.AsyncClient`` scoped to one Jira site.

    One instance is created per application process (see
    ``app/integrations/jira/dependencies.py``) and its connection pool is
    reused across every request — it should not be constructed per-request.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.JIRA_BASE_URL.rstrip("/"),
            auth=httpx.BasicAuth(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
            timeout=settings.JIRA_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
        )
        # Built once per instance (not as a class-level decorator) so the
        # retry attempt count is driven by settings.JIRA_MAX_RETRIES rather
        # than a value baked in at import time.
        self._retrying = AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            stop=stop_after_attempt(settings.JIRA_MAX_RETRIES),
            wait=_wait_strategy,
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

    async def aclose(self) -> None:
        """Release the underlying connection pool. Call once, on app shutdown."""
        await self._client.aclose()

    async def __aenter__(self) -> JiraHTTPClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """Perform one Jira API call, with retry/backoff on transient failures.

        Args:
            method: HTTP method, e.g. ``"GET"``.
            path: Path relative to the Jira base URL, e.g.
                ``"/rest/api/3/project/search"``.
            params: Optional query parameters.
            json: Optional JSON request body.

        Returns:
            The parsed JSON response body — a dict for most endpoints, but
            a bare list for the handful (e.g. ``/user/search``) that
            return a JSON array directly — or ``None`` for an empty/204
            response.

        Raises:
            JiraAuthenticationError: Credentials were rejected (401/403).
                Not retried.
            JiraNotFoundError: The resource doesn't exist (404). Not retried.
            JiraRateLimitError: Jira returned 429. Retried up to
                ``settings.JIRA_MAX_RETRIES`` times with exponential
                backoff + jitter before this is raised to the caller.
            JiraServerError: Jira returned 5xx. Retried like rate limits.
            JiraConnectionError: A network-level failure (timeout, DNS,
                connection refused). Retried like rate limits.
            JiraIntegrationError: Any other non-2xx response. Not retried.
        """
        return await self._retrying(self._do_request, method, path, params, json)

    async def _do_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
    ) -> dict[str, Any] | list[Any] | None:
        """Perform exactly one HTTP attempt and map the outcome to our exception hierarchy.

        Kept separate from :meth:`request` so :attr:`_retrying` has a plain
        async function to call repeatedly — tenacity retries by re-invoking
        this method, not by re-entering ``request`` (which would rebuild
        the retry context on every attempt).
        """
        try:
            response = await self._client.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            raise JiraConnectionError(f"Timed out calling Jira: {method} {path}") from exc
        except httpx.ConnectError as exc:
            raise JiraConnectionError(f"Could not connect to Jira: {method} {path}") from exc
        except httpx.TransportError as exc:
            raise JiraConnectionError(f"Transport error calling Jira: {method} {path}") from exc

        if response.status_code in (401, 403):
            raise JiraAuthenticationError(
                f"Jira rejected credentials for {method} {path} (status {response.status_code})",
                details={"status_code": response.status_code},
            )
        if response.status_code == 404:
            raise JiraNotFoundError(f"Jira resource not found: {method} {path}")
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response)
            raise JiraRateLimitError(
                f"Jira rate limit hit for {method} {path}",
                retry_after=retry_after,
                details={"retry_after": retry_after},
            )
        if response.status_code >= 500:
            raise JiraServerError(
                f"Jira server error {response.status_code} for {method} {path}",
                details={"status_code": response.status_code},
            )
        if response.status_code >= 400:
            # Any other 4xx: a genuine bad-request-shaped problem (e.g. an
            # invalid JQL query) that retrying will not fix.
            raise JiraIntegrationError(
                f"Jira returned {response.status_code} for {method} {path}: "
                f"{response.text[:500]}",
                details={"status_code": response.status_code},
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """Parse Jira's ``Retry-After`` header, defaulting to 1 second if absent/invalid."""
        raw = response.headers.get("Retry-After")
        try:
            return float(raw) if raw is not None else 1.0
        except ValueError:
            return 1.0

    async def paginate(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        values_key: str = "values",
        page_size: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterate every item across every page of a paginated Jira endpoint.

        Jira's REST APIs use two slightly different pagination shapes
        depending on which API family the endpoint belongs to:

        * The **Agile API** (boards, sprints) returns
          ``{"values": [...], "startAt", "maxResults", "isLast"}``.
        * The **core/search API** (issues) returns
          ``{"issues": [...], "startAt", "maxResults", "total"}``.

        This method handles both by accepting ``values_key`` to select
        which field holds the page's items, and by checking for whichever
        of ``isLast``/``total`` the response actually provides.

        Args:
            method: HTTP method for each page request.
            path: Path relative to the Jira base URL.
            params: Query parameters applied to every page (``startAt``
                and ``maxResults`` are added automatically — do not
                include them here).
            values_key: The JSON key holding the page's item list —
                ``"values"`` for Agile API endpoints, ``"issues"`` for
                search endpoints.
            page_size: Results requested per underlying page. Defaults to
                ``settings.JIRA_PAGE_SIZE`` when not given; callers doing
                a one-off bulk fetch (e.g.
                :meth:`~app.integrations.jira.jql.service.JQLService.search_all`)
                can pass a larger value to reduce the number of round
                trips.

        Yields:
            One raw (still-un-normalized) item dict per Jira record,
            across all pages, in order.
        """
        start_at = 0
        effective_page_size = page_size or self._settings.JIRA_PAGE_SIZE
        base_params = dict(params or {})

        while True:
            page_params = {**base_params, "startAt": start_at, "maxResults": effective_page_size}
            page = await self.request(method, path, params=page_params)
            if page is None:
                return
            assert isinstance(page, dict), (
                f"paginate() requires a dict-shaped response with a '{values_key}' "
                f"key; got {type(page).__name__} from {method} {path}"
            )

            items = page.get(values_key, [])
            for item in items:
                yield item

            if not items:
                return

            start_at += len(items)
            is_last = page.get("isLast")
            total = page.get("total")

            if is_last is not None:
                if is_last:
                    return
            elif total is not None:
                if start_at >= total:
                    return
            # Neither pagination signal present: stop once a short page
            # (fewer items than requested) is seen, as a last-resort
            # termination condition so this can never loop forever.
            elif len(items) < effective_page_size:
                return

    async def test_connection(self) -> bool:
        """Verify credentials and connectivity via Jira's ``/myself`` endpoint.

        This is the cheapest authenticated call Jira Cloud offers, which
        makes it the right choice for a startup connectivity check or an
        admin-facing "test Jira connection" action — it confirms both
        network reachability and that the configured API token is valid,
        without touching any real project data.

        Returns:
            ``True`` if the call succeeds, ``False`` if any
            :class:`JiraIntegrationError` occurs. Does not raise — callers
            that need the failure reason should call
            ``request("GET", "/rest/api/3/myself")`` directly instead.
        """
        try:
            await self.request("GET", "/rest/api/3/myself")
        except JiraIntegrationError:
            logger.warning("jira_connection_test_failed", exc_info=True)
            return False
        return True