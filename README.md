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
