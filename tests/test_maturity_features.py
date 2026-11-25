"""Regression & maturity tests covering persistent cache, hybrid providers, universal docs, SSRF, and repo metadata."""
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from docx import Document
from fastapi.testclient import TestClient

from core.cache_manager import StudioCacheManager
from core.config import settings
from core.llm_providers import (
    call_openai_compatible,
    detect_lan_ip,
    load_user_settings,
    save_user_settings,
)
from core.report_meta import rename_report_metadata, set_report_starred
from tools.doc_loader import UniversalDocLoader
from tools.local_scraper import WebScraperTool, is_safe_public_url
from web_app import app


def test_sqlite_cache_search_scrape_and_jobs(tmp_path: Path):
    cache = StudioCacheManager(db_path=tmp_path / "test_cache.db")
    sample_res = [{"title": "Result 1", "href": "https://example.org/1", "body": "Verified sample text."}]
    cache.set_search("test::5", "test", sample_res)
    got = cache.get_search("test::5")
    assert got == sample_res

    cache.set_scrape({"url": "https://example.org/1", "title": "Page 1", "text": "Body text", "status": "success"})
    scraped = cache.get_scrape("https://example.org/1")
    assert scraped is not None and scraped["title"] == "Page 1"

    cache.upsert_job(job_id="job1", topic="Solid-State Batteries", status="running", step_count=2)
    cache.upsert_job(job_id="job1", topic="Solid-State Batteries", status="completed", step_count=6, filename="out.md")
    jobs = cache.list_recent_jobs(limit=5)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "completed"
    assert cache.stats()["search_entries"] == 1

    cache.clear_caches()
    assert cache.get_search("test::5") is None
    assert len(cache.list_recent_jobs()) == 1


def test_universal_doc_loader_docx_csv_txt_json(tmp_path: Path):
    loader = UniversalDocLoader(chunk_size=250, chunk_overlap=30)

    # 1. DOCX
    docx_path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_heading("Research Architecture Notes", level=1)
    doc.add_paragraph("Spiking neural networks consume roughly 15 mW on neuromorphic chips compared to GPUs.")
    doc.save(str(docx_path))
    docx_chunks = loader.load_and_chunk(str(docx_path))
    assert len(docx_chunks) >= 1
    assert "Spiking neural networks" in docx_chunks[0]["text"]
    assert docx_chunks[0]["metadata"]["doc_type"] == "docx"

    # 2. CSV
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("Model,Accuracy,Latency_ms\nLlama3.2,86.4%,18\nQwen2.5,89.1%,24\n", encoding="utf-8")
    csv_chunks = loader.load_and_chunk(str(csv_path))
    assert len(csv_chunks) == 1
    assert "Qwen2.5" in csv_chunks[0]["text"]
    assert csv_chunks[0]["metadata"]["doc_type"] == "csv"

    # 3. Markdown & JSON
    md_path = tmp_path / "notes.md"
    md_path.write_text("# Key Takeaways\nRAG grounds local models on verified user evidence.", encoding="utf-8")
    assert "RAG grounds local models" in loader.load_and_chunk(str(md_path))[0]["text"]

    json_path = tmp_path / "config.json"
    json_path.write_text('{"benchmark": "MATH-500", "score": 97.3}', encoding="utf-8")
    assert "MATH-500" in loader.load_and_chunk(str(json_path))[0]["text"]


def test_ssrf_guard_blocks_private_hosts():
    assert is_safe_public_url("https://arxiv.org/abs/2501.12948") is True
    assert is_safe_public_url("http://127.0.0.1:8080/api/status") is False
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_public_url("http://localhost:11434/api/tags") is False

    scraper = WebScraperTool()
    blocked = scraper.scrape("http://127.0.0.1:8080/secret")
    assert blocked["status"] == "error"
    assert "Blocked" in blocked["title"]


def test_settings_masking_and_openai_compatible_adapter(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    saved = save_user_settings({
        "provider_mode": "openai_compatible",
        "openai_base_url": "https://api.groq.com/openai/v1",
        "openai_model": "llama-3.3-70b-versatile",
        "openai_api_key": "gsk_test_secret_123456",
    })
    assert saved["has_api_key"] is True
    assert saved["openai_api_key"] == ""
    assert "••••" in saved["openai_api_key_masked"]
    assert "123456" not in saved["openai_api_key_masked"]

    # Mock OpenAI-compatible HTTP response cleanly
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "<think>reasoning</think># Grounded Summary\nVerified output."}}]
    }
    with patch("core.llm_providers.requests.post", return_value=mock_resp):
        out = call_openai_compatible([{"role": "user", "content": "hi"}])
        assert "# Grounded Summary" in out
        assert "<think>" not in out

    # Ensure LAN IP helper always returns a valid IPv4 string
    ip = detect_lan_ip()
    assert len(ip.split(".")) == 4


def test_api_health_settings_upload_doc_star_and_rename():
    client = TestClient(app)

    # 1. Health & Network Info & Jobs endpoints
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["ok"] is True
    assert ".docx" in h.json()["supported_upload_formats"]

    n = client.get("/api/network-info")
    assert n.status_code == 200
    assert "local_url" in n.json()
    assert "lan_url" in n.json()

    j = client.get("/api/jobs")
    assert j.status_code == 200
    assert "active" in j.json()

    # 2. Settings endpoint masking
    s = client.get("/api/settings")
    assert s.status_code == 200
    assert "presets" in s.json()
    assert s.json()["settings"]["openai_api_key"] == ""

    # 3. Universal multi-format upload endpoint (.csv & .docx)
    csv_bytes = b"System,Throughput\nvLLM,180 tok/s\n"
    up_csv = client.post("/api/upload-doc", files={"file": ("bench_test.csv", BytesIO(csv_bytes), "text/csv")})
    assert up_csv.status_code == 200
    assert up_csv.json()["doc_type"] == "csv"

    uploaded_csv_path = settings.uploads_dir / "bench_test.csv"
    if uploaded_csv_path.exists():
        uploaded_csv_path.unlink()

    # 4. Star & Rename dossier endpoints
    dummy_name = "test_star_rename_dossier.md"
    dummy_path = settings.output_dir / dummy_name
    dummy_path.write_text("# Old Draft Title\n\nContent about edge AI.", encoding="utf-8")
    try:
        star_res = client.post(f"/api/reports/{dummy_name}/star", json={"starred": True})
        assert star_res.status_code == 200
        assert star_res.json()["starred"] is True

        rename_res = client.post(f"/api/reports/{dummy_name}/rename", json={"new_title": "Refined Edge AI Title"})
        assert rename_res.status_code == 200
        assert rename_res.json()["title"] == "Refined Edge AI Title"
        assert "# Refined Edge AI Title" in dummy_path.read_text(encoding="utf-8")

        reports_list = client.get("/api/reports").json()
        matched = [r for r in reports_list if r["filename"] == dummy_name]
        assert matched and matched[0]["starred"] is True
        assert matched[0]["title"] == "Refined Edge AI Title"
    finally:
        if dummy_path.exists():
            dummy_path.unlink()
        set_report_starred(dummy_name, starred=False)
        rename_report_metadata(dummy_name, dummy_name, custom_title="")
