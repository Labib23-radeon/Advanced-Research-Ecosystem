"""Webpage content scraper using Trafilatura, BeautifulSoup, SSRF guard, and optional SQLite cache."""
import ipaddress
import logging
import re
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None
    HAS_TRAFILATURA = False

from bs4 import BeautifulSoup

from core.cache_manager import get_cache_manager
from core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_SCRAPE_CACHE: Dict[str, Dict[str, str]] = {}


def is_safe_public_url(url: str) -> bool:
    """Validate HTTP(S) URL and reject private/loopback/link-local hosts to guard against SSRF."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        host = (parsed.hostname or "").strip().lower()
        if not host or host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal")):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


class WebScraperTool:
    """Clean webpage text extractor using Trafilatura, BS4 fallback, and persistent SQLite caching."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_length: Optional[int] = None,
        persist_cache: bool = False,
    ) -> None:
        self.timeout = timeout or settings.scrape_timeout
        self.max_length = max_length or settings.max_content_length
        self.persist_cache = persist_cache

    def scrape(self, url: str) -> Dict[str, str]:
        """Fetch and extract clean readable text from a URL."""
        cleaned_url = url.strip()
        if not (cleaned_url.startswith("http://") or cleaned_url.startswith("https://")):
            return {
                "url": cleaned_url,
                "title": "Invalid URL",
                "text": f"Error: Invalid URL scheme for '{cleaned_url}'. Must start with http:// or https://",
                "status": "error",
            }

        if not is_safe_public_url(cleaned_url):
            return {
                "url": cleaned_url,
                "title": "Blocked Private URL",
                "text": f"Blocked access to private or unsafe target URL: {cleaned_url}",
                "status": "error",
            }

        # Rewrite arXiv PDF links to abstract page for clean HTML metadata + abstract extraction
        arxiv_pdf_match = re.match(r"^(https?://arxiv\.org)/pdf/([0-9]+\.[0-9]+v?\d*)(?:\.pdf)?$", cleaned_url, re.IGNORECASE)
        if arxiv_pdf_match:
            cleaned_url = f"{arxiv_pdf_match.group(1)}/abs/{arxiv_pdf_match.group(2)}"

        if cleaned_url in _SCRAPE_CACHE:
            return _SCRAPE_CACHE[cleaned_url]

        if self.persist_cache:
            disk_cached = get_cache_manager().get_scrape(cleaned_url)
            if disk_cached:
                _SCRAPE_CACHE[cleaned_url] = disk_cached
                return disk_cached

        try:
            effective_timeout = min(self.timeout, 4.0)
            response = requests.get(
                cleaned_url,
                headers=DEFAULT_HEADERS,
                timeout=effective_timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            headers = getattr(response, "headers", None)
            raw_ct = ""
            if headers is not None and hasattr(headers, "get"):
                try:
                    val = headers.get("Content-Type", "")
                    if isinstance(val, str):
                        raw_ct = val.lower()
                except Exception:
                    raw_ct = ""

            if raw_ct and not any(t in raw_ct for t in ["text/", "xml", "json", "html"]):
                res = {
                    "url": cleaned_url,
                    "title": "Non-Text Media Skipped",
                    "text": f"Skipped non-HTML media content type: {raw_ct}",
                    "status": "skipped",
                }
                _SCRAPE_CACHE[cleaned_url] = res
                return res

            resp_enc = getattr(response, "encoding", None)
            if isinstance(resp_enc, str) and resp_enc.lower() == "iso-8859-1":
                apparent = getattr(response, "apparent_encoding", None)
                response.encoding = apparent if isinstance(apparent, str) and apparent else "utf-8"

            html_content = getattr(response, "text", "") or ""

            page_title = "Webpage Content"
            soup = None
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                if soup.title and soup.title.string:
                    raw_title = " ".join(soup.title.string.split()).strip()
                    if raw_title:
                        page_title = raw_title[:160]
            except Exception:
                pass

            extracted_text = None
            if HAS_TRAFILATURA and trafilatura is not None:
                try:
                    extracted_text = trafilatura.extract(
                        html_content,
                        include_comments=False,
                        include_tables=True,
                        include_links=False,
                        output_format="txt",
                    )
                except Exception as exc:
                    logger.debug("Trafilatura extract error: %s", exc)

            if not extracted_text:
                if soup is None:
                    soup = BeautifulSoup(html_content, "html.parser")
                for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    element.extract()
                paragraphs = [p.get_text().strip() for p in soup.find_all(["p", "h1", "h2", "h3", "li", "blockquote"])]
                extracted_text = "\n\n".join([p for p in paragraphs if len(p) > 20])

            if not extracted_text:
                return {
                    "url": cleaned_url,
                    "title": page_title,
                    "text": f"Could not extract meaningful main body text from {cleaned_url} (page might require JavaScript).",
                    "status": "empty",
                }

            extracted_text = re.sub(r"\n{3,}", "\n\n", extracted_text).strip()

            if len(extracted_text) > self.max_length:
                truncated_text = extracted_text[: self.max_length]
                last_break = max(truncated_text.rfind("."), truncated_text.rfind("\n"))
                if last_break > int(self.max_length * 0.7):
                    truncated_text = truncated_text[: last_break + 1]
                extracted_text = truncated_text + f"\n\n[... Content truncated for length ({len(extracted_text)} characters total) ...]"

            result = {
                "url": cleaned_url,
                "title": page_title,
                "text": extracted_text,
                "status": "success",
            }
            _SCRAPE_CACHE[cleaned_url] = result
            if self.persist_cache:
                get_cache_manager().set_scrape(result)
            return result

        except requests.Timeout:
            logger.warning("Scraping timeout for URL: %s", cleaned_url)
            return {
                "url": cleaned_url,
                "title": "Timeout Error",
                "text": f"Scraping timed out after {self.timeout} seconds for URL: {cleaned_url}",
                "status": "timeout",
            }
        except Exception as exc:
            logger.warning("Scraping error for URL %s: %s", cleaned_url, exc)
            return {
                "url": cleaned_url,
                "title": "Scrape Error",
                "text": f"Failed to scrape {cleaned_url}: {str(exc)}",
                "status": "error",
            }

    def scrape_formatted(self, url: str) -> str:
        """Fetch URL and return a formatted string for the agent context."""
        result = self.scrape(url)
        if result["status"] != "success":
            return f"[Scrape Notice for {url}]: {result['text']}"

        return (
            f"### Scraped Content from: {result['url']}\n"
            f"**Title**: {result['title']}\n\n"
            f"{result['text']}"
        )


def scrape_page(url: str, max_length: Optional[int] = None) -> str:
    """Functional wrapper to scrape and extract text from a webpage."""
    scraper = WebScraperTool(max_length=max_length)
    return scraper.scrape_formatted(url)
