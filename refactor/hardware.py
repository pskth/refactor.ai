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


def _run(command: list[str]) -> str | None:
    """Return command output without allowing hardware probes to fail setup."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _has_nvidia_gpu() -> bool:
    """Detect NVIDIA hardware even when the driver utility cannot report VRAM."""
    if shutil.which("nvidia-smi") and _run(["nvidia-smi", "-L"]):
        return True

    if os.name != "nt":
        pci_devices = _run(["lspci"])
        if pci_devices and "nvidia" in pci_devices.lower():
            return True
        nvidia_devices = "/proc/driver/nvidia/gpus"
        try:
            if os.path.isdir(nvidia_devices) and os.listdir(nvidia_devices):
                return True
        except OSError:
            pass
    else:
        output = _run(["wmic", "path", "win32_VideoController", "get", "name"])
        if output and "nvidia" in output.lower():
            return True

    return False


def _nvidia_vram_gb() -> float | None:
    if not shutil.which("nvidia-smi"):
        return None

    output = _run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if output is None:
        return None

    values = []
    for line in output.splitlines():
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
        has_nvidia_gpu=_has_nvidia_gpu(),
        gpu_vram_gb=vram,
    )


def recommend_local_model(spec: HardwareSpec) -> tuple[str, str]:
    if spec.has_nvidia_gpu and (spec.gpu_vram_gb or 0) >= 8:
        return (
            "gemma3:4b",
            "Multimodal instruction-following model suitable for both document and image organization.",
        )

    if spec.has_nvidia_gpu:
        return (
            "gemma3:4b",
            "A multimodal model is required for reliable structured document and image categorization; "
            "verify available memory if NVIDIA VRAM cannot be read.",
        )

    if spec.memory_gb >= 16:
        return (
            "gemma3:4b",
            "Multimodal model with enough context for document and image organization on 16GB+ RAM.",
        )

    if spec.memory_gb >= 8:
        return (
            "gemma3:4b",
            "Smallest recommended multimodal option for structured document and image organization; "
            "expect slower operation on CPU-only systems.",
        )

    return (
        "gemma3:4b",
        "Refactor requires a multimodal instruction-following model for all supported file types. "
        "This system may not have enough memory; use hosted mode or add memory if the model cannot run.",
    )
