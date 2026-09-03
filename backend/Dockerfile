# ---------------------------------------------------------------------------
# Jira Sprint Intelligence Bot — Backend Dockerfile
#
# Multi-stage build:
#   1. "builder"  — installs build tools + compiles wheels (asyncmy has C
#                    extensions and needs a compiler + MySQL client headers).
#   2. "runtime"  — slim final image containing only the installed
#                    packages and application code, run as a non-root user.
#
# This keeps the final image free of compilers/build headers, which
# reduces both image size and attack surface.
# ---------------------------------------------------------------------------

# --- Stage 1: builder --------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Build dependencies needed to compile asyncmy and other C-extension deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Build wheels rather than installing directly, so the runtime stage can
# install from prebuilt wheels without needing a compiler at all.
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


# --- Stage 2: runtime ----------------------------------------------------
FROM python:3.12-slim AS runtime

# Runtime-only shared libraries (no compiler, no headers).
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-mysql-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — the process should never run as root in production.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY ./app ./app
COPY ./alembic ./alembic
COPY ./alembic.ini .

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# gunicorn manages uvicorn worker processes — standard production pattern
# for running an async ASGI app with multiple worker processes per container.
CMD ["gunicorn", "app.main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
