"""FastAPI dependency-injection wiring for the Jira integration.

The :class:`~app.integrations.jira.client.JiraClient` wraps a single
pooled ``httpx.AsyncClient`` connection, so — like a database engine or
Redis pool — it must be constructed exactly once per process and reused,
not rebuilt on every request. It is created in ``app/main.py``'s
``lifespan`` startup hook and stored on ``app.state``; this module just
exposes the FastAPI-idiomatic way to retrieve it in a route.
"""

from __future__ import annotations

from fastapi import Request

from app.integrations.jira.client import JiraClient


def get_jira_client(request: Request) -> JiraClient:
    """Return the process-wide :class:`JiraClient` created at application startup.

    Use as a FastAPI dependency:

    .. code-block:: python

        from fastapi import Depends
        from app.integrations.jira.client import JiraClient
        from app.integrations.jira.dependencies import get_jira_client

        @router.get("/example")
        async def example(jira: JiraClient = Depends(get_jira_client)) -> dict:
            projects = await jira.projects.list_projects()
            return {"count": len(projects)}
    """
    return request.app.state.jira_client
