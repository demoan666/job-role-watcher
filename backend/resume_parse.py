"""Extension-dispatch text extraction for uploaded resume files.

Legacy .doc (binary Word format, pre-2007) is deliberately unsupported —
there's no clean pure-Python parser for it without shelling out to system
tools (antiword/textract), not worth the dependency for a personal tool.
"""

import io

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


class UnsupportedFileType(Exception):
    pass


def extract_text(filename, content_bytes):
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext in (".txt", ".md"):
        return content_bytes.decode("utf-8", errors="replace")

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(content_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

    if ext == ".docx":
        doc = Document(io.BytesIO(content_bytes))
        return "\n".join(p.text for p in doc.paragraphs).strip()

    if ext == ".doc":
        raise UnsupportedFileType(
            "Old .doc format isn't supported — please save as .docx, PDF, or .txt and re-upload."
        )

    raise UnsupportedFileType(
        f"Unsupported file type '{ext or filename}' — supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
    )
