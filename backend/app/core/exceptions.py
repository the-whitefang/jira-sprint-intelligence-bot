"""Application-wide exception hierarchy.

Every domain/service-layer error in the codebase should raise one of these
exceptions rather than a bare ``Exception`` or a framework-specific
``HTTPException``. This keeps the service layer free of any HTTP
knowledge (services shouldn't know what a status code is — that's a
presentation-layer concern) while still letting the presentation layer
(``app/middleware/error_handler.py``) map each exception to a precise,
consistent HTTP response.

Each exception carries:

* ``error_code`` — a stable, machine-readable string the frontend can
  branch on (e.g. to show a specific UI state), independent of the
  human-readable ``message``, which may change wording over time.
* ``status_code`` — the HTTP status the error handler should translate
  this into.
* ``details`` — optional structured context (e.g. which field failed)
  for richer client-side handling, without polluting ``message``.
"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Base class for all application-raised exceptions.

    Args:
        message: Human-readable description, safe to show to end users.
        error_code: Stable machine-readable identifier, e.g.
            ``"SPRINT_NOT_FOUND"``. Defaults to the class name in
            SCREAMING_SNAKE_CASE-ish form if not provided.
        status_code: HTTP status code the error handler will return.
        details: Optional structured extra context for the client.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundException(AppException):
    """Raised when a requested resource does not exist.

    Maps to HTTP 404. Also used for authorization-by-obscurity cases
    (e.g. a chat session that exists but isn't owned by the caller),
    per the API design's convention of not confirming existence of
    resources the caller shouldn't know about.
    """

    status_code = 404
    error_code = "NOT_FOUND"


class ValidationException(AppException):
    """Raised for business-rule validation failures beyond basic schema checks.

    Pydantic/FastAPI already handles field-shape validation (type,
    required-ness) and returns 422 automatically. This exception is for
    *semantic* validation that requires business logic — e.g. "sprint
    end_date must be after start_date" — which can't be expressed as a
    pure Pydantic field constraint.
    """

    status_code = 422
    error_code = "VALIDATION_ERROR"


class UnauthorizedException(AppException):
    """Raised when authentication is missing or invalid.

    Maps to HTTP 401. Distinct from :class:`ForbiddenException`: this
    means "we don't know who you are," not "we know who you are and
    you're not allowed."
    """

    status_code = 401
    error_code = "UNAUTHORIZED"


class ForbiddenException(AppException):
    """Raised when an authenticated caller lacks permission for an action.

    Maps to HTTP 403.
    """

    status_code = 403
    error_code = "FORBIDDEN"


class ConflictException(AppException):
    """Raised on state conflicts — duplicate unique keys, concurrent
    modification, or an operation that's invalid given the resource's
    current state (e.g. starting a Jira sync while one is already running).

    Maps to HTTP 409.
    """

    status_code = 409
    error_code = "CONFLICT"


class RateLimitExceededException(AppException):
    """Raised when a caller exceeds a rate limit or quota.

    Maps to HTTP 429. Used both for auth throttling (login attempts) and
    for the Gemini daily-query quota per user described in the API design.
    """

    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"


class ExternalServiceException(AppException):
    """Raised when a downstream dependency (Gemini, Jira, ChromaDB) fails
    or is unavailable after retries are exhausted.

    Maps to HTTP 502. Kept distinct from :class:`AppException`'s generic
    500 default so operators can immediately tell "our bug" apart from
    "a vendor is down" in logs and alerts.
    """

    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"


class DatabaseException(AppException):
    """Raised when a database operation fails in a way that should be
    surfaced as a clean error rather than an unhandled 500 with a raw
    SQLAlchemy traceback leaking to the client.

    Maps to HTTP 500. The original SQLAlchemy exception should still be
    logged (with traceback) by the repository layer before this is
    raised — this exception is what crosses the service/presentation
    boundary.
    """

    status_code = 500
    error_code = "DATABASE_ERROR"
