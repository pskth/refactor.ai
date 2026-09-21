import typer
from refactor.tree import print_tree
from importlib.metadata import version as get_version
from refactor.validation import validate_path
from refactor.scanner import scan_directory
from refactor.metadata import get_metadata
from refactor.ignore import load_ignore_patterns

app = typer.Typer(no_args_is_help=True)

@app.command()
def version():
    """Print version information"""
    print(get_version("refactor-cli"))

if __name__ == "__main__":
    app()

# validates folder
@app.command()
def tree(path: str = "."):
    """Display folder structure of given path"""
    try:
        validate_path(path)
        print_tree(path)

    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1) 

@app.command()
def scan(path: str = "."):
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


# ---------------------------------------------------------------------------
# get-image-context
# ---------------------------------------------------------------------------

@app.command(name="get-image-context")
def get_image_context(
    path: str = typer.Argument(".", help="Directory to scan for images"),
    output: str = typer.Option(
        ".refactor_image_context.json",
        "--output", "-o",
        help="Path to write the JSON context cache",
    ),
    min_confidence: float = typer.Option(
        40.0,
        "--min-confidence",
        help="Minimum Imagga tag confidence to include (0–100)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Print per-image tag results to stdout",
    ),
):
    """
    Scan a directory for images, upload each to Imagga, and save
    AI-generated tags and captions to a JSON context cache.
    """
    from pathlib import Path
    from refactor.image_scanner import scan_images
    from refactor.imagga import ImaggaClient
    from refactor.context_store import save_context

    # ── Validate path ──────────────────────────────────────────────────
    try:
        validate_path(path)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # ── Scan for images ────────────────────────────────────────────────
    patterns = load_ignore_patterns()
    images = scan_images(path, patterns)

    if not images:
        typer.echo("No image files found in the specified directory.")
        raise typer.Exit(code=0)

    typer.echo(f"Found {len(images)} image(s) in '{path}'")

    # ── Init Imagga client ─────────────────────────────────────────────
    try:
        client = ImaggaClient(min_confidence=min_confidence)
    except EnvironmentError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # ── Process images with progress bar ──────────────────────────────
    results = []
    failed = 0

    with typer.progressbar(images, label="Analysing images") as progress:
        for img_path in progress:
            try:
                ctx = client.get_tags(img_path)
                results.append(ctx)

                if verbose:
                    typer.echo(f"\n  {img_path.name}")
                    typer.echo(f"    Folder   : {ctx.primary_folder}")
                    typer.echo(f"    Tags     : {', '.join(ctx.tags[:5])}")
                    typer.echo(f"    Caption  : {ctx.caption}")

            except Exception as exc:
                typer.echo(f"\n  [!] Skipping {img_path.name}: {exc}", err=True)
                failed += 1

    # ── Save cache ─────────────────────────────────────────────────────
    output_path = Path(output)
    save_context(results, path, output_path)

    # ── Summary ────────────────────────────────────────────────────────
    typer.echo(f"\n{'─' * 52}")
    typer.echo(f"  Processed : {len(results)} image(s)")
    if failed:
        typer.echo(f"  Failed    : {failed} image(s)")
    typer.echo(f"  Cache     : {output_path.resolve()}")
    typer.echo(f"{'─' * 52}")

    if results:
        # Print summary table
        typer.echo(f"\n{'Filename':<30} {'Folder':<20} {'Top tags'}")
        typer.echo("─" * 80)
        for ctx in results:
            fname = Path(ctx.file_path).name
            top_tags = ", ".join(ctx.tags[:3])
            typer.echo(f"  {fname:<28} {ctx.primary_folder:<20} {top_tags}")


# ---------------------------------------------------------------------------
# refactor-images
# ---------------------------------------------------------------------------

@app.command(name="refactor-images")
def refactor_images(
    context: str = typer.Option(
        ".refactor_image_context.json",
        "--context", "-c",
        help="Path to the JSON context cache (from get-image-context)",
    ),
    output_dir: str = typer.Option(
        ".",
        "--output-dir", "-d",
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
):
    """
    Organise images into tag-named subdirectories using the context cache
    produced by get-image-context.

    By default, images are COPIED (non-destructive).
    Use --move to move them instead.
    """
    from pathlib import Path
    from refactor.context_store import load_context
    from refactor.organizer import plan_moves, execute_moves

    # ── Load cache ─────────────────────────────────────────────────────
    try:
        contexts = load_context(Path(context))
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if not contexts:
        typer.echo("Context cache is empty. Nothing to organize.")
        raise typer.Exit(code=0)

    # ── Plan moves ─────────────────────────────────────────────────────
    out = Path(output_dir)
    moves = plan_moves(contexts, out)

    action_word = "Move" if move else "Copy"

    # ── Dry-run: just print the plan ───────────────────────────────────
    if dry_run:
        verb = "move" if move else "copy"
        verb_past = "moved" if move else "copied"
        verb_plural = "moves" if move else "copies"
        typer.echo(f"\n[Dry Run] Planned {verb_plural} ({len(moves)} files):\n")
        typer.echo(f"  {'Source':<40} {'Destination'}")
        typer.echo("  " + "─" * 76)
        for src, dst in moves:
            typer.echo(f"  {src.name:<40} {dst}")
        typer.echo(f"\n  No files were {verb_past}.")
        raise typer.Exit(code=0)

    # ── Confirm before executing ───────────────────────────────────────
    folders = {dst.parent.name for _, dst in moves}
    typer.echo(f"\nWill {action_word.lower()} {len(moves)} image(s) into {len(folders)} folder(s):")
    for folder in sorted(folders):
        count = sum(1 for _, dst in moves if dst.parent.name == folder)
        typer.echo(f"  {out / folder}  ({count} file(s))")

    # ── Execute ────────────────────────────────────────────────────────
    verb_past = "moved" if move else "copied"
    summary = execute_moves(moves, copy=not move)

    # ── Result summary ─────────────────────────────────────────────────
    typer.echo(f"\n{'─' * 52}")
    count = summary["moved"] if move else summary["copied"]
    typer.echo(f"  {verb_past.capitalize():<8}: {count} file(s)")
    if summary["failed"]:
        typer.echo(f"  Failed  : {summary['failed']} file(s)")
    typer.echo(f"  Output  : {out.resolve()}")
    typer.echo(f"{'─' * 52}")