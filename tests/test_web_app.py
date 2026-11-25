"""Tests for FastAPI backend endpoints, Q&A chat, and static serving."""
import pytest
from fastapi.testclient import TestClient
from web_app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_index_page_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Research Studio" in response.text
    assert "advanced" in response.text


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "ollama_host" in data
    assert "active_model" in data
    assert "memory_chunks_count" in data


def test_model_switch_endpoint(client):
    response = client.post("/api/model", json={"model_name": "qwen2.5:7b"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_model"] == "qwen2.5:7b"


def test_reports_list_endpoint(client):
    response = client.get("/api/reports")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_memory_endpoint(client):
    response = client.get("/api/memory?q=test")
    assert response.status_code == 200
    data = response.json()
    assert "total_chunks" in data
    assert "results" in data


def test_chat_followup_endpoint(client):
    response = client.post("/api/chat", json={"question": "What is local AI?", "top_k": 3})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data


def test_scrape_batch_endpoint(client):
    response = client.post("/api/scrape-batch", json={"urls": ["https://example.com"]})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_source_content_local_file(client, tmp_path):
    from core.config import settings
    test_file = settings.uploads_dir / "test_doc.txt"
    test_file.write_text("This is verified test content for source preview.", encoding="utf-8")
    try:
        response = client.get(f"/api/source-content?url=test_doc.txt")
        assert response.status_code == 200
        data = response.json()
        assert "verified test content" in data["text"]
    finally:
        if test_file.exists():
            test_file.unlink()


def test_report_delete_lifecycle(client):
    from core.config import settings
    dummy_report = settings.output_dir / "test_lifecycle_report.md"
    dummy_report.write_text("# Test Lifecycle Report\nContent here.", encoding="utf-8")

    # Verify present
    res_get = client.get("/api/reports/test_lifecycle_report.md")
    assert res_get.status_code == 200

    # Delete
    res_del = client.delete("/api/reports/test_lifecycle_report.md")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"

    # Verify gone
    res_get2 = client.get("/api/reports/test_lifecycle_report.md")
    assert res_get2.status_code == 404


def test_cancel_research_endpoint(client):
    res = client.post("/api/cancel-research")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "cancelled"
