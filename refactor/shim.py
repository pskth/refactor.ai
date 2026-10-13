from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from refactor.imagga import ImageContext, ImaggaClient
from refactor.gemini import GeminiFolderClassifier


def _safe_folder_name(value: str) -> str:
    value = value.strip().lower()
    safe = "".join(char for char in value if char.isalnum() or char in " -_")
    return "_".join(safe.split()).strip("_-") or "uncategorized"


class ImageClassifier(ABC):
    @abstractmethod
    def classify_image(self, file_path: Path) -> ImageContext:
        raise NotImplementedError


class HostedImageClassifier(ImageClassifier):
    def __init__(self, min_confidence: float = 40.0) -> None:
        self.client = ImaggaClient(min_confidence=min_confidence)

    def classify_image(self, file_path: Path) -> ImageContext:
        return self.client.get_tags(file_path)

    def choose_folders(
        self, contexts: list[ImageContext], category_root: Path
    ) -> list[ImageContext]:
        return GeminiFolderClassifier().choose_folders(contexts, category_root)


OLLAMA_URL = "http://127.0.0.1:11434"

# ``format: "json"`` ensures only syntactically valid JSON. A schema also
# constrains keys and array length, which is essential for small local models.
IMAGE_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
        },
        "folder": {"type": "string"},
    },
    "required": ["caption", "tags", "folder"],
    "additionalProperties": False,
}
FOLDER_SCHEMA = {
    "type": "object",
    "properties": {"folder": {"type": "string"}},
    "required": ["folder"],
    "additionalProperties": False,
}
FOLDER_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "folders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "folder": {"type": "string"}},
                "required": ["id", "folder"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["folders"],
    "additionalProperties": False,
}

FOLDER_NAMING_SYSTEM_PROMPT = (
    "You assign precise folder names for file organization. Return a short, specific "
    "semantic topic of one to three lowercase words, using underscores if needed. "
    "Use a meaningful qualifier when it distinguishes the subject, for example "
    "'gate_exam', 'password_reset', or 'research_papers'. Never copy, abbreviate, "
    "or derive the folder name from a filename, document title, path, person name, "
    "opaque identifier, date, or version number. Do not use generic names such as "
    "'information', 'documents', 'files', 'misc', or 'other'. Reuse a matching "
    "existing category exactly when one is provided."
)


