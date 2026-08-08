"""Renders plain resume text into a minimal single-column PDF, for the "PDF
attachment" resume-delivery mode (decision #21). Deliberately bare — a
properly designed resume template/layout is a separate design task, this
exists so the delivery-mode toggle has something real behind it rather than
staying UI-only.
"""

import os
import tempfile

from fpdf import FPDF


def render_resume_pdf(resume_text, out_path=None):
    """Writes a PDF to out_path (or a fresh temp file if omitted) and
    returns the path. Caller owns cleanup of a temp-file result."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in (resume_text or "").splitlines() or [""]:
        # w=0 ("rest of the line") doesn't reset x between calls in fpdf2
        # 2.8.7 — without resetting x + using the explicit effective page
        # width, the second multi_cell call onward raises "Not enough
        # horizontal space to render a single character".
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6, line)

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
    pdf.output(out_path)
    return out_path
