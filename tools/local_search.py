"""Resilient multi-engine web search across DuckDuckGo, Wikipedia, arXiv, and Semantic Scholar."""
import logging
import re
import time
import warnings
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*renamed to.*")
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from core.cache_manager import get_cache_manager
from core.config import settings

logger = logging.getLogger(__name__)

# Module-level query cache to prevent redundant search hits
_SEARCH_CACHE: Dict[str, List[Dict[str, str]]] = {}

# Meta-words to filter when distilling core subjects for open encyclopedic & academic searches
_META_STOP_WORDS = {
    "verified", "benchmark", "benchmarks", "scores", "throughput", "accuracy",
    "empirical", "metrics", "overview", "architecture", "analysis", "state", "of",
    "the", "art", "known", "limitations", "engineering", "trade-offs", "tradeoffs",
    "and", "failure", "points", "mechanisms", "comparison", "vs", "versus"
}


def _extract_core_subject(query: str) -> str:
    """Extract the core technical subject from a prompt, stripping meta and punctuation terms."""
    clean = re.sub(r"https?://\S+", "", query)
    if ":" in clean:
        parts = clean.split(":")
        clean = parts[0].strip() if len(parts[0].strip()) > 8 else parts[1].strip()

    words = [
        w for w in re.findall(r"\b[A-Za-z0-9\-]+\b", clean)
        if w.lower() not in _META_STOP_WORDS and len(w) > 2
    ]
    if len(words) >= 2:
        return " ".join(words[:6])
    return clean.strip() or query.strip()