def _parse_ollama_json(response: dict, description: str) -> dict:
    """Return one JSON object without exposing unbounded model output on errors."""
    if response.get("error"):
        raise RuntimeError(f"Ollama {description} request failed: {response['error']}")
    content = response.get("message", {}).get("content", "")
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        preview = str(content).replace("\n", " ")[:300]
        reason = response.get("done_reason", "unknown")
        raise RuntimeError(
            f"Ollama returned invalid {description} JSON "
            f"(done_reason={reason}, preview={preview!r})"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Ollama returned a non-object {description} response")
    return parsed


def _ollama_request(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{OLLAMA_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise EnvironmentError(
            "Cannot reach Ollama at http://127.0.0.1:11434. Start it with `ollama serve`."
        ) from exc


def ollama_server_available() -> bool:
    try:
        _ollama_request("/api/tags")
    except EnvironmentError:
        return False
    return True


def ollama_model_available(model_name: str) -> bool:
    return any(
        installed_name == model_name
        or installed_name == f"{model_name}:latest"
        for installed_name in ollama_installed_models()
    )


def ollama_installed_models() -> list[str]:
    """Return installed Ollama model tags in a stable order.

    The tags endpoint is the source of truth here rather than the ``ollama``
    executable output, which keeps setup consistent with the server Refactor
    will actually use for inference.
    """
    try:
        response = _ollama_request("/api/tags")
    except EnvironmentError:
        return []

    return sorted(
        {
            name
            for model in response.get("models", [])
            if isinstance(model, dict)
            and isinstance((name := model.get("name")), str)
            and name
        },
        key=str.lower,
    )


class OllamaImageClassifier(ImageClassifier):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def classify_image(self, file_path: Path) -> ImageContext:
        try:
            encoded_image = base64.b64encode(file_path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise RuntimeError(f"Could not read image: {file_path}") from exc

        prompt = (
            "Analyze this image for file organization. Return one JSON object matching "
            "the supplied schema: a short caption, 1 to 5 distinct concise lowercase "
            "tags, and one broad reusable folder name. Do not repeat tags or add keys."
        )
        response = _ollama_request(
            "/api/chat",
            {
                "model": self.model_name,
                "stream": False,
                "format": IMAGE_CONTEXT_SCHEMA,
                "options": {"temperature": 0, "num_predict": 160},
                "think": False,
                "messages": [{"role": "user", "content": prompt, "images": [encoded_image]}],
            },
        )
        result = _parse_ollama_json(response, "image classification")

        raw_tags = result.get("tags")
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
            raise RuntimeError("Ollama image classification did not return a string tag list")
        tags = list(dict.fromkeys(tag.strip().lower() for tag in raw_tags if tag.strip()))[:5]
        caption = str(result.get("caption", "")).strip()
        primary = _safe_folder_name(str(result.get("folder", "")))
        if not tags:
            tags = ["unclassified"]
        if not caption:
            caption = "No caption returned by local model."
        if primary == "uncategorized":
            primary = tags[0]

        return ImageContext(
            file_path=str(file_path.resolve()),
            upload_id="ollama-local",
            tags=tags,
            confidences={tag: 0.0 for tag in tags},
            caption=caption,
            primary_folder=primary,
        )

    def choose_folders(
        self, contexts: list[ImageContext], category_root: Path
    ) -> list[ImageContext]:
        if not contexts:
            return contexts
        existing = (
            sorted(entry.name for entry in category_root.iterdir() if entry.is_dir())
            if category_root.exists()
            else []
        )
        images = [
            {"id": index, "filename": Path(context.file_path).name,
             "tags": context.tags, "caption": context.caption}
            for index, context in enumerate(contexts)
        ]
        prompt = (
            "Choose exactly one concise, lowercase category folder for every image. "
            "Prefer an existing category when it accurately fits; otherwise create a "
            "new, precise and reusable semantic category. Folder names must be a single "
            "relative directory name (letters, numbers, spaces, underscores, or hyphens only). "
            "Return exactly one id/folder object for every image and no other keys.\n\n"
            f"Existing categories: {json.dumps(existing)}\n"
            f"Images and local semantic context: {json.dumps(images, ensure_ascii=False)}"
        )
        response = _ollama_request(
            "/api/chat",
            {
                "model": self.model_name,
                "stream": False,
                "format": FOLDER_BATCH_SCHEMA,
                "options": {"temperature": 0, "num_predict": max(80, len(contexts) * 40)},
                "think": False,
                "messages": [
                    {"role": "system", "content": FOLDER_NAMING_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        result = _parse_ollama_json(response, "image folder-selection")
        try:
            choices = result["folders"]
            folders = {
                choice.get("id"): _safe_folder_name(str(choice.get("folder", "")))
                for choice in choices
                if isinstance(choice, dict) and isinstance(choice.get("id"), int)
            }
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "Ollama image folder-selection response did not contain folders"
            ) from exc
        missing = [str(index) for index in range(len(contexts)) if index not in folders]
        if missing:
            raise RuntimeError("Ollama did not choose a folder for image id(s): " + ", ".join(missing))
        for index, context in enumerate(contexts):
            context.primary_folder = folders[index]
        return contexts


class OllamaDocumentClassifier:
    """Choose a document folder through a local Ollama text-capable model."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def choose_document_folder(
        self, file_path: Path, extracted_text: str, category_root: Path
    ) -> str:
        existing = (
            sorted(entry.name for entry in category_root.iterdir() if entry.is_dir())
            if category_root.exists()
            else []
        )
        prompt = (
            "Choose one concise, lowercase category folder for this document. "
            "Prefer an existing category when it fits. Return one JSON object matching "
            "the supplied schema and no other keys.\n\n"
            f"Existing categories: {json.dumps(existing)}\n"
            f"Filename: {file_path.name}\n"
            f"Document text:\n{extracted_text}"
        )
        response = _ollama_request(
            "/api/chat",
            {
                "model": self.model_name,
                "stream": False,
                "format": FOLDER_SCHEMA,
                "options": {"temperature": 0, "num_predict": 80},
                "think": False,
                "messages": [
                    {"role": "system", "content": FOLDER_NAMING_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        result = _parse_ollama_json(response, "document classification")
        try:
            folder = result["folder"]
        except KeyError as exc:
            raise RuntimeError(
                "Ollama document classification response did not contain a folder"
            ) from exc
        if not isinstance(folder, str):
            raise RuntimeError("Ollama document classification returned a non-string folder")
        return _safe_folder_name(folder)


def build_image_classifier(config: dict, min_confidence: float) -> ImageClassifier:
    backend = config.get("backend", "unconfigured")

    if backend == "hosted":
        return HostedImageClassifier(min_confidence=min_confidence)

    if backend == "local":
        local_cfg = config.get("local", {})
        model_name = local_cfg.get("model") or local_cfg.get("recommended_model")
        if not model_name:
            raise EnvironmentError("No local Ollama model is configured. Run `refactor setup`.")
        if not ollama_server_available():
            raise EnvironmentError("Ollama is not running. Start it with `ollama serve`.")
        if not ollama_model_available(model_name):
            raise EnvironmentError(
                f"Ollama model '{model_name}' is not installed. Run `ollama pull {model_name}`."
            )
        return OllamaImageClassifier(model_name=model_name)

    raise EnvironmentError(
        "Refactor setup is incomplete. Run 'refactor setup' to configure hosted or local backend."
    )


def build_document_classifier(config: dict):
    """Return the configured backend's folder classifier for documents."""
    if config.get("backend") == "hosted":
        return GeminiFolderClassifier()
    if config.get("backend") == "local":
        local_cfg = config.get("local", {})
        model_name = local_cfg.get("model") or local_cfg.get("recommended_model")
        if not model_name:
            raise EnvironmentError("No local Ollama model is configured. Run `refactor setup`.")
        if not ollama_server_available():
            raise EnvironmentError("Ollama is not running. Start it with `ollama serve`.")
        if not ollama_model_available(model_name):
            raise EnvironmentError(
                f"Ollama model '{model_name}' is not installed. Run `ollama pull {model_name}`."
            )
        return OllamaDocumentClassifier(model_name)
    raise EnvironmentError(
        "Refactor setup is incomplete. Run 'refactor setup' to configure hosted or local backend."
    )


def choose_category_folders(
    config: dict, contexts: list[ImageContext], category_root: Path
) -> list[ImageContext]:
    """Use the configured model to consistently choose category folders."""
    if config.get("backend") == "hosted":
        return GeminiFolderClassifier().choose_folders(contexts, category_root)
    if config.get("backend") == "local":
        local_cfg = config.get("local", {})
        model_name = local_cfg.get("model") or local_cfg.get("recommended_model")
        if not model_name:
            raise EnvironmentError("No local Ollama model is configured. Run `refactor setup`.")
        return OllamaImageClassifier(model_name).choose_folders(contexts, category_root)
    return contexts
