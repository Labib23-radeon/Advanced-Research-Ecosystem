"""Universal local document loader supporting PDF, DOCX, TXT, Markdown, CSV, and JSON."""
import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

from core.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_DOC_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}


class UniversalDocLoader:
    """Extract and semantically chunk local documents across common everyday formats."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> None:
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def resolve_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.exists():
            return path
        candidate = settings.uploads_dir / file_path
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Document not found at: {file_path}")

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks along natural word boundaries."""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            if end < len(text):
                last_space = chunk.rfind(" ")
                if last_space > int(self.chunk_size * 0.5):
                    chunk = chunk[:last_space]
                    start += last_space + 1
                else:
                    start += self.chunk_size - self.chunk_overlap
            else:
                start += self.chunk_size
            clean = chunk.strip()
            if clean:
                chunks.append(clean)
        return chunks

    def load_and_chunk(self, file_path: str) -> List[Dict[str, Any]]:
        """Extract clean text segments from PDF, DOCX, TXT, MD, CSV, or JSON files."""
        path = self.resolve_path(file_path)
        ext = path.suffix.lower()
        if ext not in SUPPORTED_DOC_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_DOC_EXTENSIONS))}"
            )

        documents: List[Dict[str, Any]] = []
        resolved = str(path.resolve())

        if ext == ".pdf":
            reader = PdfReader(str(path))
            total_pages = len(reader.pages)
            for page_idx, page in enumerate(reader.pages, start=1):
                raw_text = page.extract_text() or ""
                cleaned = " ".join(raw_text.split())
                if not cleaned:
                    continue
                for chunk_idx, chunk in enumerate(self._chunk_text(cleaned)):
                    documents.append({
                        "text": chunk,
                        "metadata": {
                            "source": path.name,
                            "file_path": resolved,
                            "page": page_idx,
                            "total_pages": total_pages,
                            "chunk_index": chunk_idx,
                            "doc_type": "pdf",
                        },
                    })
            return documents

        if ext == ".docx":
            from docx import Document

            doc = Document(str(path))
            sections: List[str] = []
            for p in doc.paragraphs:
                txt = " ".join(p.text.split())
                if txt:
                    sections.append(txt)
            for tbl in doc.tables:
                for row in tbl.rows:
                    cells = [" ".join(c.text.split()) for c in row.cells if c.text.strip()]
                    if cells:
                        sections.append(" | ".join(cells))
            full_text = "\n".join(sections)
            raw_chunks = self._chunk_text(full_text)
            for idx, chunk in enumerate(raw_chunks):
                documents.append({
                    "text": chunk,
                    "metadata": {
                        "source": path.name,
                        "file_path": resolved,
                        "page": 1,
                        "total_pages": max(1, len(raw_chunks)),
                        "chunk_index": idx,
                        "doc_type": "docx",
                    },
                })
            return documents

        if ext == ".csv":
            rows_text: List[str] = []
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f)
                headers: List[str] = []
                for row_idx, row in enumerate(reader):
                    if not any(cell.strip() for cell in row):
                        continue
                    if row_idx == 0:
                        headers = [h.strip() for h in row]
                        continue
                    if headers:
                        pairs = [
                            f"{headers[i] if i < len(headers) else f'Col{i+1}'}: {val.strip()}"
                            for i, val in enumerate(row)
                            if val.strip()
                        ]
                        rows_text.append("; ".join(pairs))
                    else:
                        rows_text.append(" | ".join(c.strip() for c in row if c.strip()))
            full_text = "\n".join(rows_text)
        elif ext == ".json":
            raw = path.read_text(encoding="utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                full_text = json.dumps(parsed, indent=2, ensure_ascii=False)
            except Exception:
                full_text = raw
        else:
            # .txt / .md
            full_text = path.read_text(encoding="utf-8", errors="replace")

        cleaned = "\n".join(line.strip() for line in full_text.splitlines() if line.strip())
        raw_chunks = self._chunk_text(cleaned)
        for idx, chunk in enumerate(raw_chunks):
            documents.append({
                "text": chunk,
                "metadata": {
                    "source": path.name,
                    "file_path": resolved,
                    "page": 1,
                    "total_pages": max(1, len(raw_chunks)),
                    "chunk_index": idx,
                    "doc_type": ext.lstrip("."),
                },
            })
        return documents
