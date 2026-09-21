"""
refactor/context_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Manages reading and writing the JSON context cache produced by get-image-context.

Default cache filename: .refactor_image_context.json
"""

from __future__ import annotations
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from refactor.imagga import ImageContext

DEFAULT_CACHE_FILE = ".refactor_image_context.json"


def save_context(
    results: list[ImageContext],
    source_dir: str,
    output_path: Path,
) -> None:
    """Serialise a list of ImageContext objects to a JSON cache file."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(Path(source_dir).resolve()),
        "images": [asdict(ctx) for ctx in results],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_context(input_path: Path) -> list[ImageContext]:
    """Load ImageContext objects from a JSON cache file."""
    if not input_path.exists():
        raise FileNotFoundError(
            f"Context cache not found: {input_path}\n"
            "Run 'refactor get-image-context <path>' first."
        )

    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return [ImageContext(**img) for img in payload.get("images", [])]
