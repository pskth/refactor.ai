from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".refactor"
CONFIG_FILE = CONFIG_DIR / "config.json"
ENV_FILE = CONFIG_DIR / ".env"


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "backend": "unconfigured",
        "setup_skipped": False,
        "hosted": {
            "provider": "imagga_gemini",
            "imagga_api_key_env": "IMAGGA_API_KEY",
            "imagga_api_secret_env": "IMAGGA_API_SECRET",
            "gemini_api_key_env": "GEMINI_API_KEY",
        },
        "local": {
            "runtime": "ollama",
            "recommended_model": "",
            "status": "stub",
        },
    }


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return default_config()

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    merged = default_config()
    merged.update(payload)
    return merged


def save_config(config: dict[str, Any]) -> None:
    _ensure_config_dir()

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def save_env_vars(values: dict[str, str]) -> None:
    _ensure_config_dir()

    existing: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()

    existing.update(values)

    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
