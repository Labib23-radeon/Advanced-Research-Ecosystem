# Advanced Research Studio

An everyday, reliable autonomous research workstation that works **100% locally offline**, **across your local Wi-Fi network**, or with **any OpenAI-compatible AI API** (Groq, Gemini, OpenRouter, LM Studio, or local Ollama) — with an automatic **Built-in Fact Engine** fallback so it never stops working even with zero external LLMs.

---

## Key Capabilities

1. **Always Available AI Engine Routing**:
   - **Auto Mode**: Uses local **Ollama** when running, falls back to any configured **OpenAI-compatible endpoint**, or uses the **Offline Fact Engine** automatically.
   - Configure providers, API keys (stored safely in `data/user_settings.json` and masked on reads), and live connection tests inside the in-app **Settings & System Health** panel.
2. **Multi-Engine Web Discovery + Persistent Cache**:
   - Searches across **DuckDuckGo**, **Semantic Scholar**, **Wikipedia**, and **arXiv**, with retries and persistent SQLite caching (`data/studio_cache.db`) so source inspection works fast even offline or after restarts.
3. **Universal Document Ingestion**:
   - Drag and drop **`.pdf`**, **`.docx`**, **`.txt`**, **`.md`**, **`.csv`**, or **`.json`** files directly onto the research composer to index into ChromaDB / BM25 vector memory and query locally (`Attached Document Only` mode supports 100% offline study).
4. **Mature Everyday Studio**:
   - Purpose presets (**Executive Brief**, **Academic Review**, **Compare A vs B**, **Study Guide**, **Decision Memo**).
   - Quick-Jump section outline bar, interactive 16:9 Slide Deck, in-place Markdown Editor & Save, Dossier Bookmarks (★ Star) and Rename.
   - Native exports to **Microsoft Word (`.docx`)**, **PDF (`.pdf`)**, **Markdown (`.md`)**, **CSV Tables (`.csv`)**, **HTML**, **JSON**, **Rich-Text Copy**, and Print view.
   - **Direct Interactive Questioning** strictly scoped to the researched topic with optional live **Web Augment** toggle.

---

## Quick Launch

### Option 1: One-Click Windows Web Studio
Double-click [`run_web.bat`](run_web.bat) — it creates `.venv` if needed, boots the FastAPI backend on port `8080` (or next free port), and opens the browser automatically once ready.

### Option 2: Share Across Wi-Fi (Phone / Tablet / Team)
Double-click [`run_lan.bat`](run_lan.bat) or run:
```bash
.venv\Scripts\python.exe main.py --ui --lan --open --port 8080
```
Open the printed **Network URL** (`http://<your-ip>:8080`) on any device on the same Wi-Fi network.

### Option 3: Terminal CLI
```bash
.venv\Scripts\python.exe main.py
# Or single non-interactive query:
.venv\Scripts\python.exe main.py --topic "Solid-State Batteries" --pdf "data/uploads/paper.pdf"
```

---

## Running Tests

```bash
.venv\Scripts\pytest -v
```
=======
# Advanced Research Ecosystem

**Local-first autonomous AI research agent.** Give it a topic and it plans sub-queries, searches the web, reads pages and PDFs, remembers the evidence in a vector store, and writes a Markdown report with numbered inline citations. The language model runs on your own machine through [Ollama](https://ollama.com), so there are no API keys and no per-query cost.

Built for the **CSE 3202 Artificial Intelligence Sessional**, Department of CSE, Bangladesh Army University of Science and Technology (BAUST).

![Research workspace](docs/workspace.png)

## Features

- **ReAct agent loop.** Reason, Act and Observe cycles with a live step trace.
- **Multi-engine search.** DuckDuckGo, Wikipedia and arXiv, selectable in the interface.
- **Local models.** Works with Ollama models such as `llama3.2:3b`, `qwen2.5:7b`, `mistral:7b` and `deepseek-r1:7b`.
- **Six-tier JSON recovery parser.** Keeps the loop running when small models return malformed output.
- **Vector memory.** ChromaDB with `all-MiniLM-L6-v2` embeddings; text is split into 500-character chunks with 100-character overlap.
- **PDF and URL ingestion.** Attach your own documents or target pages.
- **Dual-mode synthesis.** LLM-written prose plus an extractive mode that pulls numbers directly from sources.
- **Follow-up Q&A.** Ask questions over the stored evidence (retrieval-augmented generation).
- **Web workspace and CLI.** Research Studio, Repository of saved dossiers, Vector Memory explorer, Sandbox Tools, plus a Rich command-line interface.

## How it works

The interface shows five stages: **Plan, Multi-Search, Deep Crawl, Vector Index, Synthesize**.

Each step is one model call that returns JSON:

```json
{"thought": "...", "action": "web_search", "action_input": {"query": "..."}}
```

Allowed actions: `web_search`, `scrape_page`, `load_pdf`, `vector_search`, `finish_research`.

![Architecture](docs/architecture.png)

## Project structure

```
main.py                 CLI entry point
web_app.py              FastAPI backend (REST + SSE streaming)
core/agent_engine.py    ReAct loop, working memory, JSON parser, synthesis
core/prompts.py         System prompt and prompt templates
tools/                  Search, scraper, PDF loader, vector store
web_ui/                 index.html, style.css, app.js
tests/                  Unit tests
data/                   uploads/, outputs/, chroma_db/
```

## Getting started

**Requirements:** Python 3.11+ and Ollama installed and running.

```bash
git clone <your-repo-url>
cd <repo-folder>
pip install -r requirements.txt
ollama pull llama3.2:3b
```

Run the web workspace (open the address printed in the terminal):

```bash
python web_app.py
```

Or use the command line:

```bash
python main.py
```

No API keys or secrets are needed. The `data/` folders are created on first run.

## Usage

1. Open the workspace and type a research topic.
2. Choose a depth (Quick, Standard or Deep) and the sources to search.
3. Optionally attach a PDF or add target URLs.
4. Press **Deploy Research** and watch the live trace.
5. Open the finished dossier from the **Repository**, or ask follow-up questions.

| Workspace | Purpose |
|---|---|
| Research Studio | Start runs and watch progress |
| Repository | Browse, preview, download and delete saved dossiers |
| Vector Memory | Inspect stored chunks and run semantic search |
| Sandbox Tools | Test search, page extraction and PDF indexing separately |

## Testing

```bash
python -m pytest tests/
```

The tests cover JSON parser repair, PDF chunking and the ChromaDB round-trip.

## Privacy

Model inference, vector storage and reports stay on your machine. Search queries and page requests still go to the search services and websites being read, so avoid putting confidential terms in queries.

## Limitations

- 3B to 7B models reason less deeply than large hosted models.
- Citations show where a claim came from, not that the claim is correct.
- Short or ambiguous non-technical topics can send the planner to off-topic pages.
- Scanned PDFs (no text layer) and paywalled pages are not supported.
- The embedding model is English-centred.

## Future work

- Relevance check on retrieved pages and clarifying questions for ambiguous topics.
- Claim-level verification of each sentence against its cited chunk.
- OCR for scanned PDFs and multilingual embeddings.

## Authors

- **MD. Touhid Hossain Labib**: backend (agent engine, tools, memory, API)
- **Most. Asma Akter**: UI and frontend

## License

Add a license of your choice (for example MIT).
>>>>>>> 2b90efb2fda3d49c29ec32af6d9f4b2f39f1d19d
