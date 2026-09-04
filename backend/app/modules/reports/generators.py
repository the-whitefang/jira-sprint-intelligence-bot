"""Report generators for converting data into CSV, Excel, and PDF formats."""

import io
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    
from app.modules.reports.schemas import ReportData


class ReportGenerator:
    """Handles the conversion of structured ReportData into exportable file streams."""

    @staticmethod
    def generate_csv(data: ReportData) -> io.BytesIO:
        """Generate a CSV file stream."""
        df = pd.DataFrame(data.rows, columns=data.headers)
        output = io.BytesIO()
        # pandas to_csv writes strings, so we need to encode it to bytes or use a StringIO,
        # but FastAPI's StreamingResponse works well with BytesIO.
        # We can write to memory and return it.
        csv_string = df.to_csv(index=False)
        output.write(csv_string.encode("utf-8"))
        output.seek(0)
        return output

    @staticmethod
    def generate_excel(data: ReportData) -> io.BytesIO:
        """Generate an Excel (.xlsx) file stream."""
        df = pd.DataFrame(data.rows, columns=data.headers)
        output = io.BytesIO()
        
        # Use pandas with the openpyxl engine
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Report", index=False)
            
            # Optional: auto-adjust column widths
            worksheet = writer.sheets["Report"]
            for col in worksheet.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except Exception:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column].width = adjusted_width
                
        output.seek(0)
        return output

    @staticmethod
    def generate_pdf(data: ReportData) -> io.BytesIO:
        """Generate a PDF file stream using Jinja2 and WeasyPrint."""
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("WeasyPrint is not installed or available on this system.")
            
        # 1. Setup Jinja2 environment to load templates
        # We assume templates are stored in app/templates/reports
        # For safety, resolve relative to the current file's parent path.
        base_dir = Path(__file__).resolve().parent.parent.parent
        template_dir = base_dir / "templates" / "reports"
        
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("report.html")
        
        # 2. Render the HTML with our data
        html_out = template.render(
            title=data.title,
            description=data.description,
            headers=data.headers,
            rows=data.rows
        )
        
        # 3. Convert to PDF
        output = io.BytesIO()
        HTML(string=html_out).write_pdf(output)
        output.seek(0)
        
        return output
