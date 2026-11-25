"""Persistent user metadata for saved dossiers (favorites/stars, custom titles, notes)."""
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import settings

_META_LOCK = threading.Lock()


def _meta_path() -> Path:
    return settings.data_dir / "report_meta.json"


def load_all_report_meta() -> Dict[str, Dict[str, Any]]:
    """Return mapping of filename -> metadata dict."""
    path = _meta_path()
    with _META_LOCK:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _save_all_meta(data: Dict[str, Dict[str, Any]]) -> None:
    path = _meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_report_starred(filename: str, starred: Optional[bool] = None) -> bool:
    """Toggle or explicitly set star flag for a saved dossier."""
    with _META_LOCK:
        data = {}
        path = _meta_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        entry = data.get(filename, {})
        new_val = (not bool(entry.get("starred", False))) if starred is None else bool(starred)
        entry["starred"] = new_val
        data[filename] = entry
        _save_all_meta(data)
        return new_val


def rename_report_metadata(old_filename: str, new_filename: str, custom_title: Optional[str] = None) -> None:
    """Carry over star/title metadata when a dossier is renamed."""
    with _META_LOCK:
        path = _meta_path()
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        entry = data.pop(old_filename, {})
        if custom_title:
            entry["custom_title"] = custom_title.strip()
        if entry:
            data[new_filename] = entry
        _save_all_meta(data)
