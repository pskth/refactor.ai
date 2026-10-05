from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class HardwareSpec:
    cpu_cores: int
    memory_gb: float
    has_nvidia_gpu: bool
    gpu_vram_gb: float | None = None


def _memory_gb() -> float:
    pagesize = os.sysconf("SC_PAGE_SIZE")
    pages = os.sysconf("SC_PHYS_PAGES")
    return round((pagesize * pages) / (1024**3), 2)


def _nvidia_vram_gb() -> float | None:
    if not shutil.which("nvidia-smi"):
        return None

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None

    values = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line) / 1024)
        except ValueError:
            continue

    return round(max(values), 2) if values else None


def detect_hardware() -> HardwareSpec:
    vram = _nvidia_vram_gb()
    return HardwareSpec(
        cpu_cores=os.cpu_count() or 1,
        memory_gb=_memory_gb(),
        has_nvidia_gpu=vram is not None,
        gpu_vram_gb=vram,
    )


def recommend_local_model(spec: HardwareSpec) -> tuple[str, str]:
    if spec.has_nvidia_gpu and (spec.gpu_vram_gb or 0) >= 8:
        return (
            "llava:7b",
            "Good fit for GPU-backed image understanding with balanced quality/speed.",
        )

    if spec.memory_gb >= 16:
        return (
            "llava:7b-q4",
            "Reasonable CPU-only option with quantization for 16GB+ RAM systems.",
        )

    if spec.memory_gb >= 8:
        return (
            "moondream",
            "Lightweight option for lower-memory systems focused on image captioning.",
        )

    return (
        "nanollava",
        "Very small fallback model for constrained hardware; expect limited accuracy.",
    )
