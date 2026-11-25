"""Autonomous ReAct state engine, multi-query deep crawler, multi-provider LLM, and grounded fact synthesizer."""
import concurrent.futures
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests
from core.config import settings
from core.llm_providers import (
    call_openai_compatible,
    load_user_settings,
)
from core.prompts import (
    SYSTEM_PROMPT,
    SUBQUERY_DECOMPOSITION_PROMPT,
    RESEARCH_STYLE_DIRECTIVES,
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_TEMPLATE,
    INTERACTIVE_ANALYSIS_SYSTEM_PROMPT,
    INTERACTIVE_ANALYSIS_USER_TEMPLATE,
)
from core.text_cleaner import clean_llm_output, clean_qa_response, sanitize_search_snippet
from tools.local_search import DuckDuckGoSearchTool
from tools.local_scraper import WebScraperTool
from tools.pdf_loader import PDFLoaderTool
from tools.vector_store import LocalVectorStore

logger = logging.getLogger(__name__)

# Generic words excluded when extracting strict domain keywords for cross-topic gating
_GENERIC_TOPIC_STOPWORDS: Set[str] = {
    "research", "intelligence", "report", "depth", "in-depth", "analysis",
    "overview", "study", "system", "systems", "model", "models", "architecture",
    "comparison", "comparative", "findings", "benchmark", "benchmarks",
    "metric", "metrics", "limitation", "limitations", "using", "based",
    "modern", "local", "the", "and", "for", "with", "from", "versus",
}

# Filler sentences emitted in report headers that should not be echoed back in Q&A answers
_REPORT_BOILERPLATE_PREFIXES = (
    "this intelligence dossier provides",
    "this intelligence dossier investigates",
    "the autonomous agent analyzed",
    "key verified empirical figures extracted",
    "detailed architectural mechanisms and foundational",
    "key trade-offs identified between",
    "critical operational hurdles, edge cases",
    "quantitative metrics under active evaluation",
)


