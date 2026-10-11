"""Document discovery, text extraction, and Gemini categorization."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from refactor.gemini import GeminiFolderClassifier
from refactor.ignore import should_ignore

TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
TEXT_CATEGORY_MANIFEST = ".refactor_text_categories.json"
MAX_TEXT_CHARS = 60_000
MAX_PDF_BYTES = 50 * 1024 * 1024


@dataclass
class TextContext:
    file_path: str
    primary_folder: str


def managed_text_dirs(output_dir: Path) -> set[Path]:
    manifest = output_dir / TEXT_CATEGORY_MANIFEST
    if not manifest.exists():
        return set()
    try:
        folders = json.loads(manifest.read_text(encoding="utf-8")).get("folders", [])
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        (output_dir / folder).resolve() for folder in folders
        if isinstance(folder, str) and (output_dir / folder).is_dir()
    }


def save_managed_text_dirs(output_dir: Path, folders: set[str]) -> None:
    (output_dir / TEXT_CATEGORY_MANIFEST).write_text(
        json.dumps({"folders": sorted(folders)}, indent=2) + "\n", encoding="utf-8"
    )


def scan_documents(path: str, patterns: list[str], excluded_dirs: set[Path]) -> list[Path]:
    documents: list[Path] = []
    excluded_dirs = {directory.resolve() for directory in excluded_dirs}
    for item in Path(path).rglob("*"):
        if item.is_dir() or item.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(directory in item.resolve().parents for directory in excluded_dirs):
            continue
        if not should_ignore(item.name, patterns):
            documents.append(item)
    return documents


def extract_text(file_path: Path) -> str:
    """Extract text from supported non-PDF document formats."""
    if file_path.suffix.lower() in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
    if file_path.suffix.lower() == ".docx":
        with zipfile.ZipFile(file_path) as document:
            root = ElementTree.fromstring(document.read("word/document.xml"))
        text = " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        return text[:MAX_TEXT_CHARS]
    return ""


def classify_documents(
    documents: list[Path], category_root: Path
) -> tuple[list[TextContext], list[tuple[Path, Exception]]]:
    classifier = GeminiFolderClassifier()
    results: list[TextContext] = []
    failures: list[tuple[Path, Exception]] = []
    for document in documents:
        try:
            is_pdf = document.suffix.lower() == ".pdf"
            if is_pdf and document.stat().st_size > MAX_PDF_BYTES:
                raise ValueError("PDF exceeds Gemini's 50 MB input limit")
            folder = classifier.choose_document_folder(
                document, extract_text(document), category_root, is_pdf=is_pdf
            )
            results.append(TextContext(str(document.resolve()), folder))
        except Exception as exc:
            failures.append((document, exc))
    return results, failures
