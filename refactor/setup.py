from __future__ import annotations

import sys

import typer

from refactor.config import config_exists, default_config, load_config, save_config, save_env_vars
from refactor.hardware import detect_hardware, recommend_local_model


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_setup() -> dict:
    config = default_config()

    typer.echo("\nRefactor setup")
    typer.echo("Choose backend:")
    typer.echo("  1) Hosted model (bring your own API keys)")
    typer.echo("  2) Local multimodal recommendation (stub integration)")

    choice = typer.prompt("Select option", default="1").strip()

    if choice == "1":
        typer.echo("\nCreate keys from provider dashboards and paste them below.")
        typer.echo("- Imagga: https://imagga.com")
        typer.echo("- Gemini: https://ai.google.dev")

        imagga_api_key = typer.prompt("IMAGGA_API_KEY", hide_input=True)
        imagga_api_secret = typer.prompt("IMAGGA_API_SECRET", hide_input=True)
        gemini_api_key = typer.prompt("GEMINI_API_KEY", hide_input=True)

        save_env_vars(
            {
                "IMAGGA_API_KEY": imagga_api_key,
                "IMAGGA_API_SECRET": imagga_api_secret,
                "GEMINI_API_KEY": gemini_api_key,
            }
        )

        config["backend"] = "hosted"
        config["setup_skipped"] = False
        typer.echo("Hosted backend configured. Keys stored in ~/.refactor/.env")

    elif choice == "2":
        spec = detect_hardware()
        model, reason = recommend_local_model(spec)

        typer.echo("\nDetected hardware:")
        typer.echo(f"- CPU cores: {spec.cpu_cores}")
        typer.echo(f"- RAM: {spec.memory_gb} GB")
        typer.echo(f"- NVIDIA GPU: {'yes' if spec.has_nvidia_gpu else 'no'}")
        if spec.gpu_vram_gb is not None:
            typer.echo(f"- GPU VRAM: {spec.gpu_vram_gb} GB")

        typer.echo("\nRecommended OSS multimodal model:")
        typer.echo(f"- Model: {model}")
        typer.echo(f"- Why: {reason}")
        typer.echo("- Suggested runtime: ollama")
        typer.echo("- Example install: ollama pull " + model)

        config["backend"] = "local"
        config["setup_skipped"] = False
        config["local"]["runtime"] = "ollama"
        config["local"]["recommended_model"] = model
        config["local"]["status"] = "stub"
        typer.echo("Local backend configured with stub shim for now.")

    else:
        raise typer.BadParameter("Invalid option. Choose 1 or 2.")

    save_config(config)
    return config


def maybe_run_first_time_setup() -> None:
    if config_exists() or not _interactive():
        return

    should_setup = typer.confirm(
        "No refactor setup found. Do you want to run setup now?",
        default=True,
    )

    if should_setup:
        run_setup()
        return

    config = default_config()
    config["backend"] = "unconfigured"
    config["setup_skipped"] = True
    save_config(config)


def command_setup() -> None:
    run_setup()


def ensure_backend_configured() -> dict:
    config = load_config()
    if config.get("backend") in {"hosted", "local"}:
        return config

    if _interactive() and typer.confirm(
        "Backend is not configured. Run setup now?",
        default=True,
    ):
        return run_setup()

    raise EnvironmentError(
        "Backend is not configured. Run 'refactor setup' or edit ~/.refactor/config.json."
    )
