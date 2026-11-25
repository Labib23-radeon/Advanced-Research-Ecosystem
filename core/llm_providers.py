"""Multi-provider LLM configuration, OpenAI-compatible client adapter, and LAN utilities."""
import json
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config import settings
from core.text_cleaner import clean_llm_output

logger = logging.getLogger(__name__)

_SETTINGS_LOCK = threading.Lock()

# Popular OpenAI-compatible presets shown in the UI Settings modal
PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "ollama": {
        "label": "Local Ollama (Private & Free)",
        "base_url": "http://127.0.0.1:11434",
        "default_model": "llama3.2:3b",
    },
    "groq": {
        "label": "Groq Cloud (Fast OpenAI-Compatible)",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "gemini": {
        "label": "Google Gemini (OpenAI-Compatible)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "label": "OpenRouter (Free / Multi-Model)",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "lmstudio": {
        "label": "LM Studio Local Server",
        "base_url": "http://127.0.0.1:1234/v1",
        "default_model": "local-model",
    },
    "custom": {
        "label": "Custom OpenAI-Compatible Endpoint",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
}


def _default_user_settings() -> Dict[str, Any]:
    return {
        "provider_mode": "auto",  # auto | ollama | openai_compatible | extractive
        "ollama_host": settings.ollama_host,
        "ollama_model": settings.ollama_model,
        "openai_preset": "groq",
        "openai_base_url": "https://api.groq.com/openai/v1",
        "openai_model": "llama-3.3-70b-versatile",
        "openai_api_key": "",
        "default_depth": "deep",
        "default_style": "brief",
    }


def _settings_file_path() -> Path:
    return settings.data_dir / "user_settings.json"


def load_user_settings(mask_secret: bool = False) -> Dict[str, Any]:
    """Load persisted Studio provider settings cleanly."""
    cfg = _default_user_settings()
    path = _settings_file_path()
    with _SETTINGS_LOCK:
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.update(raw)
            except Exception as exc:
                logger.warning("Failed to read user_settings.json: %s", exc)

    if mask_secret:
        key = cfg.get("openai_api_key", "") or ""
        cfg["has_api_key"] = bool(key.strip())
        if len(key) > 8:
            cfg["openai_api_key_masked"] = f"{key[:4]}{'•' * 8}{key[-4:]}"
        elif key:
            cfg["openai_api_key_masked"] = "•" * len(key)
        else:
            cfg["openai_api_key_masked"] = ""
        cfg["openai_api_key"] = ""
    return cfg


def save_user_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update persistent Studio settings without accidentally erasing stored secrets."""
    current = load_user_settings(mask_secret=False)
    allowed_keys = {
        "provider_mode",
        "ollama_host",
        "ollama_model",
        "openai_preset",
        "openai_base_url",
        "openai_model",
        "default_depth",
        "default_style",
    }
    for k in allowed_keys:
        if k in updates and updates[k] is not None:
            val = str(updates[k]).strip()
            if val or k in ("openai_base_url", "openai_model"):
                current[k] = val

    if updates.get("clear_api_key"):
        current["openai_api_key"] = ""
    elif isinstance(updates.get("openai_api_key"), str) and updates["openai_api_key"].strip():
        raw_key = updates["openai_api_key"].strip()
        if "•" not in raw_key:
            current["openai_api_key"] = raw_key

    path = _settings_file_path()
    with _SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    return load_user_settings(mask_secret=True)


def check_openai_compatible_health(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """Check if an OpenAI-compatible endpoint is configured and reachable."""
    cfg = load_user_settings(mask_secret=False)
    url = (base_url or cfg.get("openai_base_url") or "").strip().rstrip("/")
    key = (api_key if api_key is not None else cfg.get("openai_api_key", "")).strip()
    mdl = (model_name or cfg.get("openai_model") or "").strip()

    if not url:
        return False, "No API base URL configured"
    is_local = any(h in url.lower() for h in ("127.0.0.1", "localhost", "0.0.0.0"))
    if not key and not is_local:
        return False, "No API key configured for cloud endpoint"

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        t0 = time.time()
        resp = requests.get(f"{url}/models", headers=headers, timeout=3.5)
        latency_ms = int((time.time() - t0) * 1000)
        if resp.status_code == 200:
            return True, f"Connected ({mdl or 'default'}, {latency_ms}ms)"
        if resp.status_code in (401, 403):
            return False, f"Authentication rejected (HTTP {resp.status_code})"
        return False, f"Endpoint returned HTTP {resp.status_code}"
    except Exception as exc:
        return False, f"Unreachable: {str(exc)[:80]}"


def call_openai_compatible(
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> str:
    """Invoke any OpenAI-compatible /v1/chat/completions endpoint and sanitize output."""
    cfg = load_user_settings(mask_secret=False)
    url = (base_url or cfg.get("openai_base_url") or "").strip().rstrip("/")
    key = (api_key if api_key is not None else cfg.get("openai_api_key", "")).strip()
    mdl = (model_name or cfg.get("openai_model") or "gpt-4o-mini").strip()

    if not url:
        raise ValueError("OpenAI-compatible base URL is empty")

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": temperature,
    }
    resp = requests.post(
        f"{url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=min(settings.request_timeout, 60.0),
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    raw_content = choices[0].get("message", {}).get("content", "") if choices else ""
    return clean_llm_output(raw_content)


def detect_lan_ip() -> str:
    """Detect best local LAN IPv4 address for accessing the Studio from other devices."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127."):
            return hostname_ip
    except Exception:
        pass
    return "127.0.0.1"
