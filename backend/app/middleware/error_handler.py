"""Global exception handling and request correlation middleware.

This module is responsible for the presentation-layer half of error
handling: it catches whatever the service/repository layers raise
(:mod:`app.core.exceptions`), whatever FastAPI/Pydantic raises
(validation errors, ``HTTPException``), and anything unexpected, then
converts all of it into the single consistent error envelope used across
every endpoint in the API design:

.. code-block:: json

    {"error_code": "SPRINT_NOT_FOUND", "message": "...", "request_id": "..."}

It also installs a request-ID middleware: every incoming request is
tagged with a UUID, exposed to clients via the ``X-Request-ID`` response
header and to logs via the contextvar consumed in
``app/core/logging_config.py``. This is what lets a client-reported bug
("I got an error") be matched to exact server-side logs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import AppException
from app.core.logging_config import request_id_ctx_var

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a unique correlation ID to every request.

    The ID is stored in a contextvar (read by the logging formatter) and
    echoed back as the ``X-Request-ID`` response header, so a value
    visible to the client can be handed to support/engineering to look up
    exactly what happened server-side for that request.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_ctx_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _error_envelope(error_code: str, message: str) -> dict[str, str]:
    """Build the standard error response body.

    Centralized so every handler below produces byte-for-byte the same
    shape — the frontend should never need a special case per error type.
    """
    request_id = request_id_ctx_var.get() or "-"
    return {"error_code": error_code, "message": message, "request_id": request_id}


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI app.

    Called once from the application factory
    (``app/main.py::create_app``). Handler registration order does not
    matter to FastAPI (it dispatches by exception type specificity), but
    they're declared here from most-specific to least-specific for
    readability.

    Args:
        app: The FastAPI application instance to attach handlers to.
    """

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        """Handle every custom domain exception raised by services/repos."""
        log_fn = logger.warning if exc.status_code < 500 else logger.error
        log_fn(
            "app_exception",
            extra={
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "path": request.url.path,
                "details": exc.details,
            },
            exc_info=exc.status_code >= 500,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.error_code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic/FastAPI request validation failures (422).

        Kept in FastAPI's native field-error shape (not the generic
        envelope) per the API design's cross-cutting convention, so
        frontend form validation can key off ``loc``/``msg`` per field.
        """
        logger.info(
            "validation_error",
            extra={"path": request.url.path, "errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "request_id": request_id_ctx_var.get() or "-",
                "field_errors": exc.errors(),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle framework-level HTTP exceptions (e.g. 404 on unknown route)."""
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(f"HTTP_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all for anything not explicitly handled above.

        This is the last line of defense: it guarantees the API never
        leaks a raw traceback or framework error page to a client. The
        full exception is logged server-side with a traceback; the
        client only ever sees a generic message plus the request ID
        needed to look that traceback up.
        """
        logger.error(
            "unhandled_exception",
            extra={"path": request.url.path},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope(
                "INTERNAL_ERROR",
                "An unexpected error occurred. Please try again or contact support.",
            ),
        )
