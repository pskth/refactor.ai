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


# Approximate download sizes for Ollama's current Qwen3-VL quantized tags.
# The selector reserves capacity for the OS, image encoder, context, and the
# rest of Refactor instead of attempting to consume every reported GB.
MULTIMODAL_MODEL_TIERS: tuple[tuple[str, float], ...] = (
    ("qwen3-vl:32b", 21.0),
    ("qwen3-vl:30b", 20.0),
    ("qwen3-vl:8b", 6.1),
    ("qwen3-vl:4b", 3.3),
    ("qwen3-vl:2b", 1.9),
)


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
    """Recommend the largest local vision-and-text model likely to fit.

    GPU VRAM is preferred because it determines whether the model can run at
    useful speed. System RAM remains a valid fallback: Ollama can run a model
    on CPU (or partially offload it) when VRAM is insufficient.
    """
    gpu_budget = (spec.gpu_vram_gb or 0) * 0.80
    ram_budget = spec.memory_gb * 0.60

    for model, size_gb in MULTIMODAL_MODEL_TIERS:
        if spec.has_nvidia_gpu and gpu_budget >= size_gb:
            return (
                model,
                f"Largest Qwen3-VL vision-and-text model expected to fit in {spec.gpu_vram_gb:.1f} GB "
                "of NVIDIA VRAM while reserving capacity for runtime overhead.",
            )
        if ram_budget >= size_gb:
            if spec.has_nvidia_gpu:
                return (
                    model,
                    f"Largest model expected to fit in {spec.memory_gb:.1f} GB of system RAM. "
                    "It may partially run on CPU because available GPU VRAM is lower.",
                )
            return (
                model,
                f"Largest vision-and-text model expected to fit in {spec.memory_gb:.1f} GB of system RAM. "
                "CPU-only inference will be slower.",
            )

    model, size_gb = MULTIMODAL_MODEL_TIERS[-1]
    return (
        model,
        f"Smallest supported vision-and-text model ({size_gb:.1f} GB download). "
        "Available memory is below the recommended headroom; use hosted mode if it cannot run reliably.",
    )
