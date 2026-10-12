"""Persistent, source-validated plans for dry-run reuse."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Type


def _snapshot(files: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(file_path.resolve()),
            "size": file_path.stat().st_size,
            "mtime_ns": file_path.stat().st_mtime_ns,
        }
        for file_path in sorted(files)
    ]


def save_plan(
    output_path: Path,
    kind: str,
    source_dir: str,
    output_dir: str,
    files: list[Path],
    contexts: list[Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": kind,
        "source_dir": str(Path(source_dir).resolve()),
        "output_dir": str(Path(output_dir).resolve()),
        "snapshot": _snapshot(files),
        "items": [asdict(context) for context in contexts],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_valid_plan(
    input_path: Path,
    kind: str,
    source_dir: str,
    output_dir: str,
    files: list[Path],
    context_type: Type[Any],
) -> list[Any] | None:
    """Return cached contexts only if they exactly match the current source."""
    if not input_path.exists():
        return None
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("kind") != kind
        or payload.get("source_dir") != str(Path(source_dir).resolve())
        or payload.get("output_dir") != str(Path(output_dir).resolve())
        or payload.get("snapshot") != _snapshot(files)
    ):
        return None
    try:
        return [context_type(**item) for item in payload["items"]]
    except (KeyError, TypeError):
        return None