class DuckDuckGoSearchTool:
    """Resilient, multi-layer web search tool with persistent caching and open fallbacks."""

    def __init__(self, max_results: Optional[int] = None, persist_cache: bool = False) -> None:
        self.max_results = max_results or settings.max_search_results
        self.persist_cache = persist_cache

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, str]]:
        """Perform a resilient multi-source web search with persistent disk caching."""
        num_results = max_results or self.max_results
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        cache_key = f"{cleaned_query.lower()}::{num_results}"
        if cache_key in _SEARCH_CACHE:
            return _SEARCH_CACHE[cache_key]

        if self.persist_cache:
            cached = get_cache_manager().get_search(cache_key)
            if cached:
                _SEARCH_CACHE[cache_key] = cached
                return cached

        core_subject = _extract_core_subject(cleaned_query)

        # Tier 1: DuckDuckGo DDGS API with Progressive Simplification & Retry
        queries_to_try = [cleaned_query]
        if core_subject and core_subject.lower() != cleaned_query.lower():
            queries_to_try.append(core_subject)
        words = cleaned_query.split()
        if len(words) > 4:
            queries_to_try.append(" ".join(words[:4]))

        for q_try in queries_to_try:
            for attempt in range(2):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        with DDGS(timeout=5) as ddgs:
                            try:
                                results_gen = ddgs.text(
                                    query=q_try,
                                    max_results=num_results,
                                    safesearch="moderate",
                                )
                            except TypeError:
                                results_gen = ddgs.text(
                                    keywords=q_try,
                                    max_results=num_results,
                                    safesearch="moderate",
                                )

                            results: List[Dict[str, str]] = []
                            for item in results_gen:
                                title = item.get("title", "").strip()
                                href = item.get("href", item.get("link", "")).strip()
                                body = item.get("body", item.get("snippet", "")).strip()
                                if href and not href.startswith("error://"):
                                    results.append({
                                        "title": title or "Untitled",
                                        "href": href,
                                        "body": body or "No snippet available",
                                    })

                            if results:
                                _SEARCH_CACHE[cache_key] = results
                                if self.persist_cache:
                                    get_cache_manager().set_search(cache_key, cleaned_query, results)
                                return results
                    break
                except Exception as exc:
                    logger.debug("DuckDuckGo search attempt %d failed on '%s': %s", attempt + 1, q_try, exc)
                    if attempt == 0:
                        time.sleep(0.25)

        # Tier 2: Semantic Scholar Open Academic API Fallback
        acad_results = self._search_semantic_scholar_fallback(core_subject or cleaned_query, max_results=num_results)
        if acad_results:
            _SEARCH_CACHE[cache_key] = acad_results
            if self.persist_cache:
                get_cache_manager().set_search(cache_key, cleaned_query, acad_results)
            return acad_results

        # Tier 3: Wikipedia Open Knowledge API Fallback
        wiki_query = core_subject if len(core_subject) > 5 else cleaned_query
        wiki_results = self._search_wikipedia_fallback(wiki_query, max_results=num_results)
        if wiki_results:
            _SEARCH_CACHE[cache_key] = wiki_results
            if self.persist_cache:
                get_cache_manager().set_search(cache_key, cleaned_query, wiki_results)
            return wiki_results

        # Tier 4: arXiv Open Scientific Research API Fallback
        arxiv_results = self._search_arxiv_fallback(core_subject or cleaned_query, max_results=num_results)
        if arxiv_results:
            _SEARCH_CACHE[cache_key] = arxiv_results
            if self.persist_cache:
                get_cache_manager().set_search(cache_key, cleaned_query, arxiv_results)
            return arxiv_results

        return []

    def _search_semantic_scholar_fallback(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Open scientific paper search via Semantic Scholar Graph API."""
        try:
            resp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": max_results, "fields": "title,abstract,url,year,citationCount"},
                headers={"User-Agent": "AdvancedResearchStudio/3.0"},
                timeout=3.5,
            )
            if resp.status_code != 200:
                return []
            papers = resp.json().get("data") or []
            results: List[Dict[str, str]] = []
            for p in papers:
                url = (p.get("url") or "").strip()
                title = (p.get("title") or "").strip()
                if not url or not title:
                    continue
                year = p.get("year") or ""
                cites = p.get("citationCount") or 0
                abstract = (p.get("abstract") or "").strip()
                body = f"({year}, {cites} citations) {abstract[:260]}" if year else abstract[:280]
                results.append({
                    "title": f"{title} (Semantic Scholar)",
                    "href": url,
                    "body": body or "Peer-reviewed scientific reference.",
                })
            return results
        except Exception as exc:
            logger.debug("Semantic Scholar fallback error for '%s': %s", query, exc)
            return []

    def _search_wikipedia_fallback(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Reliable open encyclopedic search via Wikipedia API."""
        try:
            resp = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "utf8": 1,
                    "srlimit": max_results,
                },
                headers={"User-Agent": "AdvancedResearchStudio/3.0 (LocalResearch)"},
                timeout=4.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("query", {}).get("search", [])
                results: List[Dict[str, str]] = []
                for item in items:
                    title = item.get("title", "")
                    page_title = title.replace(" ", "_")
                    href = f"https://en.wikipedia.org/wiki/{page_title}"
                    raw_snippet = item.get("snippet", "")
                    clean_snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()
                    results.append({
                        "title": f"{title} (Wikipedia)",
                        "href": href,
                        "body": clean_snippet or "Open encyclopedic research reference.",
                    })
                return results
        except Exception as exc:
            logger.debug("Wikipedia fallback error for '%s': %s", query, exc)
        return []

    def _search_arxiv_fallback(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Reliable open scientific literature search via arXiv API."""
        try:
            clean_q = re.sub(r"[^\w\s\-]", "", query).strip()
            resp = requests.get(
                "http://export.arxiv.org/api/query",
                params={"search_query": f"all:{clean_q}", "start": 0, "max_results": max_results},
                timeout=4.5,
            )
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                results: List[Dict[str, str]] = []
                for entry in root.findall("atom:entry", ns):
                    title_elem = entry.find("atom:title", ns)
                    summary_elem = entry.find("atom:summary", ns)
                    id_elem = entry.find("atom:id", ns)
                    if title_elem is not None and id_elem is not None:
                        t_text = " ".join((title_elem.text or "").split())
                        s_text = " ".join((summary_elem.text or "").split())[:280] if summary_elem is not None else ""
                        link_url = (id_elem.text or "").strip()
                        if link_url:
                            results.append({
                                "title": f"{t_text} (arXiv)",
                                "href": link_url,
                                "body": s_text or "Open scientific paper pre-print.",
                            })
                return results
        except Exception as exc:
            logger.debug("arXiv fallback error for '%s': %s", query, exc)
        return []

    def format_results(self, results: List[Dict[str, str]], query: str) -> str:
        """Format a list of search result dicts into clean markdown for agent reasoning."""
        valid_results = [r for r in results if r.get("href") and not r.get("href", "").startswith("error://")]
        if not valid_results:
            return (
                f"### Web Search for: '{query}'\n"
                f"No direct external web matches found. Research proceeding with cross-source synthesis and local knowledge memory."
            )

        formatted_lines = [f"### Web Search Results for: '{query}'"]
        for idx, item in enumerate(valid_results, 1):
            formatted_lines.append(f"{idx}. [{item['title']}]({item['href']})\n   {item['body']}")
        return "\n\n".join(formatted_lines)

    def search_formatted(self, query: str, max_results: Optional[int] = None) -> str:
        """Perform search and immediately return formatted markdown output."""
        results = self.search(query, max_results=max_results)
        return self.format_results(results, query)


def web_search(query: str, max_results: int = 5) -> str:
    """Convenience functional wrapper for DuckDuckGoSearchTool."""
    tool = DuckDuckGoSearchTool()
    results = tool.search(query, max_results=max_results)
    return tool.format_results(results, query)
