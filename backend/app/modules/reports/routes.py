"""REST API routes for downloading reports."""

from typing import Annotated
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.modules.auth.dependencies import RequirePermission
from app.modules.reports.generators import ReportGenerator, WEASYPRINT_AVAILABLE
from app.modules.reports.schemas import ExportFormat, ReportRequest, ReportType
from app.modules.reports.service import ReportService, get_report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/download")
async def download_report(
    report_type: ReportType = Query(..., description="The type of report to generate"),
    export_format: ExportFormat = Query(..., description="The file format for the export"),
    sprint_id: int | None = Query(None, description="Optional sprint ID filter"),
    report_service: ReportService = Depends(get_report_service),
    # Ensure the caller has read access to reports
    _user = Depends(RequirePermission(["report:read"])),
) -> StreamingResponse:
    """Generate and stream a report on the fly."""
    
    if export_format == ExportFormat.PDF and not WEASYPRINT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF generation is currently unavailable on this server."
        )

    # 1. Gather the structured data
    req = ReportRequest(
        report_type=report_type,
        export_format=export_format,
        sprint_id=sprint_id
    )
    data = await report_service.build_report_data(req)
    
    # 2. Generate the file stream
    if export_format == ExportFormat.CSV:
        stream = ReportGenerator.generate_csv(data)
        media_type = "text/csv"
        ext = "csv"
    elif export_format == ExportFormat.EXCEL:
        stream = ReportGenerator.generate_excel(data)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif export_format == ExportFormat.PDF:
        stream = ReportGenerator.generate_pdf(data)
        media_type = "application/pdf"
        ext = "pdf"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format.")
        
    # 3. Stream back to client
    # Clean up title for filename
    safe_title = urllib.parse.quote(data.title.replace(" ", "_").lower())
    filename = f"{safe_title}.{ext}"
    
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename}"}
    )
