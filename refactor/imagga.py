"""
refactor/imagga.py
~~~~~~~~~~~~~~~~~~
Thin wrapper around the Imagga v3 REST API.

Reads IMAGGA_API_KEY and IMAGGA_API_SECRET from the environment (or .env file).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from the current working directory (or any parent)
load_dotenv()

BASE_URL = "https://api.imagga.com/v2"
DEFAULT_MIN_CONFIDENCE = 40.0
DEFAULT_TAG_LIMIT = 10


@dataclass
class ImageContext:
    """Structured result for a single image analysis."""

    file_path: str
    upload_id: str
    tags: list[str] = field(default_factory=list)
    confidences: dict[str, float] = field(default_factory=dict)
    caption: str = ""
    primary_folder: str = "uncategorized"


def _sanitize_folder_name(name: str) -> str:
    """Convert a tag string into a safe directory name."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)   # strip special chars
    name = re.sub(r"[\s]+", "_", name)      # spaces -> underscores
    name = name.strip("_-")
    return name or "uncategorized"


class ImaggaClient:
    """Imagga v3 REST API client."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self.api_key = api_key or os.environ.get("IMAGGA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("IMAGGA_API_SECRET", "")

        if not self.api_key or not self.api_secret:
            raise EnvironmentError(
                "Imagga credentials not found. "
                "Set IMAGGA_API_KEY and IMAGGA_API_SECRET in your .env file."
            )

        self.auth = (self.api_key, self.api_secret)
        self.min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_image(self, file_path: Path) -> str:
        """Upload a local image to Imagga and return the upload_id."""
        url = f"{BASE_URL}/uploads"

        with open(file_path, "rb") as image_file:
            response = requests.post(
                url,
                auth=self.auth,
                files={"image": (file_path.name, image_file)},
                timeout=60,
            )

        response.raise_for_status()
        data = response.json()

        upload_id = data.get("result", {}).get("upload_id")
        if not upload_id:
            raise ValueError(f"Imagga upload failed for {file_path}: {data}")

        return upload_id

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _fetch_tags(self, params: dict) -> dict:
        """Internal: call /tags endpoint and return parsed JSON."""
        url = f"{BASE_URL}/tags"
        params = {**params, "model": "pro", "include_caption": "true"}

        response = requests.get(url, auth=self.auth, params=params, timeout=60)

        if not response.ok:
            try:
                msg = response.json().get("status", {}).get("text", response.text)
            except Exception:
                msg = response.text
            raise requests.HTTPError(
                f"Imagga /tags returned {response.status_code}: {msg}",
                response=response,
            )

        return response.json()


    def _parse_response(self, file_path: str, upload_id: str, data: dict) -> ImageContext:
        """Parse a /tags API response into an ImageContext."""
        result = data.get("result", {})

        # Tags
        raw_tags = result.get("tags", [])
        filtered = [
            t for t in raw_tags
            if t.get("confidence", 0) >= self.min_confidence
        ]
        filtered.sort(key=lambda t: t["confidence"], reverse=True)
        filtered = filtered[:DEFAULT_TAG_LIMIT]

        tags = [t["tag"]["en"] for t in filtered]
        confidences = {t["tag"]["en"]: round(t["confidence"], 2) for t in filtered}

        # Caption
        captions = result.get("captions", [])
        caption = captions[0].get("text", "") if captions else ""

        # Primary folder from top tag
        primary_folder = _sanitize_folder_name(tags[0]) if tags else "uncategorized"

        return ImageContext(
            file_path=file_path,
            upload_id=upload_id,
            tags=tags,
            confidences=confidences,
            caption=caption,
            primary_folder=primary_folder,
        )

    def get_tags(self, file_path: Path) -> ImageContext:
        """Upload a local image and return its AI-generated context."""
        upload_id = self.upload_image(file_path)
        data = self._fetch_tags({"image_upload_id": upload_id})
        return self._parse_response(str(file_path.resolve()), upload_id, data)

    def get_tags_by_url(self, image_url: str) -> ImageContext:
        """Fetch tags for a publicly accessible image URL (no upload needed)."""
        data = self._fetch_tags({"image_url": image_url})
        return self._parse_response(image_url, "", data)
