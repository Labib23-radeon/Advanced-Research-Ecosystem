"""Asynchronous FastAPI Web Server & SSE Streaming Backend for Advanced Research Studio."""
import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import requests
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.agent_engine import LocalResearchAgent
from core.cache_manager import get_cache_manager
from core.config import settings
from core.export_utils import markdown_to_docx_bytes, markdown_to_pdf_bytes
from core.llm_providers import (
    PROVIDER_PRESETS,
    check_openai_compatible_health,
    detect_lan_ip,
    load_user_settings,
    save_user_settings,
)
from core.report_meta import (
    load_all_report_meta,
    rename_report_metadata,
    set_report_starred,
)
from tools.doc_loader import SUPPORTED_DOC_EXTENSIONS, UniversalDocLoader
from tools.local_scraper import WebScraperTool
from tools.local_search import DuckDuckGoSearchTool
from tools.pdf_loader import PDFLoaderTool

logger = logging.getLogger("research_agent_web")

BASE_DIR = Path(__file__).resolve().parent
WEB_UI_DIR = BASE_DIR / "web_ui"
WEB_UI_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Advanced Research Studio",
    description="Reliable Local-First & Hybrid AI Research Platform",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared singleton for vector store, default settings, and stateless endpoints
global_agent = LocalResearchAgent()

# Thread-safe active job registry for isolated per-run agents + cancellation
_JOBS_LOCK = threading.Lock()
ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}


# ==========================================
# Request Schemas
# ==========================================

class ModelChangeRequest(BaseModel):
    model_name: str


class SettingsUpdateRequest(BaseModel):
    provider_mode: Optional[str] = None
    ollama_host: Optional[str] = None
    ollama_model: Optional[str] = None
    openai_preset: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    clear_api_key: Optional[bool] = False
    default_depth: Optional[str] = None
    default_style: Optional[str] = None


class ConnectionTestRequest(BaseModel):
    provider_mode: Optional[str] = None
    ollama_host: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None


class OllamaPullRequest(BaseModel):
    model_name: str


class SearchRequest(BaseModel):
    query: str
    max_results: int = 5


class ScrapeRequest(BaseModel):
    url: str


class BatchScrapeRequest(BaseModel):
    urls: List[str]


class ChatRequest(BaseModel):
    question: str
    top_k: int = 6
    topic: Optional[str] = None
    report_filename: Optional[str] = None
    report_text: Optional[str] = None
    web_augment: bool = False
    chat_history: Optional[List[Dict[str, str]]] = None


class ReportUpdateRequest(BaseModel):
    content: str


class ReportStarRequest(BaseModel):
    starred: Optional[bool] = None


class ReportRenameRequest(BaseModel):
    new_title: str


class ExportRequest(BaseModel):
    content: str
    title: Optional[str] = "Research Report"
    filename: Optional[str] = "research_report"


class RepositorySelectRequest(BaseModel):
    filename: str


class ResearchRequest(BaseModel):
    topic: str
    model_name: Optional[str] = None
    pdf_path: Optional[str] = None
    depth: Optional[str] = "deep"
    source_scope: Optional[str] = "all"
    report_style: Optional[str] = "brief"
    custom_urls: Optional[List[str]] = None


# ==========================================
# Helpers
# ==========================================

def _safe_output_path(filename: str) -> Path:
    """Resolve filename safely within settings.output_dir, rejecting traversal attempts."""
    clean_name = Path(filename).name
    if not clean_name or clean_name != filename:
        raise HTTPException(status_code=400, detail="Invalid report filename")
    return settings.output_dir / clean_name


# ==========================================
# Status, Settings, Health & Network Access API
# ==========================================

