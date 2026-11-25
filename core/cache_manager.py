"""Thread-safe SQLite persistence for search cache, scrape cache, and research job history."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings


class StudioCacheManager:
    """SQLite WAL-backed cache and job history store with TTL support."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or (settings.data_dir / "studio_cache.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS search_cache (
                        cache_key TEXT PRIMARY KEY,
                        query TEXT NOT NULL,
                        results_json TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scrape_cache (
                        url TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        text_content TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_jobs (
                        job_id TEXT PRIMARY KEY,
                        topic TEXT NOT NULL,
                        status TEXT NOT NULL,
                        depth TEXT,
                        source_scope TEXT,
                        model_name TEXT,
                        step_count INTEGER DEFAULT 0,
                        filename TEXT,
                        error_msg TEXT,
                        started_at REAL NOT NULL,
                        finished_at REAL
                    )
                    """
                )
                conn.commit()

    # ------------------------------------------
    # Search Cache
    # ------------------------------------------
    def get_search(self, cache_key: str, ttl_seconds: int = 43200) -> Optional[List[Dict[str, str]]]:
        """Return cached search results if present and within TTL (default 12h)."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT results_json, created_at FROM search_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if not row:
                    return None
                if now - float(row["created_at"]) > ttl_seconds:
                    conn.execute("DELETE FROM search_cache WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None
                try:
                    data = json.loads(row["results_json"])
                    return data if isinstance(data, list) else None
                except Exception:
                    return None

    def set_search(self, cache_key: str, query: str, results: List[Dict[str, str]]) -> None:
        """Persist non-empty search results to SQLite cache."""
        if not results:
            return
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_cache (cache_key, query, results_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cache_key, query, json.dumps(results, ensure_ascii=False), time.time()),
                )
                conn.commit()

    # ------------------------------------------
    # Scrape Cache (also powers Source View Text offline/after restarts)
    # ------------------------------------------
    def get_scrape(self, url: str, ttl_seconds: int = 604800) -> Optional[Dict[str, str]]:
        """Return cached webpage extraction if within TTL (default 7 days)."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT url, title, text_content, status, created_at FROM scrape_cache WHERE url = ?",
                    (url,),
                ).fetchone()
                if not row:
                    return None
                if now - float(row["created_at"]) > ttl_seconds:
                    return None
                return {
                    "url": row["url"],
                    "title": row["title"],
                    "text": row["text_content"],
                    "status": row["status"],
                }

    def set_scrape(self, result: Dict[str, str]) -> None:
        """Persist successful scrape payload for reuse and offline source inspection."""
        url = (result.get("url") or "").strip()
        if not url or result.get("status") != "success":
            return
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO scrape_cache (url, title, text_content, status, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        url,
                        result.get("title", "Webpage Content"),
                        result.get("text", ""),
                        result.get("status", "success"),
                        time.time(),
                    ),
                )
                conn.commit()

    # ------------------------------------------
    # Research Job History & Recovery
    # ------------------------------------------
    def upsert_job(
        self,
        job_id: str,
        topic: str,
        status: str,
        depth: str = "deep",
        source_scope: str = "all",
        model_name: str = "",
        step_count: int = 0,
        filename: Optional[str] = None,
        error_msg: Optional[str] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> None:
        """Record or update an autonomous research execution job."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT started_at FROM research_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                actual_start = started_at or (float(existing["started_at"]) if existing else now)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO research_jobs
                    (job_id, topic, status, depth, source_scope, model_name, step_count, filename, error_msg, started_at, finished_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        topic,
                        status,
                        depth,
                        source_scope,
                        model_name,
                        step_count,
                        filename,
                        error_msg,
                        actual_start,
                        finished_at,
                    ),
                )
                conn.commit()

    def list_recent_jobs(self, limit: int = 15) -> List[Dict[str, Any]]:
        """List recent research jobs ordered by newest first."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM research_jobs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        """Return cache counts and database file size."""
        with self._lock:
            with self._connect() as conn:
                s_cnt = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
                p_cnt = conn.execute("SELECT COUNT(*) FROM scrape_cache").fetchone()[0]
                j_cnt = conn.execute("SELECT COUNT(*) FROM research_jobs").fetchone()[0]
        db_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "search_entries": int(s_cnt),
            "scraped_pages": int(p_cnt),
            "logged_jobs": int(j_cnt),
            "db_size_kb": round(db_bytes / 1024.0, 1),
        }

    def clear_caches(self) -> None:
        """Clear cached searches and scraped pages while preserving job history."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM search_cache")
                conn.execute("DELETE FROM scrape_cache")
                conn.commit()


# Lazy singleton accessor
_CACHE_SINGLETON: Optional[StudioCacheManager] = None
_CACHE_INIT_LOCK = threading.Lock()


def get_cache_manager() -> StudioCacheManager:
    """Return process-wide SQLite cache manager instance."""
    global _CACHE_SINGLETON
    if _CACHE_SINGLETON is None:
        with _CACHE_INIT_LOCK:
            if _CACHE_SINGLETON is None:
                _CACHE_SINGLETON = StudioCacheManager()
    return _CACHE_SINGLETON
