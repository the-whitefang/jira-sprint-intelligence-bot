"""SQLAlchemy models for Jira projects and sprints.

This is the persisted, queryable cache of Jira data described in the
database architecture design — populated by the future sync worker
(``app/workers/jira_sync_worker.py``), read by the analytics engine and
the API layer. Corresponds to the ``projects`` and ``sprints`` tables
from the MySQL schema designed earlier.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """A Jira project, keyed by its natural Jira key (e.g. ``"ENG"``)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    jira_project_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    sprints: Mapped[list[Sprint]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Sprint(Base, TimestampMixin):
    """A Jira sprint belonging to one project."""

    __tablename__ = "sprints"
    __table_args__ = (Index("ix_sprints_project_id_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    jira_sprint_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    project: Mapped[Project] = relationship(back_populates="sprints")
    # "Ticket" is defined in app.modules.tickets.models — a different
    # module. Referencing it by string name here (rather than importing
    # it directly) avoids a circular import, since Ticket's own
    # `sprint` relationship refers back to `Sprint` the same way.
    # app/db/import_models.py ensures both modules are imported before
    # any relationship needs to resolve.
    #
    # cascade + passive_deletes: when a Project is deleted, the ORM
    # cascades to its Sprints (see Project.sprints); without this same
    # configuration here, the ORM would then try to satisfy Ticket's
    # NOT NULL sprint_id by setting it to NULL rather than deleting the
    # ticket, which fails outright. passive_deletes=True tells the ORM
    # to defer entirely to the database's own ON DELETE CASCADE on
    # `tickets.sprint_id` instead of managing this in Python.
    tickets: Mapped[list["Ticket"]] = relationship(  # noqa: F821
        back_populates="sprint", cascade="all, delete-orphan", passive_deletes=True
    )