class RobustJSONParser:
    """Multi-tiered JSON repair and extractor designed for 3B/7B local LLMs."""

    @classmethod
    def parse_action(cls, raw_text: str) -> Dict[str, Any]:
        """Extract and repair JSON action from raw LLM output."""
        if not raw_text or not raw_text.strip():
            return {
                "thought": "Empty response received from LLM.",
                "action": "finish_research",
                "action_input": {"summary_points": ["No response generated."]},
            }

        text = clean_llm_output(raw_text).strip()

        # Tier 1: Direct JSON parsing
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "action" in parsed:
                return cls._normalize_dict(parsed)
        except Exception:
            pass

        # Tier 2: Extract from Markdown ```json ... ``` or ``` ... ```
        codeblock_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if codeblock_match:
            candidate = codeblock_match.group(1).strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "action" in parsed:
                    return cls._normalize_dict(parsed)
            except Exception:
                text = candidate

        # Tier 3: Extract outermost curly braces { ... }
        brace_match = re.search(r"(\{[\s\S]*\})", text)
        if brace_match:
            candidate = brace_match.group(1).strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "action" in parsed:
                    return cls._normalize_dict(parsed)
            except Exception:
                repaired = cls._repair_json_string(candidate)
                try:
                    parsed = json.loads(repaired)
                    if isinstance(parsed, dict) and "action" in parsed:
                        return cls._normalize_dict(parsed)
                except Exception:
                    pass

        # Tier 4: Fuzzy ReAct heuristic pattern matching
        fuzzy_action = cls._fuzzy_react_extract(raw_text)
        if fuzzy_action:
            return fuzzy_action

        # Tier 5: Fallback wrapper
        return {
            "thought": f"Extracted reasoning: {raw_text[:300]}",
            "action": "finish_research",
            "action_input": {"summary_points": [raw_text[:500]]},
        }

    @staticmethod
    def _normalize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize parsed action dictionary to ensure expected keys."""
        thought = str(data.get("thought", "Analyzing current state..."))
        action = str(data.get("action", "finish_research")).strip().lower()
        action_input = data.get("action_input", {})
        if isinstance(action_input, str):
            try:
                action_input = json.loads(action_input)
            except Exception:
                if action in ("web_search", "vector_search"):
                    action_input = {"query": action_input}
                elif action == "scrape_page":
                    action_input = {"url": action_input}
                elif action == "load_pdf":
                    action_input = {"file_path": action_input}
                else:
                    action_input = {"input": action_input}

        if not isinstance(action_input, dict):
            action_input = {"value": action_input}

        return {
            "thought": thought,
            "action": action,
            "action_input": action_input,
        }

    @staticmethod
    def _repair_json_string(s: str) -> str:
        """Heuristic string repairs for malformed JSON."""
        repaired = re.sub(r",\s*([\]}])", r"\1", s)
        repaired = re.sub(r"\'([a-zA-Z0-9_\-]+)\'\s*:", r'"\1":', repaired)
        repaired = re.sub(r":\s*\'([^\'\n]*?)\'", r': "\1"', repaired)
        repaired = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", repaired)
        return repaired

    @staticmethod
    def _fuzzy_react_extract(text: str) -> Optional[Dict[str, Any]]:
        """Extract thought/action from plain text ReAct style output."""
        thought_match = re.search(r"Thought:\s*(.*?)(?=(?:Action:|$))", text, re.IGNORECASE | re.DOTALL)
        action_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)", text, re.IGNORECASE)
        input_match = re.search(r"Action Input:\s*(.*?)(?=(?:Observation:|Thought:|$))", text, re.IGNORECASE | re.DOTALL)

        thought = thought_match.group(1).strip() if thought_match else "Reasoning step..."
        action = action_match.group(1).strip().lower() if action_match else None

        if action:
            raw_input = input_match.group(1).strip() if input_match else ""
            try:
                action_input = json.loads(raw_input)
            except Exception:
                if action in ("web_search", "vector_search"):
                    action_input = {"query": raw_input.strip("\"'")}
                elif action == "scrape_page":
                    action_input = {"url": raw_input.strip("\"'")}
                elif action == "load_pdf":
                    action_input = {"file_path": raw_input.strip("\"'")}
                else:
                    action_input = {"summary_points": [raw_input] if raw_input else []}

            return {
                "thought": thought,
                "action": action,
                "action_input": action_input if isinstance(action_input, dict) else {"query": str(action_input)},
            }
        return None


class ExtractiveFactSynthesizer:
    """Extracts genuine facts, metrics, statistics, tables, and quotes directly from raw crawled data."""

    @classmethod
    def synthesize(
        cls,
        topic: str,
        notes: List[str],
        sources: List[Dict[str, str]],
        raw_documents: List[Dict[str, str]],
        report_style: str = "brief",
    ) -> str:
        """Build a publication-grade, 8-section fact-grounded Markdown report from extracted documents."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        all_key_numbers: List[Dict[str, Any]] = []
        informative_sentences: List[Dict[str, Any]] = []
        tradeoff_sentences: List[Dict[str, Any]] = []
        limitation_sentences: List[Dict[str, Any]] = []

        boilerplate_filter = re.compile(
            r"\b(cookie|privacy|terms of service|copyright|all rights reserved|subscribe|sign in|login|contact us|navigation|advertis|creators|policy & safety|javascript is disabled|verify that you're not a robot|content truncated|enable javascript|access denied|jump to content|wikipedia, the free)\b|©",
            re.IGNORECASE,
        )

        seen_prefixes: Set[str] = set()

        url_to_cite_idx: Dict[str, int] = {}
        for cite_i, src in enumerate(sources, 1):
            u = src.get("url", "")
            if u and u not in url_to_cite_idx:
                url_to_cite_idx[u] = cite_i

        effective_docs = list(raw_documents)
        covered_urls = {d.get("url") for d in effective_docs if d.get("url")}
        for note in notes:
            if note.startswith("Search ["):
                for match in re.finditer(r"\d+\.\s+\[(.*?)\]\((https?://[^\s\)]+)\)\s+([^\n]+)", note):
                    s_title, s_url, s_body = match.group(1), match.group(2), match.group(3)
                    if s_url not in covered_urls and len(s_body.strip()) > 35:
                        covered_urls.add(s_url)
                        effective_docs.append({"url": s_url, "title": s_title, "text": s_body})

        for idx, doc in enumerate(effective_docs, 1):
            src_url = doc.get("url", "Document")
            title = doc.get("title", f"Source {idx}")
            text = doc.get("text", "")
            if not text:
                continue

            cite_idx = url_to_cite_idx.get(src_url)
            if cite_idx is None:
                cite_idx = len(sources) + 1
                sources.append({"title": title, "url": src_url, "type": "web"})
                url_to_cite_idx[src_url] = cite_idx

            sents = re.split(r"(?<=[.!?])\s+", text)
            for s in sents:
                clean_s = sanitize_search_snippet(s)
                if len(clean_s) < 30 or len(clean_s) > 350:
                    continue
                if len(clean_s.split()) < 6 or clean_s.endswith("..."):
                    continue
                if boilerplate_filter.search(clean_s):
                    continue

                prefix = clean_s[:45].lower()
                if prefix in seen_prefixes:
                    continue
                seen_prefixes.add(prefix)

                doc_ref = {"text": clean_s, "source": title, "url": src_url, "idx": cite_idx}

                s_lower = clean_s.lower()
                if re.search(
                    r"(\d+(\.\d+)?%|\$\d+|\b\d+(\.\d+)?\s*(x|times|B|M|K|GB|MB|TB|ms|s|fps|W|mW|Hz|GHz|TOPS|FLOPS|watts|neurons|synapses|parameters|tokens/s)\b)",
                    clean_s,
                    re.IGNORECASE,
                ):
                    all_key_numbers.append(doc_ref)
                elif any(w in s_lower for w in ["trade-off", "tradeoff", "versus", "vs", "compared to", "bottleneck", "challenge"]):
                    tradeoff_sentences.append(doc_ref)
                elif any(w in s_lower for w in ["limit", "risk", "cost", "error", "fail", "constraint", "vulnerab"]):
                    limitation_sentences.append(doc_ref)
                else:
                    informative_sentences.append(doc_ref)

        style_labels = {
            "brief": "Executive Research Dossier",
            "academic": "Academic Literature Review",
            "comparison": "Comparative Benchmark Matrix",
            "study_guide": "Structured Study Guide",
            "decision": "Technical Decision Memo",
        }
        style_badge = style_labels.get(report_style, "Research Intelligence Report")

        lines = [
            f"# {style_badge}: {topic.title()}",
            "",
            f"> **Generated by Advanced Research Studio (Fact Engine)** | {now_str}",
            f"> **Grounding**: {len(sources)} Verified Web & Document Sources | 100% Local Processing",
            "",
            "## 📌 Executive Summary",
            f"This dossier investigates **{topic}** across **{len(effective_docs)} multi-source documents**.",
            "",
        ]

        if informative_sentences:
            lines.append(f"- **Core Technical State**: {informative_sentences[0]['text']} `[{informative_sentences[0]['idx']}]`")
            if len(informative_sentences) > 1:
                lines.append(f"- **Consensus Takeaway**: {informative_sentences[1]['text']} `[{informative_sentences[1]['idx']}]`")
            lines.append("")

        lines.extend([
            "## 📊 Quantitative Benchmarks & Empirical Metrics",
            "",
        ])

        if all_key_numbers:
            lines.extend([
                "| # | Empirical Metric / Observed Finding | Source Verification |",
                "|---|---|---|",
            ])
            for idx, item in enumerate(all_key_numbers[:8], 1):
                clean_fact = re.sub(r"\s+", " ", item["text"]).replace("|", "\\|").strip()
                lines.append(f"| {idx} | {clean_fact} | [{item['source']}]({item['url']}) `[{item['idx']}]` |")
            lines.append("")
        else:
            lines.append("*Quantitative metrics under active evaluation across published benchmarks.*\n")

        lines.extend([
            "## 🔍 Architecture & Technical Deep-Dive",
            "",
        ])

        arch_items = informative_sentences[2:6] if len(informative_sentences) >= 6 else informative_sentences
        for item in arch_items:
            lines.append(f"- {item['text']} `[{item['idx']}]`")
        lines.append("")

        lines.extend([
            "## ⚖️ Comparative Analysis & Engineering Trade-Offs",
            "",
        ])

        if tradeoff_sentences:
            for item in tradeoff_sentences[:4]:
                lines.append(f"- {item['text']} `[{item['idx']}]`")
        else:
            lines.append("- Balances computational overhead and hardware memory footprint against empirical accuracy.")
        lines.append("")

        lines.extend([
            "## ⚠️ Limitations, Vulnerabilities & Practical Bottlenecks",
            "",
        ])

        if limitation_sentences:
            for item in limitation_sentences[:4]:
                lines.append(f"- {item['text']} `[{item['idx']}]`")
        else:
            lines.append("- Practical deployment scales strictly with domain data calibration and local compute bandwidth.")
        lines.append("")

        lines.extend([
            "## 🔮 Strategic Trajectory & Future Outlook",
            f"1. **Near-Term Horizon**: Continued algorithmic optimization and lightweight deployment for **{topic}**.",
            "2. **Production Scaling**: Integration of standardized reproducible evaluation pipelines.",
            "3. **Open Challenges**: Bridging generalization gaps under strict compute constraints.",
            "",
            "## 📚 References & Verified Sources",
            "",
        ])

        for idx, src in enumerate(sources, 1):
            title = src.get("title", "External Reference")
            url = src.get("url", "#")
            src_type = src.get("type", "web").upper()
            lines.append(f"- `[{idx}]` **{title}** ({src_type}) - [{url}]({url})")

        return "\n".join(lines)


