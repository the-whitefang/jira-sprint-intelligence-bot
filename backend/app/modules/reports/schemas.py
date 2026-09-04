"""Pydantic schemas for the reporting module."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReportType(str, Enum):
    """The types of reports that can be generated."""
    DAILY = "daily"
    WEEKLY = "weekly"
    SPRINT_SUMMARY = "sprint_summary"
    VELOCITY = "velocity"
    WORKLOAD = "workload"
    RISK = "risk"


class ExportFormat(str, Enum):
    """The supported export formats."""
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"


class ReportRequest(BaseModel):
    """Payload to request the generation of a report."""
    report_type: ReportType
    export_format: ExportFormat
    sprint_id: int | None = Field(
        default=None, 
        description="Optional sprint ID for sprint-specific reports like Sprint Summary or Workload."
    )
    # Could add date ranges, team IDs, etc., but keeping it simple for the initial implementation.


class ReportData(BaseModel):
    """An internal structure used to pass gathered data to the generators."""
    title: str
    description: str
    headers: list[str]
    rows: list[dict[str, Any]]
