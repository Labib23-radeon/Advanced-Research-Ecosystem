"""Unit and integration tests for local research agent components."""
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pypdf import PdfWriter

from core.agent_engine import RobustJSONParser, LocalResearchAgent
from tools.local_search import DuckDuckGoSearchTool
from tools.local_scraper import WebScraperTool
from tools.pdf_loader import PDFLoaderTool
from tools.vector_store import LocalVectorStore
from core.config import settings


# ==========================================
# 1. JSON Fallback Parser Tests
# ==========================================

def test_json_parser_clean_json():
    raw = '{"thought": "Need to find facts", "action": "web_search", "action_input": {"query": "AI research"}}'
    parsed = RobustJSONParser.parse_action(raw)
    assert parsed["action"] == "web_search"
    assert parsed["action_input"]["query"] == "AI research"
    assert "facts" in parsed["thought"]


def test_json_parser_markdown_codeblock():
    raw = """Here is my plan:
```json
{
  "thought": "Searching for details",
  "action": "web_search",
  "action_input": {"query": "deep learning"}
}
```
Let me know if you need more."""
    parsed = RobustJSONParser.parse_action(raw)
    assert parsed["action"] == "web_search"
    assert parsed["action_input"]["query"] == "deep learning"


def test_json_parser_single_quotes_and_trailing_commas():
    raw = """
    {
      'thought': 'Fixing trailing commas and single quotes',
      'action': 'scrape_page',
      'action_input': {'url': 'https://example.com/article'},
    }
    """
    parsed = RobustJSONParser.parse_action(raw)
    assert parsed["action"] == "scrape_page"
    assert parsed["action_input"]["url"] == "https://example.com/article"


def test_json_parser_fuzzy_react():
    raw = """Thought: I should search for local SLM advances.
Action: web_search
Action Input: {"query": "small language models 2026"}
Observation: Pending..."""
    parsed = RobustJSONParser.parse_action(raw)
    assert parsed["action"] == "web_search"
    assert parsed["action_input"]["query"] == "small language models 2026"


def test_json_parser_finish_research():
    raw = '{"thought": "Finished researching", "action": "finish_research", "action_input": {"summary_points": ["Fact 1", "Fact 2"]}}'
    parsed = RobustJSONParser.parse_action(raw)
    assert parsed["action"] == "finish_research"
    assert len(parsed["action_input"]["summary_points"]) == 2


# ==========================================
# 2. Scraper Tests
# ==========================================

def test_scraper_invalid_url():
    scraper = WebScraperTool()
    res = scraper.scrape("not-a-valid-url")
    assert res["status"] == "error"
    assert "Invalid URL" in res["title"]


def test_scraper_clean_extraction():
    scraper = WebScraperTool()
    mock_html = """
    <html>
      <head><title>Test Page</title></head>
      <body>
        <nav><a href="#">Home</a></nav>
        <article>
          <h1>Breakthrough in AI</h1>
          <p>Local language models are running exceptionally fast on consumer edge devices with quantized 4-bit weights.</p>
        </article>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        res = scraper.scrape("https://test.example.com/ai")
        assert res["status"] == "success"
        assert "Local language models" in res["text"]
        assert "Copyright 2026" not in res["text"]


# ==========================================
# 3. PDF Loader & Chunker Tests
# ==========================================

def test_pdf_loader_chunking(tmp_path: Path):
    pdf_path = tmp_path / "sample_test.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # We can write minimal PDF
    with open(pdf_path, "wb") as f:
        writer.write(f)

    loader = PDFLoaderTool(chunk_size=100, chunk_overlap=20)
    # Test internal chunking function directly
    sample_text = "Sentence one about local AI. " * 10
    chunks = loader._chunk_text(sample_text)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


# ==========================================
# 4. Local Vector Store Tests
# ==========================================

def test_vector_store_in_memory_or_temp(tmp_path: Path):
    store = LocalVectorStore(
        collection_name="test_collection",
        persist_dir=str(tmp_path / "chroma_test"),
    )
    # Add items
    docs = [
        "Llama 3.2 3B is an efficient lightweight model developed for edge devices.",
        "Quantum computing uses qubits and superposition for complex simulations.",
        "ChromaDB is an open source embedding database.",
    ]
    metas = [
        {"topic": "AI", "source": "meta.com"},
        {"topic": "Physics", "source": "nature.com"},
        {"topic": "Databases", "source": "chroma.org"},
    ]
    added = store.add_texts(docs, metadatas=metas)
    assert added == 3
    assert store.count() == 3

    # Query
    results = store.query("Which model is good for edge devices?", n_results=2)
    assert len(results) >= 1
    assert "Llama 3.2" in results[0]["text"]

    # Clear
    store.clear()
    assert store.count() == 0


# ==========================================
# 5. Agent ReAct Cycle Mock Test
# ==========================================

def test_agent_research_mock_cycle(tmp_path: Path):
    test_out = tmp_path / "outputs"
    test_out.mkdir(parents=True, exist_ok=True)
    settings.output_dir = test_out

    agent = LocalResearchAgent(model_name="mock-model")

    mock_step_1 = json.dumps({
        "thought": "I will search for the history of python.",
        "action": "web_search",
        "action_input": {"query": "python language history"}
    })
    mock_step_2 = json.dumps({
        "thought": "I have enough information.",
        "action": "finish_research",
        "action_input": {"summary_points": ["Created by Guido van Rossum", "Released in 1991"]}
    })
    mock_synthesis = (
        "# Python History Report\n\n"
        "## Executive Summary\nPython was created by Guido van Rossum in 1991 [1].\n\n"
        "## References\n[1] https://python.org"
    )

    with patch.object(agent, "check_ollama_health", return_value=(True, "Online")):
        with patch.object(agent, "_call_ollama", side_effect=[mock_step_1, mock_step_2, mock_synthesis]):
            with patch.object(agent.search_tool, "search", return_value=[{"title": "Python History", "href": "https://python.org", "body": "Guido created Python in 1991."}]):
                with patch.object(agent.scraper_tool, "scrape", return_value={"url": "https://python.org", "title": "Python History", "text": "Guido created Python in 1991.", "status": "success"}):
                    report_text, report_file = agent.research(topic="History of Python")

                    assert "Python" in report_text
                    assert report_file.exists()
                    assert report_file.name.endswith(".md")
