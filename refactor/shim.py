from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from refactor.imagga import ImageContext, ImaggaClient


class ImageClassifier(ABC):
    @abstractmethod
    def classify_image(self, file_path: Path) -> ImageContext:
        raise NotImplementedError


class HostedImageClassifier(ImageClassifier):
    def __init__(self, min_confidence: float = 40.0) -> None:
        self.client = ImaggaClient(min_confidence=min_confidence)

    def classify_image(self, file_path: Path) -> ImageContext:
        return self.client.get_tags(file_path)


class LocalStubImageClassifier(ImageClassifier):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def classify_image(self, file_path: Path) -> ImageContext:
        name_tokens = [t for t in file_path.stem.lower().replace("-", "_").split("_") if t]
        tags = name_tokens[:3] if name_tokens else ["unclassified"]
        primary = tags[0] if tags else "unclassified"

        return ImageContext(
            file_path=str(file_path.resolve()),
            upload_id="local-stub",
            tags=tags,
            confidences={tag: 0.0 for tag in tags},
            caption=(
                f"Local stub classification using '{self.model_name}'. "
                "Install and connect a local multimodal runtime in a future step."
            ),
            primary_folder=primary,
        )


def build_image_classifier(config: dict, min_confidence: float) -> ImageClassifier:
    backend = config.get("backend", "unconfigured")

    if backend == "hosted":
        return HostedImageClassifier(min_confidence=min_confidence)

    if backend == "local":
        local_cfg = config.get("local", {})
        model_name = local_cfg.get("recommended_model") or "local-stub"
        return LocalStubImageClassifier(model_name=model_name)

    raise EnvironmentError(
        "Refactor setup is incomplete. Run 'refactor setup' to configure hosted or local backend."
    )
