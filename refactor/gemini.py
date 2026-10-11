"""Gemini-backed folder selection for Imagga image context."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

from refactor.config import ENV_FILE
from refactor.imagga import ImageContext

load_dotenv()
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Current Gemini API default. Users may set GEMINI_MODEL to override it.
DEFAULT_MODEL = "gemini-3.8-flash"


def _safe_folder_name(value: str) -> str:
    """Return one relative directory name, never a path supplied by the model."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"\s+", "_", value).strip("_-")
    return value or "uncategorized"


class GeminiFolderClassifier:
    """Ask Gemini to select consistent folders from Imagga tags and captions."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        if not self.api_key:
            raise EnvironmentError(
                "Gemini credentials not found. Set GEMINI_API_KEY in ~/.refactor/.env."
            )

    def choose_folders(
        self, contexts: list[ImageContext], category_root: Path
    ) -> list[ImageContext]:
        if not contexts:
            return contexts

        existing = sorted(
            entry.name for entry in category_root.iterdir() if entry.is_dir()
        ) if category_root.exists() else []
        images = [
            {"id": index, "filename": Path(ctx.file_path).name,
             "tags": ctx.tags, "caption": ctx.caption}
            for index, ctx in enumerate(contexts)
        ]
        prompt = (
            "Choose exactly one concise, lowercase category folder for every image. "
            "Prefer an existing category when it accurately fits; otherwise create a "
            "new, broad and reusable category. Folder names must be a single relative "
            "directory name (letters, numbers, spaces, underscores, or hyphens only). "
            "Do not use filenames, paths, or explanations. Return JSON only in this "
            "shape: {\"folders\":[{\"id\":0,\"folder\":\"example\"}]}.\n\n"
            f"Existing categories: {json.dumps(existing)}\n"
            f"Images and Imagga semantic context: {json.dumps(images, ensure_ascii=False)}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        response = requests.post(
            url, headers={"x-goog-api-key": self.api_key}, json=payload, timeout=60
        )
        if not response.ok:
            raise requests.HTTPError(
                f"Gemini folder selection returned {response.status_code}: {response.text}",
                response=response,
            )

        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            choices = json.loads(text)["folders"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Gemini returned an invalid folder-selection response") from exc

        folders = {
            choice.get("id"): _safe_folder_name(str(choice.get("folder", "")))
            for choice in choices if isinstance(choice, dict) and isinstance(choice.get("id"), int)
        }
        missing = [str(index) for index in range(len(contexts)) if index not in folders]
        if missing:
            raise ValueError("Gemini did not choose a folder for image id(s): " + ", ".join(missing))

        for index, context in enumerate(contexts):
            context.primary_folder = folders[index]
        return contexts