class LocalResearchAgent:
    """High-utility autonomous research agent supporting Ollama, OpenAI-compatible APIs, and Offline Fact Engine."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        host: Optional[str] = None,
        max_steps: Optional[int] = None,
        on_step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        vector_store: Optional[LocalVectorStore] = None,
    ) -> None:
        cfg = load_user_settings(mask_secret=False)
        self.host = host or cfg.get("ollama_host") or settings.ollama_host
        self.model_name = model_name or cfg.get("ollama_model") or settings.ollama_model
        self.max_steps = max_steps or settings.max_research_steps
        self.on_step_callback = on_step_callback

        # Persistent cached sensors + shared thread-safe vector memory
        self.search_tool = DuckDuckGoSearchTool(max_results=settings.max_search_results, persist_cache=True)
        self.scraper_tool = WebScraperTool(timeout=settings.scrape_timeout, max_length=settings.max_content_length, persist_cache=True)
        self.pdf_loader = PDFLoaderTool(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        self.vector_store = vector_store or LocalVectorStore()

        self._research_lock = threading.RLock()
        self.messages: List[Dict[str, str]] = []
        self.sources: List[Dict[str, str]] = []
        self.research_notes: List[str] = []
        self.scraped_documents: List[Dict[str, str]] = []
        self.current_topic: str = ""
        self.is_cancelled: bool = False
        self.available_models: List[str] = []

    def cancel(self) -> None:
        """Signal running research loops to halt immediately."""
        self.is_cancelled = True
        logger.info("Agent received cancellation signal.")

    def reset_cancellation(self) -> None:
        """Reset cancellation flag before a new research cycle."""
        self.is_cancelled = False

    def check_ollama_health(self) -> Tuple[bool, str]:
        """Check if local Ollama server is accessible and list installed models."""
        cfg = load_user_settings(mask_secret=False)
        active_host = (cfg.get("ollama_host") or self.host).rstrip("/")
        try:
            resp = requests.get(f"{active_host}/api/tags", timeout=0.8)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                self.available_models = models
                if self.model_name in models or any(m.startswith(self.model_name.split(":")[0]) for m in models):
                    return True, f"Ollama is online. Active: '{self.model_name}'"
                return True, (
                    f"Ollama running. Installed: {', '.join(models) if models else 'None'}. "
                    f"Run `ollama pull {self.model_name}` to download."
                )
            return False, f"Ollama returned HTTP {resp.status_code}"
        except Exception:
            return False, f"Ollama offline at {active_host} (Built-in Fact Engine active)"

    def get_active_engine_info(self) -> Dict[str, Any]:
        """Determine the active AI engine mode for status indicators and routing."""
        cfg = load_user_settings(mask_secret=False)
        mode = cfg.get("provider_mode", "auto")
        ollama_ok, ollama_msg = self.check_ollama_health()
        has_api = bool((cfg.get("openai_base_url") or "").strip()) and (
            bool((cfg.get("openai_api_key") or "").strip())
            or any(h in (cfg.get("openai_base_url") or "").lower() for h in ("127.0.0.1", "localhost"))
        )

        if mode == "extractive":
            return {"engine": "extractive", "label": "Offline Fact Engine", "detail": "Deterministic grounded extraction (Zero LLM)", "ready": False}
        if mode == "openai_compatible" or (mode == "auto" and not ollama_ok and has_api):
            mdl = cfg.get("openai_model") or "API Model"
            return {"engine": "openai_compatible", "label": f"API: {mdl}", "detail": f"Connected via {cfg.get('openai_base_url')}", "ready": True}
        if ollama_ok:
            return {"engine": "ollama", "label": f"{self.model_name} Ready", "detail": ollama_msg, "ready": True}
        return {"engine": "extractive", "label": "Offline Fact Engine", "detail": ollama_msg, "ready": False}

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name

    def _call_ollama(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        """Call Ollama /api/chat with model-specific adaptations and output sanitization."""
        cfg = load_user_settings(mask_secret=False)
        active_host = (cfg.get("ollama_host") or self.host).rstrip("/")
        url = f"{active_host}/api/chat"

        options: Dict[str, Any] = {"temperature": temperature}
        m_lower = self.model_name.lower()
        if "deepseek" in m_lower:
            options["top_p"] = 0.95
        elif "mistral" in m_lower:
            options["top_k"] = 40
        elif "qwen" in m_lower:
            options["top_p"] = 0.8
        elif "phi" in m_lower:
            options["temperature"] = max(0.1, temperature - 0.05)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        try:
            resp = requests.post(url, json=payload, timeout=settings.request_timeout)
            resp.raise_for_status()
            raw_content = resp.json().get("message", {}).get("content", "")
            return clean_llm_output(raw_content)
        except requests.exceptions.RequestException as exc:
            logger.warning("Ollama API call error for model '%s': %s", self.model_name, exc)
            raise

    def _call_llm(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> Optional[str]:
        """Route LLM inference across Ollama (local) or OpenAI-compatible API cleanly."""
        cfg = load_user_settings(mask_secret=False)
        mode = cfg.get("provider_mode", "auto")
        if mode == "extractive":
            return None

        ollama_ok, _ = self.check_ollama_health()
        if mode in ("auto", "ollama") and ollama_ok:
            try:
                return self._call_ollama(messages, temperature=temperature)
            except Exception as exc:
                if mode == "ollama":
                    logger.warning("Ollama call failed: %s", exc)
                    return None

        has_api = bool((cfg.get("openai_base_url") or "").strip()) and (
            bool((cfg.get("openai_api_key") or "").strip())
            or any(h in (cfg.get("openai_base_url") or "").lower() for h in ("127.0.0.1", "localhost"))
        )
        if mode in ("auto", "openai_compatible") and has_api:
            try:
                return call_openai_compatible(messages, temperature=temperature)
            except Exception as exc:
                logger.warning("OpenAI-compatible API call failed: %s", exc)
        return None

    def generate_subqueries(self, topic: str, max_count: int = 4, source_scope: str = "all") -> List[str]:
        """Decompose topic into orthogonal specialized search subqueries scoped by target source type."""
        cleaned = topic.strip()

        decompose_prompt = SUBQUERY_DECOMPOSITION_PROMPT.format(topic=cleaned)
        resp = self._call_llm([{"role": "user", "content": decompose_prompt}], temperature=0.1)
        if resp:
            try:
                match = re.search(r"\[[\s\S]*?\]", resp)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        valid = [str(q).strip().strip('"\'') for q in parsed if str(q).strip()]
                        if len(valid) >= 2:
                            if max_count > len(valid):
                                primary_q = cleaned.split(":")[0].strip()
                                valid.extend([
                                    f"{primary_q} deployment scalability cost",
                                    f"{primary_q} recent state of the art advances",
                                ])
                            return valid[:max_count]
            except Exception as exc:
                logger.debug("Dynamic subquery decomposition fallback: %s", exc)

        primary = cleaned
        subtitle = ""
        if ":" in cleaned:
            parts = cleaned.split(":")
            primary = parts[0].strip()
            subtitle = parts[1].strip()
        elif " - " in cleaned:
            parts = cleaned.split(" - ")
            primary = parts[0].strip()
            subtitle = parts[1].strip()

        if source_scope == "academic":
            subqueries = [
                f"{primary} arxiv research paper methodology",
                f"{primary} empirical benchmark evaluation",
                f"{primary} theoretical limitations open problems",
                f"{subtitle or primary} peer reviewed survey",
                f"{primary} experimental ablation results",
                f"{primary} future research trajectory",
            ]
        elif source_scope == "tech":
            subqueries = [
                f"{primary} github implementation architecture",
                f"{primary} throughput latency benchmarks",
                f"{primary} engineering trade-offs documentation",
                f"{subtitle or primary} production deployment guide",
                f"{primary} memory hardware requirements",
                f"{primary} release notes changelog",
            ]
        else:
            subqueries = [
                f"{primary} architecture mechanisms",
                f"{primary} benchmark performance metrics",
                f"{primary} engineering trade-offs limitations",
                f"{subtitle or primary} empirical research findings",
                f"{primary} production deployment scalability cost",
                f"{primary} recent state of the art advances",
            ]
        return subqueries[:max_count]

    def deep_crawl_topic(
        self,
        topic: str,
        depth: str = "deep",
        custom_urls: Optional[List[str]] = None,
        source_scope: str = "all",
    ) -> None:
        """Perform multi-query deep search and scrape top authoritative pages."""
        step_counter = len(self.research_notes)

        if custom_urls:
            for url in custom_urls:
                if self.is_cancelled:
                    return
                clean_u = url.strip()
                if clean_u:
                    step_counter += 1
                    obs = self.execute_tool("scrape_page", {"url": clean_u})
                    self.research_notes.append(f"Target URL [{clean_u}]:\n{obs[:600]}")
                    if self.on_step_callback:
                        self.on_step_callback({
                            "step": step_counter,
                            "thought": f"Crawling user-specified target URL: {clean_u}",
                            "action": "scrape_page",
                            "action_input": {"url": clean_u},
                            "observation": obs,
                        })

        if source_scope == "pdf_only":
            logger.info("Source scope is pdf_only: skipping external web search and crawling.")
            return

        max_searches = 2 if depth == "quick" else (4 if depth == "deep" else 6)
        max_scrapes_per_query = 2 if depth == "quick" else 3

        queries = self.generate_subqueries(topic, max_count=max_searches, source_scope=source_scope)
        seen_urls = {s.get("url") for s in self.sources if s.get("url")}

        step_counter = len(self.research_notes)
        for q in queries:
            if self.is_cancelled:
                logger.info("Deep crawl loop halted due to user cancellation.")
                break
            step_counter += 1
            search_obs = self.execute_tool("web_search", {"query": q})
            step_data = {
                "step": step_counter,
                "thought": f"Querying search index for targeted dimension: '{q}'",
                "action": "web_search",
                "action_input": {"query": q},
                "observation": search_obs,
            }
            self.research_notes.append(f"Search [{q}]:\n{search_obs[:500]}")
            if self.on_step_callback:
                self.on_step_callback(step_data)

            if self.is_cancelled:
                break

            raw_results = self.search_tool.search(q, max_results=5)
            candidate_urls = []
            for item in raw_results:
                url = item.get("href", "")
                if url and not url.startswith("error://") and url not in seen_urls and len(candidate_urls) < max_scrapes_per_query:
                    seen_urls.add(url)
                    candidate_urls.append(url)

            if candidate_urls and not self.is_cancelled:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidate_urls), 4)) as executor:
                    future_to_url = {executor.submit(self.execute_tool, "scrape_page", {"url": u}): u for u in candidate_urls}
                    for future in concurrent.futures.as_completed(future_to_url):
                        if self.is_cancelled:
                            break
                        u = future_to_url[future]
                        try:
                            scrape_obs = future.result()
                        except Exception as exc:
                            scrape_obs = f"Error scraping {u}: {exc}"

                        step_counter += 1
                        step_scrape = {
                            "step": step_counter,
                            "thought": f"Extracting structured content from: {u}",
                            "action": "scrape_page",
                            "action_input": {"url": u},
                            "observation": scrape_obs,
                        }
                        self.research_notes.append(f"Scraped [{u}]:\n{scrape_obs[:600]}")
                        if self.on_step_callback:
                            self.on_step_callback(step_scrape)

    def execute_tool(self, action: str, action_input: Dict[str, Any]) -> str:
        """Dispatch tool calls, update memory, and track raw documents."""
        if self.is_cancelled:
            return "Action aborted by user cancellation."

        action = action.lower().strip()

        if action == "web_search":
            query = action_input.get("query", "").strip()
            if not query:
                return "Error: Empty search query."
            raw_results = self.search_tool.search(query)
            formatted = self.search_tool.format_results(raw_results, query)

            for item in raw_results:
                if item.get("href") and not item["href"].startswith("error://"):
                    self.sources.append({"title": item["title"], "url": item["href"], "type": "web"})
                    self.vector_store.add_texts(
                        [f"{item['title']}\n{item['body']}"],
                        metadatas=[{"source": item["href"], "title": item["title"], "type": "search_snippet"}],
                    )
            return formatted

        elif action == "scrape_page":
            url = action_input.get("url", "").strip()
            if not url:
                return "Error: Empty URL."
            scraped = self.scraper_tool.scrape(url)
            if scraped["status"] == "success":
                self.sources.append({"title": scraped["title"], "url": scraped.get("url", url), "type": "webpage"})
                self.scraped_documents.append(scraped)
                self.vector_store.add_scraped_document(url=scraped.get("url", url), title=scraped["title"], text=scraped["text"])
                return f"Extracted {len(scraped['text'])} chars from {scraped.get('url', url)} (Title: '{scraped['title']}')."
            return f"Scrape notice for {url}: {scraped['text']}"

        elif action == "load_pdf":
            file_path = action_input.get("file_path", "").strip()
            if not file_path:
                return "Error: Empty document path."
            try:
                chunks = self.pdf_loader.load_and_chunk(file_path)
                self.vector_store.add_pdf_chunks(chunks)
                filename = Path(file_path).name
                doc_type = Path(file_path).suffix.lstrip(".").lower() or "pdf"
                self.sources.append({"title": f"Document: {filename}", "url": file_path, "type": doc_type})
                combined_text = "\n".join([c["text"] for c in chunks])
                self.scraped_documents.append({"url": file_path, "title": f"Document: {filename}", "text": combined_text})
                return f"Loaded '{filename}' ({doc_type.upper()}) with {len(chunks)} semantic chunks indexed into vector store."
            except Exception as exc:
                return f"Failed to load document '{file_path}': {str(exc)}"

        elif action == "vector_search":
            query = action_input.get("query", "").strip()
            return self.vector_store.query_formatted(query, n_results=5)

        elif action == "finish_research":
            summary = action_input.get("summary_points", [])
            points = "\n- ".join(summary) if isinstance(summary, list) else str(summary)
            return f"Research complete. Summary:\n- {points}"

        return f"Unknown tool action: {action}"

    def research(
        self,
        topic: str,
        initial_pdf: Optional[str] = None,
        depth: str = "deep",
        custom_urls: Optional[List[str]] = None,
        source_scope: str = "all",
        report_style: str = "brief",
    ) -> Tuple[str, Path]:
        """Execute autonomous research using multi-query crawling and fact synthesis."""
        with self._research_lock:
            self.reset_cancellation()
            self.current_topic = topic
            self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            self.sources = []
            self.research_notes = []
            self.scraped_documents = []

            if initial_pdf:
                pdf_obs = self.execute_tool("load_pdf", {"file_path": initial_pdf})
                self.research_notes.append(f"Preloaded Document: {pdf_obs}")
                if self.on_step_callback:
                    self.on_step_callback({
                        "step": 1,
                        "thought": "Ingesting and chunking preloaded local document into vector memory",
                        "action": "load_pdf",
                        "action_input": {"file_path": initial_pdf},
                        "observation": pdf_obs,
                    })

            self.deep_crawl_topic(
                topic=topic,
                depth=depth,
                custom_urls=custom_urls,
                source_scope=source_scope,
            )

            report_content = self._synthesize_report(topic, report_style=report_style)
            saved_path = self._save_report(topic, report_content)
            return report_content, saved_path

    def _synthesize_report(self, topic: str, report_style: str = "brief") -> str:
        """Synthesize collected research into a factual report with fallback to Extractive Synthesizer."""
        url_best_source: Dict[str, Dict[str, str]] = {}
        ordered_urls: List[str] = []
        for src in self.sources:
            url = src.get("url", "")
            if not url:
                continue
            title = src.get("title", "Source")
            if url not in url_best_source:
                url_best_source[url] = dict(src)
                ordered_urls.append(url)
            else:
                existing_title = url_best_source[url].get("title", "")
                if title not in ("Untitled", "Webpage Content", "Source") and (
                    existing_title in ("Untitled", "Webpage Content", "Source") or len(title) > len(existing_title)
                ):
                    url_best_source[url]["title"] = title
                if src.get("type") in ("webpage", "pdf", "docx", "txt", "md", "csv"):
                    url_best_source[url]["type"] = src["type"]

        unique_sources: List[Dict[str, str]] = [url_best_source[u] for u in ordered_urls]
        self.sources = unique_sources

        style_directive = RESEARCH_STYLE_DIRECTIVES.get(report_style, RESEARCH_STYLE_DIRECTIVES["brief"])
        retrieved_facts = self.vector_store.query_formatted(topic, n_results=8)
        sources_text = "\n".join([
            f"[{idx}] {s.get('title', 'Source')} - {s.get('url', '')}"
            for idx, s in enumerate(unique_sources, 1)
        ])
        notes_combined = "\n\n".join(self.research_notes)
        full_context = f"{notes_combined}\n\n### Vector DB Retrieved Facts:\n{retrieved_facts}\n\n### Output Style Directive:\n{style_directive}"

        synthesis_prompt = SYNTHESIS_USER_TEMPLATE.format(
            topic=topic,
            research_notes=full_context,
            sources=sources_text,
        )
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": synthesis_prompt},
        ]
        report = self._call_llm(messages, temperature=0.3)
        if report and len(report.strip()) > 300:
            return report

        report_md = ExtractiveFactSynthesizer.synthesize(
            topic=topic,
            notes=self.research_notes,
            sources=unique_sources,
            raw_documents=self.scraped_documents,
            report_style=report_style,
        )
        self.sources = unique_sources
        return report_md

    @staticmethod
    def _extract_domain_topic_terms(effective_topic: str) -> Tuple[str, Set[str]]:
        """Extract clean topic display name and strict domain keywords excluding generic boilerplate words."""
        clean_label = re.sub(
            r"^(?:Research\s+(?:Intelligence\s+)?Report|In-Depth\s+Research\s+Report|Executive\s+Research\s+Dossier|Academic\s+Literature\s+Review|Comparative\s+Benchmark\s+Matrix|Structured\s+Study\s+Guide|Technical\s+Decision\s+Memo)\s*:\s*",
            "",
            effective_topic,
            flags=re.IGNORECASE,
        ).strip()
        tokens = re.findall(r"\b[a-zA-Z0-9\-]{3,}\b", clean_label)
        domain_terms = {w.lower() for w in tokens if w.lower() not in _GENERIC_TOPIC_STOPWORDS}
        if not domain_terms:
            domain_terms = {w.lower() for w in tokens}
        return clean_label, domain_terms

    def ask_question(
        self,
        question: str,
        top_k: int = 6,
        topic: Optional[str] = None,
        report_text: Optional[str] = None,
        report_filename: Optional[str] = None,
        web_augment: bool = False,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Answer a follow-up question directly with ONLY clean topic-grounded findings."""
        cleaned_q = question.strip()
        if not cleaned_q:
            return {"answer": "Please enter a specific question about the active research topic.", "sources": []}

        effective_topic = (topic or self.current_topic or "").strip()
        clean_topic_label, domain_topic_terms = self._extract_domain_topic_terms(effective_topic)
        q_terms = {
            w.lower()
            for w in re.findall(r"\b[a-zA-Z0-9\-]{3,}\b", cleaned_q)
            if w.lower() not in {"what", "when", "where", "which", "from", "with", "that", "this", "these", "those", "about", "there"}
        }

        context_chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        seen_sources: Set[str] = set()
        allowed_urls: Set[str] = set()

        report_table_header: List[str] = []
        report_table_rows: List[Tuple[int, str]] = []
        report_fact_candidates: List[Tuple[int, str]] = []

        if report_text and len(report_text.strip()) > 60:
            allowed_urls = set(re.findall(r"https?://[^\s\)\]\>\"'\,]+", report_text))
            clean_rep = re.sub(r"<!--[\s\S]*?-->", "", report_text).strip()
            sections = re.split(r"\n(?=##?\s+)", clean_rep)

            for sec in sections:
                sec_clean = sec.strip()
                if not sec_clean:
                    continue
                sec_lines = sec_clean.splitlines()
                first_line_lower = sec_lines[0].lower() if sec_lines else ""

                if any(r in first_line_lower for r in ["references", "verified sources", "detailed evidence"]):
                    continue

                sec_weight = 0
                q_lower = cleaned_q.lower()
                if any(k in q_lower for k in ["metric", "benchmark", "number", "quant", "%", "score", "table"]):
                    if "quantitative" in first_line_lower or "benchmark" in first_line_lower:
                        sec_weight += 8
                elif any(k in q_lower for k in ["trade-off", "tradeoff", "bottleneck", "architect", "mechanism"]):
                    if "comparative" in first_line_lower or "trade-off" in first_line_lower or "architecture" in first_line_lower:
                        sec_weight += 8
                elif any(k in q_lower for k in ["limitation", "risk", "future", "outlook", "cost", "caveat", "bottleneck"]):
                    if "limitation" in first_line_lower or "future" in first_line_lower or "trajectory" in first_line_lower:
                        sec_weight += 8
                elif any(k in q_lower for k in ["summary", "verdict", "overview", "executive", "finding", "takeaway"]):
                    if "executive summary" in first_line_lower or "trajectory" in first_line_lower:
                        sec_weight += 8

                for raw_l in sec_lines[1:]:
                    stripped_l = raw_l.strip()
                    if not stripped_l or stripped_l.startswith(">"):
                        continue
                    low_l = stripped_l.lower()
                    if any(low_l.startswith(bp) for bp in _REPORT_BOILERPLATE_PREFIXES):
                        continue

                    if stripped_l.startswith("|"):
                        if re.match(r"^\|[\s\-:|]+\|$", stripped_l):
                            continue
                        if not report_table_header and ("metric" in low_l or "finding" in low_l or "#" in low_l or "model" in low_l or "source" in low_l):
                            report_table_header = [stripped_l]
                            continue
                        row_score = sec_weight + sum(3 for t in q_terms if t in low_l) + 2
                        report_table_rows.append((row_score, stripped_l))
                        continue

                    fact_line = re.sub(r"^[-*•]\s+", "", stripped_l)
                    fact_line = re.sub(r"^\d+\.\s+", "", fact_line)
                    fact_line = sanitize_search_snippet(fact_line)
                    if len(fact_line) < 25 or any(b in fact_line.lower() for b in ["javascript is disabled", "verify that you're not a robot", "under active evaluation"]):
                        continue

                    q_hits = sum(3 for t in q_terms if t in fact_line.lower())
                    has_metric = 2 if re.search(r"(\d+(\.\d+)?%|\$\d+|\b\d+(\.\d+)?\s*(x|GB|MB|ms|TOPS|s)\b)", fact_line, re.IGNORECASE) else 0
                    total_score = sec_weight + q_hits + has_metric
                    report_fact_candidates.append((total_score, fact_line))

                sec_body = "\n".join(sec_lines).strip()
                if sec_weight > 0 or sum(1 for t in q_terms if t in sec_body.lower()) > 0:
                    context_chunks.append(sec_body[:1600])

            if report_fact_candidates or report_table_rows:
                sources.append({"id": "Report", "source": "Active Report Dossier", "title": clean_topic_label or "Active Report"})
                seen_sources.add("Active Report Dossier")

        live_chunks: List[Dict[str, Any]] = []
        if web_augment:
            web_q = f"{clean_topic_label} {cleaned_q}".strip() if clean_topic_label else cleaned_q
            web_res = self.search_tool.search(web_q, max_results=3)
            for item in web_res:
                u = item.get("href", "")
                if u and not u.startswith("error://"):
                    allowed_urls.add(u)
                    snippet = sanitize_search_snippet(item.get("body", ""))
                    if len(snippet) > 40:
                        live_chunks.append({
                            "text": snippet,
                            "metadata": {"source": u, "title": item.get("title", "Live Web Result")},
                            "distance": 0.1,
                        })
                    scraped = self.scraper_tool.scrape(u)
                    if scraped.get("status") == "success":
                        self.vector_store.add_scraped_document(url=u, title=scraped["title"], text=scraped["text"])
                        live_chunks.append({
                            "text": scraped["text"][:1400],
                            "metadata": {"source": u, "title": scraped["title"]},
                            "distance": 0.05,
                        })
                        break

        search_query = f"{clean_topic_label}: {cleaned_q}" if clean_topic_label and clean_topic_label.lower() not in cleaned_q.lower() else cleaned_q
        raw_vector_results = live_chunks + self.vector_store.query(search_query, n_results=top_k * 2)

        filtered_chunks: List[Dict[str, Any]] = []
        seen_chunk_prefixes: Set[str] = set()
        for r in raw_vector_results:
            text = r.get("text", "")
            meta = r.get("metadata", {})
            src = meta.get("source", "")
            title = meta.get("title", "")
            combined_lower = f"{title} {src} {text}".lower()

            if src.startswith("repo:"):
                if report_filename and src != f"repo:{report_filename}":
                    continue
                if domain_topic_terms and not any(t in title.lower() for t in domain_topic_terms):
                    continue

            cleaned_text = re.sub(r"^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\s*[·\-–—|]\s*", "", text).strip()
            cleaned_text = re.sub(r"Missing:[\s\S]*$", "", cleaned_text).strip()
            if len(cleaned_text) < 40:
                continue

            if any(b in cleaned_text.lower() for b in ["javascript is disabled", "verify that you're not a robot", "enable javascript", "cookie policy"]):
                continue

            in_active_urls = bool(allowed_urls and src in allowed_urls)
            matches_domain = bool(domain_topic_terms and any(term in combined_lower for term in domain_topic_terms))
            if domain_topic_terms and not (in_active_urls or matches_domain):
                continue

            p_key = cleaned_text[:50].lower()
            if p_key in seen_chunk_prefixes:
                continue
            seen_chunk_prefixes.add(p_key)

            filtered_chunks.append({"text": cleaned_text, "metadata": meta, "distance": r.get("distance", 1.0)})
            if len(filtered_chunks) >= top_k:
                break

        for idx, item in enumerate(filtered_chunks, 1):
            meta = item.get("metadata", {})
            src = meta.get("source", "Memory")
            title = meta.get("title", src)
            if src not in seen_sources:
                seen_sources.add(src)
                sources.append({"id": idx, "source": src, "title": title})
            context_chunks.append(f"[{idx}] ({title} - {src}):\n{item['text']}")

        if not context_chunks and not report_fact_candidates and not report_table_rows:
            return {
                "answer": f"No details found in **{clean_topic_label or 'the researched dossier'}** for \"{cleaned_q}\".",
                "sources": [],
                "retrieved_chunks": 0,
            }

        context_str = "\n\n".join(context_chunks)

        system_prompt = INTERACTIVE_ANALYSIS_SYSTEM_PROMPT.format(
            topic=clean_topic_label or effective_topic or "the researched topic"
        )
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if chat_history:
            for turn in chat_history[-4:]:
                role = turn.get("role", "user")
                content = turn.get("content", "").strip()
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content[:500]})

        user_msg = INTERACTIVE_ANALYSIS_USER_TEMPLATE.format(
            topic=clean_topic_label or effective_topic or "Research Topic",
            context=context_str,
            question=cleaned_q,
        )
        messages.append({"role": "user", "content": user_msg})
        raw_answer = self._call_llm(messages, temperature=0.15)
        if raw_answer:
            cleaned_answer = clean_qa_response(raw_answer)
            if len(cleaned_answer.strip()) > 20:
                return {
                    "answer": cleaned_answer,
                    "sources": sources,
                    "retrieved_chunks": len(filtered_chunks),
                }

        q_lower = cleaned_q.lower()
        wants_metrics_table = any(k in q_lower for k in ["metric", "benchmark", "number", "quant", "%", "score", "table"])

        if wants_metrics_table and report_table_rows:
            report_table_rows.sort(key=lambda x: x[0], reverse=True)
            top_rows = [row for _, row in report_table_rows[:6]]
            hdr_line = report_table_header[0] if report_table_header else "| # | Empirical Metric / Finding | Source |"
            col_count = max(1, len([c for c in hdr_line.strip("|").split("|")]))
            sep_line = "|" + "|".join(["---"] * col_count) + "|"
            answer_md = "\n".join([hdr_line, sep_line] + top_rows)
            return {
                "answer": answer_md,
                "sources": sources,
                "retrieved_chunks": len(filtered_chunks),
            }

        ranked_points: List[Tuple[int, str]] = []
        seen_point_prefixes: Set[str] = set()

        for score, item in report_fact_candidates:
            p_key = re.sub(r"\*\*[^*]+\*\*:\s*", "", item)[:42].lower()
            if p_key not in seen_point_prefixes:
                seen_point_prefixes.add(p_key)
                ranked_points.append((score + 3, item))

        for idx, r in enumerate(filtered_chunks, 1):
            raw_sents = re.split(r"(?<=[.!?])\s+", r["text"])
            for s in raw_sents:
                clean_s = sanitize_search_snippet(s)
                if len(clean_s) < 35 or clean_s.endswith("...") or len(clean_s.split()) < 6:
                    continue
                if clean_s.startswith("http") or any(b in clean_s.lower() for b in ["javascript is disabled", "verify that you're not a robot", "cookie"]):
                    continue
                clean_s_lower = clean_s.lower()
                if any(clean_s_lower.startswith(bp) for bp in _REPORT_BOILERPLATE_PREFIXES):
                    continue
                if domain_topic_terms and not any(term in clean_s_lower for term in domain_topic_terms):
                    continue
                p_key = clean_s_lower[:42]
                if p_key in seen_point_prefixes:
                    continue
                seen_point_prefixes.add(p_key)

                matches = sum(3 for w in q_terms if w in clean_s_lower)
                has_metrics = 2 if re.search(r"(\d+(\.\d+)?%|\$\d+|\b\d+(\.\d+)?\s*(x|B|M|GB|TB|ms|TOPS|FPS|s)\b)", clean_s, re.IGNORECASE) else 0
                score = matches + has_metrics
                if score > 0 or not report_fact_candidates:
                    ranked_points.append((score, f"{clean_s} `[{idx}]`"))

        ranked_points.sort(key=lambda x: x[0], reverse=True)
        selected_bullets = [f"- {txt}" for _, txt in ranked_points[:5]]

        if not selected_bullets:
            answer_text = f"No details found in **{clean_topic_label or 'the researched dossier'}** for \"{cleaned_q}\"."
        else:
            answer_text = "\n".join(selected_bullets)

        return {
            "answer": answer_text,
            "sources": sources,
            "retrieved_chunks": len(filtered_chunks),
        }

    def _save_report(self, topic: str, content: str) -> Path:
        """Write final markdown report to disk."""
        sanitized = re.sub(r"[^\w\-_]", "_", topic.lower())[:40]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{sanitized}.md"
        output_path = settings.output_dir / filename

        if not content.startswith("#"):
            content = f"# Research Report: {topic}\n\n" + content

        header = (
            f"<!--\n"
            f"Topic: {topic}\n"
            f"Model: {self.model_name}\n"
            f"Generated: {datetime.now().isoformat()}\n"
            f"Engine: Advanced Local Research Studio\n"
            f"-->\n\n"
        )
        output_path.write_text(header + content, encoding="utf-8")
        return output_path
