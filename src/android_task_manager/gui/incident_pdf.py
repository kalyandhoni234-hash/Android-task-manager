"""PDF rendering of an incident report (GUI layer only).

The report model and its JSON/HTML renderers are GUI-independent; PDF is
implemented here because the project's only PDF tooling lives in PySide6's
GUI extra (``QPdfWriter`` + ``QTextDocument``). The PDF is produced by
feeding the same ``html_report()`` output through Qt's rich-text engine —
one rendering source, three formats. Qt applies its own CSS subset, so the
PDF layout approximates, but does not byte-identical-match, the HTML view
(a documented limitation).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument

from ..incident.models import IncidentReport
from ..incident.renderers import html_report


def write_incident_pdf(report: IncidentReport, path: str | Path) -> None:
    """Write *report* to *path* as a PDF document. Raises on write errors.

    A4 page, 96 dpi so CSS pixel sizes map one-to-one. ``print_`` is the
    (still functional) Qt 6 API for rendering a QTextDocument to a
    QPagedPaintDevice.
    """
    writer = QPdfWriter(str(path))
    writer.setTitle(f"Android Security Investigation Report {report.metadata.report_id}")
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(96)

    document = QTextDocument()
    document.setPageSize(QSizeF(writer.width(), writer.height()))
    document.setHtml(html_report(report))
    document.print_(writer)