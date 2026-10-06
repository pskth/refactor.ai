import typer
from importlib.metadata import version as get_version

from refactor.context_store import save_context
from refactor.ignore import load_ignore_patterns
from refactor.image_scanner import scan_images
from refactor.metadata import get_metadata
from refactor.organizer import execute_moves, plan_moves
from refactor.scanner import scan_directory
from refactor.setup import command_setup, ensure_backend_configured, maybe_run_first_time_setup
from refactor.shim import build_image_classifier
from refactor.tree import print_tree
from refactor.validation import validate_path

app = typer.Typer(no_args_is_help=True)


@app.callback()
def bootstrap() -> None:
    maybe_run_first_time_setup()


@app.command()
def version() -> None:
    """Print version information"""
    print(get_version("refactor-cli"))


@app.command()
def setup() -> None:
    """Configure hosted or local multimodal backend."""
    command_setup()


@app.command()
def tree(path: str = ".") -> None:
    """Display folder structure of given path"""
    try:
        validate_path(path)
        print_tree(path)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def scan(path: str = ".") -> None:
    """Scan directory and display metadata"""
    try:
        validate_path(path)
        patterns = load_ignore_patterns()
        items = scan_directory(path, patterns)

        for item in items:
            print(get_metadata(item))

    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@app.command(name="get-image-context")
def get_image_context(
    path: str = typer.Argument(".", help="Directory to scan for images"),
    output: str = typer.Option(
        ".refactor_image_context.json",
        "--output",
        "-o",
        help="Path to write the JSON context cache",
    ),
    min_confidence: float = typer.Option(
        40.0,
        "--min-confidence",
        help="Minimum tag confidence to include (hosted backend only)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print per-image tag results to stdout",
    ),
) -> None:
    """
    Scan directory images using configured backend shim and save
    tags/captions to JSON context cache.
    """
    from pathlib import Path

    try:
        validate_path(path)
        config = ensure_backend_configured()
    except (ValueError, EnvironmentError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    patterns = load_ignore_patterns()
    images = scan_images(path, patterns)

    if not images:
        typer.echo("No image files found in the specified directory.")
        raise typer.Exit(code=0)

    typer.echo(f"Found {len(images)} image(s) in '{path}'")

    try:
        classifier = build_image_classifier(config, min_confidence=min_confidence)
    except EnvironmentError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    results = []
    failed = 0

    with typer.progressbar(images, label="Analysing images") as progress:
        for img_path in progress:
            try:
                ctx = classifier.classify_image(img_path)
                results.append(ctx)

                if verbose:
                    typer.echo(f"\n  {img_path.name}")
                    typer.echo(f"    Folder   : {ctx.primary_folder}")
                    typer.echo(f"    Tags     : {', '.join(ctx.tags[:5])}")
                    typer.echo(f"    Caption  : {ctx.caption}")

            except Exception as exc:
                typer.echo(f"\n  [!] Skipping {img_path.name}: {exc}", err=True)
                failed += 1

    output_path = Path(output)
    save_context(results, path, output_path)

    typer.echo(f"\n{'─' * 52}")
    typer.echo(f"  Processed : {len(results)} image(s)")
    if failed:
        typer.echo(f"  Failed    : {failed} image(s)")
    typer.echo(f"  Cache     : {output_path.resolve()}")
    typer.echo(f"{'─' * 52}")

    if results:
        typer.echo(f"\n{'Filename':<30} {'Folder':<20} {'Top tags'}")
        typer.echo("─" * 80)
        for ctx in results:
            fname = Path(ctx.file_path).name
            top_tags = ", ".join(ctx.tags[:3])
            typer.echo(f"  {fname:<28} {ctx.primary_folder:<20} {top_tags}")


@app.command(name="refactor-images")
def refactor_images(
    context: str = typer.Option(
        ".refactor_image_context.json",
        "--context",
        "-c",
        help="Path to the JSON context cache (from get-image-context)",
    ),
    output_dir: str = typer.Option(
        ".",
        "--output-dir",
        "-d",
        help="Root directory where tag-named folders will be created",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the planned moves without executing them",
    ),
    move: bool = typer.Option(
        False,
        "--move",
        help="Move files instead of copying (destructive). Default is copy.",
    ),
) -> None:
    """
    Organise images into tag-named subdirectories using the context cache
    produced by get-image-context.

    By default, images are COPIED (non-destructive).
    Use --move to move them instead.
    """
    from pathlib import Path
    from refactor.context_store import load_context

    try:
        contexts = load_context(Path(context))
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if not contexts:
        typer.echo("Context cache is empty. Nothing to organize.")
        raise typer.Exit(code=0)

    out = Path(output_dir)
    moves = plan_moves(contexts, out)

    action_word = "Move" if move else "Copy"

    if dry_run:
        verb_plural = "moves" if move else "copies"
        verb_past = "moved" if move else "copied"
        typer.echo(f"\n[Dry Run] Planned {verb_plural} ({len(moves)} files):\n")
        typer.echo(f"  {'Source':<40} {'Destination'}")
        typer.echo("  " + "─" * 76)
        for src, dst in moves:
            typer.echo(f"  {src.name:<40} {dst}")
        typer.echo(f"\n  No files were {verb_past}.")
        raise typer.Exit(code=0)

    folders = {dst.parent.name for _, dst in moves}
    typer.echo(f"\nWill {action_word.lower()} {len(moves)} image(s) into {len(folders)} folder(s):")
    for folder in sorted(folders):
        count = sum(1 for _, dst in moves if dst.parent.name == folder)
        typer.echo(f"  {out / folder}  ({count} file(s))")

    summary = execute_moves(moves, copy=not move)

    typer.echo(f"\n{'─' * 52}")
    count = summary["moved"] if move else summary["copied"]
    verb_past = "moved" if move else "copied"
    typer.echo(f"  {verb_past.capitalize():<8}: {count} file(s)")
    if summary["failed"]:
        typer.echo(f"  Failed  : {summary['failed']} file(s)")
    typer.echo(f"  Output  : {out.resolve()}")
    typer.echo(f"{'─' * 52}")


if __name__ == "__main__":
    app()
