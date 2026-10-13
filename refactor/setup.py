from __future__ import annotations

import os
import shutil
import subprocess
import sys

import typer

from refactor.config import config_exists, default_config, load_config, save_config, save_env_vars
from refactor.hardware import detect_hardware, recommend_local_model
from refactor.shim import (
    ollama_installed_models,
    ollama_model_available,
    ollama_server_available,
)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def masked_prompt(label: str) -> str:
    """Read a secret while rendering one asterisk per entered character.

    ``getpass`` and Typer's ``hide_input`` deliberately render nothing. This
    reader keeps terminal echo disabled but provides visible paste/type feedback
    without ever writing the secret itself to stdout.
    """
    if not _interactive():
        raise typer.BadParameter(f"{label} requires an interactive terminal.")

    typer.echo(f"{label}: ", nl=False)
    characters: list[str] = []

    if os.name == "nt":
        import msvcrt

        while True:
            character = msvcrt.getwch()
            if character in {"\r", "\n"}:
                break
            if character == "\003":
                raise KeyboardInterrupt
            if character in {"\b", "\x7f"}:
                if characters:
                    characters.pop()
                    typer.echo("\b \b", nl=False)
                continue
            if character.isprintable():
                characters.append(character)
                typer.echo("*", nl=False)
    else:
        import termios
        import tty

        file_descriptor = sys.stdin.fileno()
        original_settings = termios.tcgetattr(file_descriptor)
        try:
            tty.setraw(file_descriptor)
            while True:
                character = sys.stdin.read(1)
                if character in {"\r", "\n"}:
                    break
                if character == "\003":
                    raise KeyboardInterrupt
                if character == "\004":
                    raise EOFError
                if character in {"\b", "\x7f"}:
                    if characters:
                        characters.pop()
                        typer.echo("\b \b", nl=False)
                    continue
                if character.isprintable():
                    characters.append(character)
                    typer.echo("*", nl=False)
        finally:
            termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)

    typer.echo()
    return "".join(characters)


def _choose_local_model(recommended_model: str, installed_models: list[str]) -> str:
    """Let the user choose the hardware recommendation or an installed tag."""
    options = [recommended_model]
    options.extend(
        model
        for model in installed_models
        if model not in {recommended_model, f"{recommended_model}:latest"}
    )

    typer.echo("\nChoose an Ollama model:")
    typer.echo(f"  1) {recommended_model} (recommended for this computer)")
    for index, model in enumerate(options[1:], start=2):
        typer.echo(f"  {index}) {model} (already installed)")
    typer.echo("- Choose a vision-capable model to organize images.")

    selection = typer.prompt("Select option", default="1").strip()
    try:
        return options[int(selection) - 1]
    except (ValueError, IndexError):
        raise typer.BadParameter(f"Invalid model option. Choose 1 through {len(options)}.")


def run_setup() -> dict:
    config = default_config()

    typer.echo("\nRefactor setup")
    typer.echo("Choose backend:")
    typer.echo("  1) Hosted model (bring your own API keys)")
    typer.echo("  2) Local multimodal model with Ollama")

    choice = typer.prompt("Select option", default="1").strip()

    if choice == "1":
        typer.echo("\nCreate both provider credentials, then paste them below:")
        typer.echo("- Imagga API keys: https://imagga.com/auth/signup")
        typer.echo("- Google Gemini API key: https://aistudio.google.com/app/apikey")

        imagga_api_key = masked_prompt("IMAGGA_API_KEY")
        imagga_api_secret = masked_prompt("IMAGGA_API_SECRET")
        gemini_api_key = masked_prompt("GEMINI_API_KEY")

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
        if model.startswith("qwen3-vl:"):
            typer.echo("- Requires Ollama 0.12.7 or newer")
        typer.echo("- Model command: ollama pull " + model)

        config["backend"] = "local"
        config["setup_skipped"] = False
        config["local"]["runtime"] = "ollama"
        config["local"]["recommended_model"] = model
        config["local"]["status"] = "not_ready"

        if not shutil.which("ollama"):
            typer.echo("\nOllama is not installed, so Refactor cannot use a local model yet.")
            typer.echo("Install Ollama from: https://ollama.com/download")
            typer.echo("Then run:")
            typer.echo(f"  ollama pull {model}")
            typer.echo("  refactor setup")
        elif not ollama_server_available():
            typer.echo("\nOllama is installed but its local server is not running.")
            typer.echo("Start it in another terminal with:")
            typer.echo("  ollama serve")
            typer.echo("Then rerun: refactor setup")
        else:
            selected_model = _choose_local_model(model, ollama_installed_models())
            config["local"]["model"] = selected_model
            if ollama_model_available(selected_model):
                config["local"]["status"] = "ready"
                typer.echo(f"\nOllama model '{selected_model}' is installed and ready to use.")
            elif typer.confirm(f"Download '{selected_model}' now?", default=True):
                result = subprocess.run(["ollama", "pull", selected_model], check=False)
                if result.returncode == 0 and ollama_model_available(selected_model):
                    config["local"]["status"] = "ready"
                    typer.echo(f"Local model '{selected_model}' is ready to use.")
                else:
                    typer.echo(
                        f"Could not verify '{selected_model}'. Run `ollama pull {selected_model}` and then `refactor setup` again."
                    )
            else:
                typer.echo(f"Run `ollama pull {selected_model}` and then `refactor setup` when ready.")

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
