"""Dependencies for non-blocking audit logging."""

import logging
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.audit.models import AuditLog

logger = logging.getLogger(__name__)


async def _write_audit_log(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    resource_name: str | None,
    ip_address: str | None,
) -> None:
    """The actual async function executed in the background."""
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource_name=resource_name,
            ip_address=ip_address,
        )
        session.add(log)
        await session.commit()
    except Exception as e:
        # We catch and log this so an audit failure doesn't crash the BackgroundTask loop
        logger.error(f"Failed to write audit log: {e}")


class AuditLogger:
    """FastAPI Dependency to easily emit audit logs without blocking the response."""
    
    def __init__(
        self,
        request: Request,
        background_tasks: BackgroundTasks,
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        self.request = request
        self.background_tasks = background_tasks
        self.session = session

    def log(
        self, action: str, resource_name: str | None = None, user_id: int | None = None
    ) -> None:
        """Enqueue an audit log to be written after the response is sent."""
        ip_address = self.request.client.host if self.request.client else None
        
        self.background_tasks.add_task(
            _write_audit_log,
            self.session,
            user_id,
            action,
            resource_name,
            ip_address,
        )


def get_audit_logger(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLogger:
    """Injectable factory for AuditLogger."""
    return AuditLogger(request, background_tasks, session)
