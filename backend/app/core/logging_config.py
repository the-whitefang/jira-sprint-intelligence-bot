"""Structured logging configuration.

Provides a single :func:`configure_logging` entry point, called once from
the application's lifespan startup hook. All application code should use
``logging.getLogger(__name__)`` as usual afterward — this module only sets
up *how* logs are formatted and routed, not what individual modules log.

Design decisions:

* **JSON logs in staging/production, human-readable logs in development.**
  JSON is what log aggregators (CloudWatch, Datadog, ELK) expect; a plain
  formatter is far faster to read during local development.
* **A request ID is injected into every log line** via a
  :class:`logging.Filter` reading from a ``contextvar``, so every log
  emitted while handling a given HTTP request can be correlated — this is
  set by the request-ID middleware in ``app/middleware/error_handler.py``.
* **Uvicorn's own loggers are re-parented** to the same handlers/formatters
  so access logs and application logs are consistent, instead of
  uvicorn's default lines looking different from the app's own output.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger import jsonlogger

from app.core.config import Environment, Settings

# Populated per-request by the request-ID middleware; read here so every
# log record can carry the correlating ID without every call site having
# to pass it explicitly.
request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Attach the current request's correlation ID to each log record.

    If no request is in flight (e.g. a startup log or a background job),
    ``request_id`` is emitted as ``"-"`` so the field is always present
    and log queries can rely on it existing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get() or "-"
        return True


class _JsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter with a consistent, predictable field set.

    A fixed field order/name set matters for log aggregators that build
    indexes or dashboards off specific field names — renaming fields
    between deploys silently breaks those.
    """

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["request_id"] = getattr(record, "request_id", "-")
        # Ensure a consistent ISO-8601 timestamp field name across all logs.
        if "timestamp" not in log_record:
            log_record["timestamp"] = self.formatTime(record, self.datefmt)


_HUMAN_READABLE_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | request_id=%(request_id)s | %(message)s"
)


def configure_logging(settings: Settings) -> None:
    """Configure the root logger and re-parent framework loggers to match.

    Must be called exactly once, early in application startup, before any
    other module-level logging occurs. Idempotent-safe: calling it again
    (e.g. in tests) simply replaces the handler set rather than stacking
    duplicate handlers.

    Args:
        settings: The validated application settings, used to select log
            level and output format (JSON vs. human-readable) based on
            ``settings.LOG_LEVEL`` and ``settings.ENVIRONMENT``.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL.value)

    # Remove any handlers configured by prior calls or by imported
    # libraries, so we have full, deterministic control of output.
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(RequestIdFilter())

    if settings.ENVIRONMENT is Environment.DEVELOPMENT:
        handler.setFormatter(logging.Formatter(_HUMAN_READABLE_FORMAT))
    else:
        handler.setFormatter(_JsonFormatter())

    root_logger.addHandler(handler)

    # Re-parent uvicorn's loggers onto the root logger's handler instead of
    # letting uvicorn manage its own separate formatting — keeps every log
    # line (access logs included) in the same shape.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # SQLAlchemy's engine logger is noisy at INFO; only enable it when the
    # operator has explicitly asked for SQL echo via DB_ECHO.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )

    logging.getLogger(__name__).info(
        "logging_configured",
        extra={
            "environment": settings.ENVIRONMENT.value,
            "log_level": settings.LOG_LEVEL.value,
        },
    )
