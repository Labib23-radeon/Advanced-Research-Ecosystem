"""Local PDF & Document loader wrapper delegating cleanly to UniversalDocLoader."""
from pathlib import Path
from typing import Optional

from tools.doc_loader import UniversalDocLoader


class PDFLoaderTool(UniversalDocLoader):
    """Backwards-compatible document loader supporting PDF, DOCX, TXT, MD, CSV, and JSON."""

    def load_formatted(self, file_path: str) -> str:
        """Load local document and return a formatted preview for the agent."""
        try:
            chunks = self.load_and_chunk(file_path)
            if not chunks:
                return f"[Document Load Warning]: No readable text found in {file_path}."

            total_pages = chunks[0]["metadata"].get("total_pages", 1)
            filename = Path(file_path).name

            preview_text = "\n\n".join([
                f"[Page {c['metadata']['page']}, Section {c['metadata']['chunk_index'] + 1}]: {c['text'][:200]}..."
                for c in chunks[:3]
            ])

            return (
                f"### Successfully Ingested Document: {filename}\n"
                f"- **Total Pages / Sections**: {total_pages}\n"
                f"- **Extracted Chunks**: {len(chunks)}\n"
                f"- **Preview**:\n{preview_text}\n\n"
                f"(All {len(chunks)} chunks have been indexed into vector memory for retrieval)."
            )
        except Exception as exc:
            return f"[Document Ingestion Error for {file_path}]: {str(exc)}"


def load_pdf_document(file_path: str) -> str:
    """Functional wrapper to load and parse a local PDF or supported document."""
    loader = PDFLoaderTool()
    return loader.load_formatted(file_path)