@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Return active AI engine state, Ollama models, vector memory, and dossier counts."""
    ollama_ok, ollama_msg = global_agent.check_ollama_health()
    engine_info = global_agent.get_active_engine_info()
    reports_count = len(list(settings.output_dir.glob("*.md")))
    memory_count = global_agent.vector_store.count()

    default_models = [
        "llama3.2:3b",
        "qwen2.5:7b",
        "mistral:7b",
        "llama3.1:8b",
        "deepseek-r1:7b",
        "phi3:mini",
    ]
    if global_agent.available_models:
        available_models = list(dict.fromkeys(global_agent.available_models + default_models))
    else:
        available_models = default_models

    with _JOBS_LOCK:
        running_jobs = [
            {
                "job_id": jid,
                "topic": j["topic"],
                "step_count": j.get("step_count", 0),
                "depth": j.get("depth", "deep"),
            }
            for jid, j in ACTIVE_JOBS.items()
            if j.get("status") == "running"
        ]

    return {
        "status": "ready" if engine_info.get("ready") else "extractive_ready",
        "engine_type": engine_info.get("engine"),
        "engine_label": engine_info.get("label"),
        "engine_detail": engine_info.get("detail"),
        "ollama_host": global_agent.host,
        "active_model": global_agent.model_name,
        "available_models": available_models,
        "ollama_health": ollama_msg,
        "embedding_model": settings.embedding_model_name,
        "memory_chunks_count": memory_count,
        "saved_reports_count": reports_count,
        "active_jobs_count": len(running_jobs),
        "active_jobs": running_jobs,
        "chroma_dir": str(settings.chroma_dir),
        "output_dir": str(settings.output_dir),
    }


@app.get("/api/health")
def get_full_diagnostics() -> Dict[str, Any]:
    """Comprehensive system health & readiness probe for UI Health Modal and ops checks."""
    ollama_ok, ollama_msg = global_agent.check_ollama_health()
    api_ok, api_msg = check_openai_compatible_health()
    engine_info = global_agent.get_active_engine_info()
    cache_stats = get_cache_manager().stats()
    return {
        "ok": True,
        "timestamp": datetime.now().isoformat(),
        "active_engine": engine_info,
        "ollama": {"online": ollama_ok, "detail": ollama_msg, "installed_models": global_agent.available_models},
        "openai_compatible": {"online": api_ok, "detail": api_msg},
        "vector_store": {
            "backend": "ChromaDB" if global_agent.vector_store.use_chroma else "LightweightBM25",
            "chunks": global_agent.vector_store.count(),
        },
        "cache": cache_stats,
        "storage": {
            "reports": len(list(settings.output_dir.glob("*.md"))),
            "uploads": len(list(settings.uploads_dir.glob("*"))) if settings.uploads_dir.exists() else 0,
        },
        "supported_upload_formats": sorted(SUPPORTED_DOC_EXTENSIONS),
    }


@app.get("/api/settings")
def get_user_settings() -> Dict[str, Any]:
    """Return persisted AI Engine and workspace preferences with masked API key."""
    return {
        "settings": load_user_settings(mask_secret=True),
        "presets": PROVIDER_PRESETS,
    }


@app.post("/api/settings")
async def update_user_settings(req: SettingsUpdateRequest) -> Dict[str, Any]:
    """Save AI Engine preferences cleanly without leaking or dropping secrets."""
    updated = save_user_settings(req.model_dump(exclude_none=True))
    if updated.get("ollama_model"):
        global_agent.set_model(updated["ollama_model"])
    if updated.get("ollama_host"):
        global_agent.host = updated["ollama_host"]
    return {
        "status": "saved",
        "settings": updated,
        "engine": global_agent.get_active_engine_info(),
    }


@app.post("/api/settings/test")
async def test_provider_connection(req: ConnectionTestRequest) -> Dict[str, Any]:
    """Live connectivity check for either local Ollama or OpenAI-compatible endpoints."""
    cfg = load_user_settings(mask_secret=False)
    target = (req.provider_mode or cfg.get("provider_mode") or "auto").lower()

    if target == "openai_compatible":
        key_arg = req.openai_api_key
        if key_arg is not None and "•" in key_arg:
            key_arg = None
        ok, msg = check_openai_compatible_health(
            base_url=req.openai_base_url,
            api_key=key_arg,
            model_name=req.openai_model,
        )
        return {"ok": ok, "provider": "openai_compatible", "message": msg}

    host = (req.ollama_host or cfg.get("ollama_host") or global_agent.host).rstrip("/")
    try:
        t0 = time.time()
        resp = requests.get(f"{host}/api/tags", timeout=2.0)
        ms = int((time.time() - t0) * 1000)
        if resp.status_code == 200:
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return {
                "ok": True,
                "provider": "ollama",
                "message": f"Ollama connected ({ms}ms). {len(models)} model(s) installed.",
                "models": models,
            }
        return {"ok": False, "provider": "ollama", "message": f"Ollama returned HTTP {resp.status_code}"}
    except Exception:
        return {"ok": False, "provider": "ollama", "message": f"Ollama offline at {host}. Offline Fact Engine remains available."}


@app.post("/api/ollama/pull")
async def pull_ollama_model(req: OllamaPullRequest) -> Dict[str, Any]:
    """Trigger a local Ollama model pull when Ollama daemon is running."""
    model = req.model_name.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required")
    cfg = load_user_settings(mask_secret=False)
    host = (cfg.get("ollama_host") or global_agent.host).rstrip("/")
    try:
        resp = requests.post(
            f"{host}/api/pull",
            json={"name": model, "stream": False},
            timeout=120.0,
        )
        if resp.status_code == 200:
            return {"status": "pulled", "model": model}
        raise HTTPException(status_code=resp.status_code, detail=f"Ollama pull failed: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable at {host}: {exc}")


@app.get("/api/network-info")
def get_network_info(request: Request) -> Dict[str, Any]:
    """Return local and Wi-Fi LAN URLs for opening the Studio from phones, tablets, or teammates."""
    port = request.url.port or 8080
    lan_ip = detect_lan_ip()
    host_hdr = request.headers.get("host", f"127.0.0.1:{port}")
    return {
        "local_url": f"http://127.0.0.1:{port}",
        "lan_url": f"http://{lan_ip}:{port}",
        "current_origin": f"{request.url.scheme}://{host_hdr}",
        "lan_ip": lan_ip,
        "port": port,
    }


@app.post("/api/cache/clear")
async def clear_studio_cache() -> Dict[str, Any]:
    """Clear disk search/scrape cache without deleting reports or vector memory."""
    get_cache_manager().clear_caches()
    return {"status": "cleared", "cache": get_cache_manager().stats()}


@app.post("/api/model")
async def switch_model(req: ModelChangeRequest) -> Dict[str, Any]:
    """Switch active Ollama model."""
    new_model = req.model_name.strip()
    if not new_model:
        raise HTTPException(status_code=400, detail="Model name cannot be empty")
    global_agent.set_model(new_model)
    save_user_settings({"ollama_model": new_model})
    return {"status": "success", "active_model": global_agent.model_name}


# ==========================================
# Multi-Format Document Ingestion
# ==========================================

def _ingest_uploaded_file(file: UploadFile, allowed_exts: Optional[set] = None) -> Dict[str, Any]:
    """Save an uploaded document safely to data/uploads/ and index semantic chunks."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    clean_name = Path(file.filename).name
    ext = Path(clean_name).suffix.lower()
    valid_exts = allowed_exts or SUPPORTED_DOC_EXTENSIONS
    if ext not in valid_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported: {', '.join(sorted(valid_exts))}",
        )

    save_path = settings.uploads_dir / clean_name
    try:
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        loader = UniversalDocLoader(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        chunks = loader.load_and_chunk(str(save_path))
        added_count = global_agent.vector_store.add_pdf_chunks(chunks)

        total_pages = chunks[0]["metadata"].get("total_pages", 1) if chunks else 0
        combined_text = "\n".join([c["text"] for c in chunks])
        global_agent.scraped_documents.append({
            "url": str(save_path),
            "title": f"Document: {clean_name}",
            "text": combined_text,
        })

        return {
            "status": "success",
            "filename": clean_name,
            "doc_type": ext.lstrip("."),
            "file_path": str(save_path),
            "total_pages": total_pages,
            "chunks_extracted": len(chunks),
            "chunks_indexed": added_count,
            "preview": chunks[0]["text"][:250] if chunks else "",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Document upload error (%s): %s", clean_name, exc)
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(exc)}")


@app.post("/api/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a PDF file, save it to data/uploads/, and index chunks into vector memory."""
    return _ingest_uploaded_file(file, allowed_exts={".pdf"})


@app.post("/api/upload-doc")
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload PDF, DOCX, TXT, MD, CSV, or JSON document and index chunks into vector memory."""
    return _ingest_uploaded_file(file, allowed_exts=SUPPORTED_DOC_EXTENSIONS)


# ==========================================
# Interactive Q&A & Source Tools
# ==========================================

@app.post("/api/chat")
async def chat_with_research(req: ChatRequest) -> Dict[str, Any]:
    """Interactive follow-up Q&A grounded strictly in the active topic & dossier."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    report_text = req.report_text
    if not report_text:
        if req.report_filename:
            target = _safe_output_path(req.report_filename)
            if target.exists():
                report_text = target.read_text(encoding="utf-8", errors="replace")
        elif req.topic or global_agent.current_topic:
            lookup_topic = (req.topic or global_agent.current_topic or "").lower()
            topic_words = [w for w in re.findall(r"\w+", lookup_topic) if len(w) > 3]
            if topic_words:
                matches = [
                    f for f in sorted(settings.output_dir.glob("*.md"), key=os.path.getmtime, reverse=True)
                    if any(w in f.name.lower() for w in topic_words[:3])
                ]
                if matches:
                    report_text = matches[0].read_text(encoding="utf-8", errors="replace")

    return global_agent.ask_question(
        question=question,
        top_k=req.top_k,
        topic=req.topic,
        report_text=report_text,
        report_filename=req.report_filename,
        web_augment=req.web_augment,
        chat_history=req.chat_history,
    )


@app.post("/api/scrape-batch")
async def scrape_batch(req: BatchScrapeRequest) -> Dict[str, Any]:
    """Batch scrape multiple target URLs and index into vector memory."""
    scraper = WebScraperTool(timeout=settings.scrape_timeout, max_length=settings.max_content_length, persist_cache=True)
    scraped_results = []
    for url in req.urls:
        u = url.strip()
        if u:
            res = scraper.scrape(u)
            if res["status"] == "success":
                global_agent.scraped_documents.append(res)
                global_agent.vector_store.add_scraped_document(url=u, title=res["title"], text=res["text"])
                scraped_results.append({"url": u, "title": res["title"], "length": len(res["text"])})

    return {"status": "success", "scraped_count": len(scraped_results), "items": scraped_results}


@app.get("/api/source-content")
def get_source_content(url: str = Query(..., description="Source URL or local filename")) -> Dict[str, Any]:
    """Retrieve full raw text of a scraped source (in-memory, SQLite cache, local upload, or live)."""
    for doc in global_agent.scraped_documents:
        if doc.get("url") == url:
            return {"url": url, "title": doc.get("title", "Source"), "text": doc.get("text", ""), "status": "success"}

    # Check persistent SQLite cache so View Text works after restarts or offline
    if url.startswith("http://") or url.startswith("https://"):
        cached = get_cache_manager().get_scrape(url)
        if cached:
            return cached

    local_path = Path(url)
    if not local_path.is_absolute():
        candidate = settings.uploads_dir / url
        if candidate.exists():
            local_path = candidate
        else:
            candidate2 = settings.data_dir / url
            if candidate2.exists():
                local_path = candidate2

    if local_path.exists() and local_path.is_file():
        ext = local_path.suffix.lower()
        if ext in SUPPORTED_DOC_EXTENSIONS:
            try:
                chunks = UniversalDocLoader().load_and_chunk(str(local_path))
                combined = "\n\n".join(c["text"] for c in chunks)
                return {
                    "url": url,
                    "title": f"Local {ext.lstrip('.').upper()}: {local_path.name}",
                    "text": combined,
                    "status": "success",
                }
            except Exception as exc:
                return {"url": url, "title": local_path.name, "text": f"Error loading document: {exc}", "status": "error"}
        try:
            text = local_path.read_text(encoding="utf-8", errors="replace")
            return {"url": url, "title": local_path.name, "text": text, "status": "success"}
        except Exception as exc:
            return {"url": url, "title": local_path.name, "text": f"Error reading file: {exc}", "status": "error"}

    scraper = WebScraperTool(timeout=settings.scrape_timeout, max_length=settings.max_content_length, persist_cache=True)
    return scraper.scrape(url)


# ==========================================
# Repository, Bookmarks, Editing & Exports
# ==========================================

@app.get("/api/reports")
def list_reports() -> List[Dict[str, Any]]:
    """List saved dossiers merged with persistent star/bookmark & custom title metadata."""
    meta_map = load_all_report_meta()
    reports: List[Dict[str, Any]] = []
    files = sorted(settings.output_dir.glob("*.md"), key=os.path.getmtime, reverse=True)

    for f in files:
        try:
            stat = f.stat()
            content = f.read_text(encoding="utf-8", errors="replace")
            first_title = f.name
            for line in content.splitlines():
                if line.startswith("# "):
                    first_title = line[2:].strip()
                    break

            m = meta_map.get(f.name, {})
            display_title = m.get("custom_title") or first_title
            starred = bool(m.get("starred", False))

            word_count = len(content.split())
            reading_time_min = max(1, round(word_count / 200))

            reports.append({
                "filename": f.name,
                "title": display_title,
                "starred": starred,
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_bytes": stat.st_size,
                "word_count": word_count,
                "reading_time_min": reading_time_min,
                "preview": content[:300],
            })
        except Exception:
            pass

    # Starred reports gently surface first only when filtering or preserve chronological sort?
    # Keep newest-first primary order so test/expectation & recency remain predictable.
    return reports


@app.get("/api/reports/{filename}")
def get_report(filename: str) -> Dict[str, Any]:
    """Retrieve raw markdown content of a specific report."""
    target = _safe_output_path(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    content = target.read_text(encoding="utf-8", errors="replace")
    meta = load_all_report_meta().get(target.name, {})
    return {
        "filename": target.name,
        "content": content,
        "starred": bool(meta.get("starred", False)),
        "size_bytes": target.stat().st_size,
        "modified_at": datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.put("/api/reports/{filename}")
async def update_report(filename: str, req: ReportUpdateRequest) -> Dict[str, Any]:
    """Save edited markdown changes back to a saved research report."""
    target = _safe_output_path(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    new_content = req.content.strip()
    if not new_content:
        raise HTTPException(status_code=400, detail="Report content cannot be empty")
    target.write_text(new_content + "\n", encoding="utf-8")

    paragraphs = [p.strip() for p in new_content.split("\n\n") if len(p.strip()) > 80]
    if paragraphs:
        slice_paras = paragraphs[:25]
        ids = [f"repo_{target.name}_{idx}" for idx in range(len(slice_paras))]
        title = target.name
        for line in new_content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        metas = [{"source": f"repo:{target.name}", "title": title, "type": "repository_report"} for _ in slice_paras]
        try:
            global_agent.vector_store.upsert_texts(slice_paras, metadatas=metas, ids=ids)
        except Exception as e:
            logger.debug("Re-index after edit skipped: %s", e)

    return {
        "status": "updated",
        "filename": target.name,
        "size_bytes": target.stat().st_size,
        "word_count": len(new_content.split()),
    }


@app.post("/api/reports/{filename}/star")
async def toggle_report_star(filename: str, req: Optional[ReportStarRequest] = None) -> Dict[str, Any]:
    """Bookmark or unbookmark a saved research dossier."""
    target = _safe_output_path(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    starred = set_report_starred(target.name, starred=req.starred if req else None)
    return {"status": "success", "filename": target.name, "starred": starred}


@app.post("/api/reports/{filename}/rename")
async def rename_report_title(filename: str, req: ReportRenameRequest) -> Dict[str, Any]:
    """Update the display title (both heading inside file & metadata) cleanly."""
    target = _safe_output_path(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    new_title = req.new_title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="New title cannot be empty")

    content = target.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            lines[idx] = f"# {new_title}"
            replaced = True
            break
    if not replaced:
        lines.insert(0, f"# {new_title}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rename_report_metadata(target.name, target.name, custom_title=new_title)
    return {"status": "renamed", "filename": target.name, "title": new_title}


@app.post("/api/export/docx")
async def export_report_docx(req: ExportRequest) -> Response:
    """Convert markdown report into a cleanly styled Microsoft Word (.docx) download."""
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="Empty content cannot be exported")
    docx_bytes = markdown_to_docx_bytes(req.content, title=req.title or "Research Report")
    base_name = re.sub(r"[^\w\-_]", "_", (req.filename or "research_report").replace(".md", ""))[:50]
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.docx"'},
    )


@app.post("/api/export/pdf")
async def export_report_pdf(req: ExportRequest) -> Response:
    """Convert markdown report into a formatted PDF download."""
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="Empty content cannot be exported")
    pdf_bytes = markdown_to_pdf_bytes(req.content, title=req.title or "Research Report")
    base_name = re.sub(r"[^\w\-_]", "_", (req.filename or "research_report").replace(".md", ""))[:50]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.pdf"'},
    )


@app.delete("/api/reports/{filename}")
async def delete_report(filename: str) -> Dict[str, str]:
    """Delete a saved research report."""
    target = _safe_output_path(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    target.unlink()
    return {"status": "deleted", "filename": target.name}


@app.get("/api/repository")
def get_repository_catalog() -> List[Dict[str, Any]]:
    """Alias for repository listing."""
    return list_reports()


@app.post("/api/repository/select")
async def select_repository_report(req: RepositorySelectRequest) -> Dict[str, Any]:
    """Select and activate a research report from the repository for analysis and Q&A."""
    target = _safe_output_path(req.filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Report file '{req.filename}' not found")

    content = target.read_text(encoding="utf-8", errors="replace")
    meta = load_all_report_meta().get(target.name, {})

    title = meta.get("custom_title") or target.name.replace(".md", "").replace("_", " ").title()
    if not meta.get("custom_title"):
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

    global_agent.current_topic = title

    paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 80]
    chunks_indexed = 0
    if paragraphs:
        slice_paras = paragraphs[:25]
        ids = [f"repo_{target.name}_{idx}" for idx in range(len(slice_paras))]
        metas = [{"source": f"repo:{target.name}", "title": title, "type": "repository_report"} for _ in slice_paras]
        try:
            chunks_indexed = global_agent.vector_store.upsert_texts(slice_paras, metadatas=metas, ids=ids)
        except Exception as e:
            logger.debug("Failed indexing report paragraphs: %s", e)

    urls = re.findall(r"https?://[^\s\)\]\>\"\'\,]+", content)
    unique_urls = list(dict.fromkeys(urls))
    sources = [{"url": u, "title": u.split("//")[-1].split("/")[0]} for u in unique_urls[:20]]

    if sources:
        global_agent.sources = sources

    return {
        "status": "success",
        "filename": req.filename,
        "title": title,
        "starred": bool(meta.get("starred", False)),
        "content": content,
        "size_bytes": target.stat().st_size,
        "modified_at": datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "chunks_indexed": chunks_indexed,
        "sources": sources,
    }


@app.get("/api/memory")
def get_memory_sample(q: Optional[str] = None) -> Dict[str, Any]:
    """Get sample stored chunks from vector memory."""
    query_text = q or "research"
    results = global_agent.vector_store.query(query_text, n_results=12)
    return {
        "total_chunks": global_agent.vector_store.count(),
        "sample_query": query_text,
        "results": results,
    }


@app.post("/api/memory/clear")
async def clear_memory() -> Dict[str, str]:
    """Clear all vector memory."""
    global_agent.vector_store.clear()
    global_agent.scraped_documents = []
    return {"status": "success", "message": "Vector memory store cleared"}


@app.post("/api/search")
async def direct_search(req: SearchRequest) -> Dict[str, Any]:
    """Direct search tool tester."""
    tool = DuckDuckGoSearchTool(max_results=req.max_results, persist_cache=True)
    results = tool.search(req.query, max_results=req.max_results)
    formatted = tool.format_results(results, req.query)
    return {"query": req.query, "results": results, "formatted": formatted}


@app.post("/api/scrape")
async def direct_scrape(req: ScrapeRequest) -> Dict[str, Any]:
    """Direct scraper tool tester."""
    tool = WebScraperTool(persist_cache=True)
    return tool.scrape(req.url)


@app.get("/api/jobs")
def list_recent_jobs() -> Dict[str, Any]:
    """List active and recent persistent research jobs."""
    with _JOBS_LOCK:
        active = [
            {
                "job_id": jid,
                "topic": j["topic"],
                "status": j["status"],
                "step_count": j.get("step_count", 0),
                "depth": j.get("depth", "deep"),
                "started_at": j.get("started_at"),
            }
            for jid, j in ACTIVE_JOBS.items()
            if j.get("status") == "running"
        ]
    return {"active": active, "recent": get_cache_manager().list_recent_jobs(limit=12)}


@app.post("/api/cancel-research")
async def cancel_research() -> Dict[str, str]:
    """Request all active autonomous research runs to halt immediately."""
    global_agent.cancel()
    with _JOBS_LOCK:
        for job in ACTIVE_JOBS.values():
            agent_ref = job.get("agent")
            if agent_ref is not None:
                agent_ref.cancel()
            if job.get("status") == "running":
                job["status"] = "cancelled"
    return {"status": "cancelled", "message": "Research loop cancellation requested"}


# ==========================================
# Isolated Concurrent SSE Research Streaming
# ==========================================

@app.get("/api/stream-research")
async def stream_research(
    topic: str = Query(..., description="Research goal / topic"),
    model_name: Optional[str] = Query(None, description="Model name to use"),
    pdf_path: Optional[str] = Query(None, description="Path to optional local document"),
    depth: Optional[str] = Query("deep", description="Research depth: quick, deep, exhaustive"),
    source_scope: Optional[str] = Query("all", description="Source scope: all, academic, tech, pdf_only"),
    report_style: Optional[str] = Query("brief", description="Synthesis style: brief, academic, comparison, study_guide, decision"),
    custom_urls: Optional[str] = Query(None, description="Comma-separated custom URLs"),
) -> StreamingResponse:
    """Execute research on an isolated agent instance and stream Server-Sent Events with heartbeats."""
    if not topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty")

    job_id = str(uuid.uuid4())[:12]
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    parsed_urls = [u.strip() for u in custom_urls.split(",") if u.strip()] if custom_urls else []

    # Per-request isolated agent reusing shared thread-safe vector store (prevents cross-tab collisions)
    job_agent = LocalResearchAgent(
        model_name=model_name or global_agent.model_name,
        host=global_agent.host,
        vector_store=global_agent.vector_store,
    )

    cache = get_cache_manager()
    started_ts = time.time()
    with _JOBS_LOCK:
        ACTIVE_JOBS[job_id] = {
            "job_id": job_id,
            "topic": topic,
            "status": "running",
            "depth": depth or "deep",
            "source_scope": source_scope or "all",
            "step_count": 0,
            "started_at": started_ts,
            "agent": job_agent,
        }
    cache.upsert_job(
        job_id=job_id,
        topic=topic,
        status="running",
        depth=depth or "deep",
        source_scope=source_scope or "all",
        model_name=job_agent.model_name,
        started_at=started_ts,
    )

    def sync_on_step(step_info: Dict[str, Any]) -> None:
        step_num = int(step_info.get("step", 0))
        with _JOBS_LOCK:
            if job_id in ACTIVE_JOBS:
                ACTIVE_JOBS[job_id]["step_count"] = step_num
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "step", "data": step_info})

    def run_agent_sync() -> None:
        try:
            job_agent.on_step_callback = sync_on_step
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "start",
                    "job_id": job_id,
                    "topic": topic,
                    "model": job_agent.model_name,
                    "pdf": pdf_path,
                    "depth": depth or "deep",
                    "source_scope": source_scope or "all",
                    "report_style": report_style or "brief",
                },
            )

            report_text, report_file = job_agent.research(
                topic=topic,
                initial_pdf=pdf_path,
                depth=depth or "deep",
                custom_urls=parsed_urls,
                source_scope=source_scope or "all",
                report_style=report_style or "brief",
            )

            # Update shared global_agent convenience state for simple CLI/single-user queries
            global_agent.current_topic = topic
            if job_agent.sources:
                global_agent.sources = list(job_agent.sources)
            if job_agent.scraped_documents:
                global_agent.scraped_documents = (global_agent.scraped_documents + job_agent.scraped_documents)[-50:]

            fin_status = "cancelled" if job_agent.is_cancelled else "completed"
            with _JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = fin_status
                    ACTIVE_JOBS[job_id]["filename"] = report_file.name
            cache.upsert_job(
                job_id=job_id,
                topic=topic,
                status=fin_status,
                depth=depth or "deep",
                source_scope=source_scope or "all",
                model_name=job_agent.model_name,
                step_count=ACTIVE_JOBS.get(job_id, {}).get("step_count", 0),
                filename=report_file.name,
                finished_at=time.time(),
            )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "complete",
                    "job_id": job_id,
                    "report": report_text,
                    "file_path": str(report_file),
                    "filename": report_file.name,
                    "sources": job_agent.sources,
                },
            )
        except Exception as exc:
            logger.error("Streaming research error (%s): %s", job_id, exc)
            with _JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "error"
            cache.upsert_job(
                job_id=job_id,
                topic=topic,
                status="error",
                depth=depth or "deep",
                source_scope=source_scope or "all",
                model_name=job_agent.model_name,
                error_msg=str(exc),
                finished_at=time.time(),
            )
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(asyncio.to_thread(run_agent_sync))

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if item is None:
                yield "event: close\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==========================================
# Frontend Static Assets
# ==========================================

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Serve Advanced logo favicon."""
    fav_path = WEB_UI_DIR / "assets" / "advanced_logo.png"
    if fav_path.exists():
        return FileResponse(fav_path, media_type="image/png")
    return HTMLResponse("", status_code=204)


@app.get("/")
async def serve_index() -> HTMLResponse:
    """Serve main Single Page Application HTML."""
    index_file = WEB_UI_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Web UI is initializing...</h1>", status_code=200)
    return HTMLResponse(index_file.read_text(encoding="utf-8"), status_code=200)


app.mount("/static", StaticFiles(directory=str(WEB_UI_DIR)), name="static")
