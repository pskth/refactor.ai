"""
refactor/image_scanner.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Scans a directory for image files only.
Extends the base scanner with image-extension filtering.
"""

from pathlib import Path

from refactor.ignore import should_ignore

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}


def scan_images(path: str, ignore_patterns: list[str]) -> list[Path]:
    """
    Recursively scan *path* and return all image files.

    Files matching any pattern in *ignore_patterns* are skipped.
    """
    images: list[Path] = []

    for item in Path(path).rglob("*"):
        if item.is_dir():
            continue

        if should_ignore(item.name, ignore_patterns):
            continue

        if item.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(item)

    return images
