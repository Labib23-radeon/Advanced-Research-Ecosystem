"""Comprehensive automated tests for text cleaning, repository selection, and interactive Q&A."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from core.text_cleaner import clean_llm_output, clean_qa_response, sanitize_search_snippet
from core.agent_engine import LocalResearchAgent
from core.config import settings
from web_app import app


def test_clean_llm_output_thinking_tokens():
    raw = "<think>Let me ponder about the architecture and compute trade-offs...</think># Executive Summary\nDeepSeek-R1 achieves high reasoning efficiency."
    cleaned = clean_llm_output(raw)
    assert "<think>" not in cleaned
    assert "Let me ponder" not in cleaned
    assert "# Executive Summary" in cleaned
    assert "DeepSeek-R1 achieves high reasoning efficiency." in cleaned


def test_clean_llm_output_markdown_block_wrapper():
    raw = "```markdown\n# Architecture Review\n\nKey architectural pillars:\n- MoE routing\n- Multi-head latent attention\n```"
    cleaned = clean_llm_output(raw)
    assert not cleaned.startswith("```")
    assert not cleaned.endswith("```")
    assert "# Architecture Review" in cleaned
    assert "Multi-head latent attention" in cleaned


def test_clean_llm_output_conversational_preamble_and_trailing():
    raw = "Sure! Here is the comprehensive research report:\n\n# Benchmark Analysis\n\nMMLU score is 90.8%.\n\nI hope this helps! Let me know if you need any further analysis."
    cleaned = clean_llm_output(raw)
    assert not cleaned.startswith("Sure!")
    assert not cleaned.startswith("Here is")
    assert "# Benchmark Analysis" in cleaned
    assert "MMLU score is 90.8%." in cleaned
    assert "I hope this helps" not in cleaned


def test_clean_llm_output_duplicate_headings():
    raw = "# DeepSeek-R1 vs Llama 3.3\n\n# DeepSeek-R1 vs Llama 3.3\n\nOverview of the models."
    cleaned = clean_llm_output(raw)
    assert cleaned.count("# DeepSeek-R1 vs Llama 3.3") == 1
    assert "Overview of the models." in cleaned


def test_clean_llm_output_unclosed_thinking_tags():
    raw = "<think>Pondering model parameter distributions without closing tag...\n\n# Technical Architecture\nMoE architecture utilizes top-2 routing."
    cleaned = clean_llm_output(raw)
    assert "<think>" not in cleaned
    assert "Pondering" not in cleaned
    assert "# Technical Architecture" in cleaned
    assert "top-2 routing" in cleaned


def test_clean_llm_output_heading_inner_bolding():
    raw = "## **1. Executive Summary**\nCore findings.\n\n### **Empirical Benchmarks:**\nMMLU score 88.5%."
    cleaned = clean_llm_output(raw)
    assert "## 1. Executive Summary" in cleaned
    assert "### Empirical Benchmarks:" in cleaned or "### Empirical Benchmarks" in cleaned
    assert "**1. Executive Summary**" not in cleaned


def test_clean_qa_response_directness():
    raw = "Sure! Based on the provided context, here is the answer:\n\nDeepSeek-R1 achieves 97.3% on MATH-500.\n\nI hope this helps answers your question!"
    cleaned = clean_qa_response(raw)
    assert not cleaned.startswith("Sure")
    assert not cleaned.startswith("Based on")
    assert "97.3% on MATH-500" in cleaned
    assert "I hope this helps" not in cleaned


def test_sanitize_search_snippet_dates_and_bots():
    raw = "Nov 14, 2026 · DeepSeek-R1 open weights release announcement on HuggingFace... JavaScript is disabled"
    sanitized = sanitize_search_snippet(raw)
    assert not sanitized.startswith("Nov 14")
    assert "DeepSeek-R1" in sanitized
    assert "JavaScript is disabled" not in sanitized


def test_repository_select_and_chat_endpoints():
    client = TestClient(app)

    # 1. Test repository catalog listing
    resp = client.get("/api/repository")
    assert resp.status_code == 200
    reports = resp.json()
    assert isinstance(reports, list)

    # Create a dummy report in output_dir to test selection
    test_filename = "test_deepseek_dossier.md"
    test_path = settings.output_dir / test_filename
    test_content = (
        "# DeepSeek-R1 Deep Dive Architecture\n\n"
        "DeepSeek-R1 introduces pure reinforcement learning reasoning without supervised fine-tuning in cold-start.\n\n"
        "Benchmark results: MATH-500 score reached 97.3%, competing directly with OpenAI o1.\n\n"
        "Source: https://arxiv.org/abs/2501.12948 and https://github.com/deepseek-ai/DeepSeek-R1\n"
    )
    test_path.write_text(test_content, encoding="utf-8")

    try:
        # 2. Test selecting this report from repository
        sel_resp = client.post("/api/repository/select", json={"filename": test_filename})
        assert sel_resp.status_code == 200
        sel_data = sel_resp.json()
        assert sel_data["status"] == "success"
        assert sel_data["filename"] == test_filename
        assert "DeepSeek-R1 Deep Dive Architecture" in sel_data["title"]
        assert len(sel_data["sources"]) >= 1

        # 3. Test interactive follow-up Q&A on this active report
        chat_resp = client.post(
            "/api/chat",
            json={
                "question": "What is the MATH-500 benchmark score?",
                "topic": "DeepSeek-R1 Deep Dive Architecture",
                "report_filename": test_filename,
                "top_k": 4,
            },
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        assert "answer" in chat_data
        assert len(chat_data["answer"]) > 0
        # Should cite or mention MATH-500 or 97.3%
        assert "97.3" in chat_data["answer"] or "MATH-500" in chat_data["answer"] or "benchmark" in chat_data["answer"].lower()
    finally:
        if test_path.exists():
            test_path.unlink()


def test_ask_question_strict_topic_scoping_no_cross_pollution():
    """Verify that asking a generic question like 'Key metrics' does not pull unrelated chunks from other topics."""
    agent = LocalResearchAgent()

    # Provide active report text on Anemia Detection
    anemia_report = (
        "# Anemia Detection from Palm Images\n\n"
        "## 📌 Executive Summary\n"
        "Non-invasive anemia detection using smartphone camera palm images.\n\n"
        "## 📊 Quantitative Benchmarks & Empirical Metrics\n"
        "| Model | Accuracy | Sensitivity | Specificity |\n"
        "| --- | --- | --- | --- |\n"
        "| ResNet50 | 92.4% | 89.1% | 94.2% |\n"
        "| Ensemble | 95.8% | 94.6% | 96.3% |\n\n"
        "## ⚖️ Comparative Analysis & Engineering Trade-offs\n"
        "Skin tone variability remains the dominant challenge for colorimetric calibration.\n"
    )

    # Ask generic prompt with topic 'Anemia Detection from Palm Images'
    result = agent.ask_question(
        question="Summarize all quantitative metrics, numbers, and benchmarks from these sources.",
        topic="Anemia Detection from Palm Images",
        report_text=anemia_report,
    )

    answer = result["answer"]
    # 1. Must contain relevant metrics from active report
    assert "95.8%" in answer or "ResNet50" in answer or "Quantitative" in answer or "Accuracy" in answer
    # 2. Must NEVER contain out-of-context topics from old vector store entries like neuromorphic computing
    assert "neuromorphic" not in answer.lower()
    assert "Discussion" not in answer


def test_direct_search_endpoint_and_citation_parity():
    from unittest.mock import patch
    from core.agent_engine import ExtractiveFactSynthesizer
    from tools.local_scraper import WebScraperTool

    client = TestClient(app)

    # 1. Verify /api/search works cleanly without AttributeError
    with patch("tools.local_search.DuckDuckGoSearchTool.search", return_value=[{"title": "Sample Result", "href": "https://example.com/a", "body": "Verified summary content."}]):
        resp = client.post("/api/search", json={"query": "quantum computing"})
        assert resp.status_code == 200
        data = resp.json()
        assert "Sample Result" in data["formatted"]

    # 2. Verify inline citation indices map 1:1 to unique source list positions
    sources = [
        {"title": "Primary Source A", "url": "https://a.example.com", "type": "web"},
        {"title": "Secondary Source B", "url": "https://b.example.com", "type": "webpage"},
    ]
    raw_docs = [
        {"url": "https://b.example.com", "title": "Secondary Source B", "text": "Quantum annealing reached 94.5% benchmark accuracy across optimization tasks with low energy consumption."},
    ]
    report = ExtractiveFactSynthesizer.synthesize("Quantum Annealing", [], sources, raw_docs)
    # Source B is index [2] in sources, so its inline fact must cite [2], not [1]!
    assert "`[2]`" in report

    # 3. Verify scraper preserves real <title> and rewrites arxiv pdf URLs
    scraper = WebScraperTool()
    mock_html = "<html><head><title>Real Technical Paper Title</title></head><body><article><p>Sufficient long scientific text describing architecture details and verified benchmark metrics cleanly.</p></article></body></html>"
    with patch("requests.get") as mock_get:
        class MockResp:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            text = mock_html
            def raise_for_status(self): pass
        mock_get.return_value = MockResp()
        res = scraper.scrape("https://arxiv.org/pdf/2501.12948")
        assert res["status"] == "success"
        assert res["url"] == "https://arxiv.org/abs/2501.12948"
        assert res["title"] == "Real Technical Paper Title"


def test_vector_store_upsert_and_path_traversal_guard(tmp_path):
    from tools.vector_store import LightweightVectorStore
    store = LightweightVectorStore(persist_path=tmp_path / "upsert_mem.json")
    store.upsert_texts(["Initial version fact about AI."], metadatas=[{"source": "s1"}], ids=["doc_1"])
    assert store.count() == 1
    store.upsert_texts(["Updated refined fact about AI."], metadatas=[{"source": "s1"}], ids=["doc_1"])
    assert store.count() == 1
    assert "Updated refined" in store.documents[0]["text"]

    # Check report path traversal protection
    client = TestClient(app)
    resp = client.get("/api/reports/..%5C..%5Csecret.md")
    assert resp.status_code in (400, 404)


def test_clean_qa_zero_clutter_and_real_world_exports():
    from unittest.mock import patch

    agent = LocalResearchAgent()
    sample_md = (
        "# Research Intelligence Report: Solid-State Lithium Batteries\n\n"
        "## 📌 Executive Summary\n"
        "Solid-state electrolytes replace flammable liquid carbonate solvents with ceramic or sulfide separators [1].\n\n"
        "## 📊 Quantitative Benchmarks & Empirical Metrics\n"
        "| # | Empirical Metric / Finding | Source |\n"
        "|---|---|---|\n"
        "| 1 | Solid-state prototypes demonstrate 450 Wh/kg volumetric energy density at 25C. | [Nature](https://example.com/ssb) |\n\n"
        "## 📚 References & Verified Sources\n"
        "- `[1]` **Nature Energy** (WEB) - [https://example.com/ssb](https://example.com/ssb)\n"
    )

    # 1. Verify Q&A returns strictly clean results with zero wrapper headings or clutter
    qa_res = agent.ask_question(
        question="What are the energy density benchmarks?",
        topic="Research Intelligence Report: Solid-State Lithium Batteries",
        report_text=sample_md,
    )
    ans = qa_res["answer"]
    assert "450 Wh/kg" in ans
    assert "Evidence Analysis" not in ans
    assert "Verified Dossier Findings" not in ans
    assert "Direct Grounded Evidence Points" not in ans

    # 2. Verify domain keyword scoping stops unrelated generic queries
    unrelated_res = agent.ask_question(
        question="What is quantum annealing?",
        topic="Research Intelligence Report: Solid-State Lithium Batteries",
        report_text=sample_md,
    )
    assert "450 Wh/kg" in unrelated_res["answer"] or "No details found" in unrelated_res["answer"]

    client = TestClient(app)

    # 3. Verify DOCX and PDF native exports
    docx_resp = client.post("/api/export/docx", json={"content": sample_md, "title": "Solid-State Batteries", "filename": "ssb"})
    assert docx_resp.status_code == 200
    assert docx_resp.content[:2] == b"PK"

    pdf_resp = client.post("/api/export/pdf", json={"content": sample_md, "title": "Solid-State Batteries", "filename": "ssb"})
    assert pdf_resp.status_code == 200
    assert pdf_resp.content[:4] == b"%PDF"

    # 4. Verify live report Edit/Save PUT endpoint
    edit_filename = "test_editable_dossier.md"
    edit_path = settings.output_dir / edit_filename
    edit_path.write_text(sample_md, encoding="utf-8")
    try:
        updated_md = sample_md.replace("450 Wh/kg", "510 Wh/kg")
        put_resp = client.put(f"/api/reports/{edit_filename}", json={"content": updated_md})
        assert put_resp.status_code == 200
        assert put_resp.json()["status"] == "updated"
        assert "510 Wh/kg" in edit_path.read_text(encoding="utf-8")
    finally:
        if edit_path.exists():
            edit_path.unlink()

    # 5. Verify pdf_only source scope skips external web search calls
    with patch.object(agent.search_tool, "search") as mock_search:
        agent.deep_crawl_topic(topic="Private Local Study", source_scope="pdf_only")
        mock_search.assert_not_called()


