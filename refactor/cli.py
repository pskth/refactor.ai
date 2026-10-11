import typer
from importlib.metadata import version as get_version

from refactor.context_store import DEFAULT_CACHE_FILE, save_context
from refactor.ignore import load_ignore_patterns
from refactor.image_scanner import scan_images
from refactor.metadata import get_metadata
from refactor.organizer import (
    execute_moves,
    managed_category_dirs,
    plan_moves,
    save_managed_category_dirs,
)
from refactor.scanner import scan_directory
from refactor.setup import command_setup, ensure_backend_configured, maybe_run_first_time_setup
from refactor.shim import build_image_classifier, choose_category_folders
from refactor.text import (
    classify_documents,
    managed_text_dirs,
    save_managed_text_dirs,
    scan_documents,
)
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
    category_root: str = typer.Option(
        ".",
        "--category-root",
        help="Directory whose existing folders Gemini may reuse",
    ),
    write_context: bool = typer.Option(
        True,
        "--write-context/--no-write-context",
        hidden=True,
    ),
) -> list:
    """
    Scan directory images using configured backend shim and save
    tags/captions to JSON context cache.
    """
    from pathlib import Path

    try:
        validate_path(path)
        if not Path(category_root).exists() or not Path(category_root).is_dir():
            raise ValueError(f"Category root is not a directory: {category_root}")
        config = ensure_backend_configured()
    except (ValueError, EnvironmentError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    patterns = load_ignore_patterns()
    source_root = Path(path).resolve()
    destination_root = Path(category_root).resolve()
    excluded_dirs = (
        managed_category_dirs(destination_root)
        if source_root == destination_root else set()
    )
    images = scan_images(path, patterns, excluded_dirs)

    if not images:
        typer.echo("No image files found in the specified directory.")
        return []

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

            except Exception as exc:
                typer.echo(f"\n  [!] Skipping {img_path.name}: {exc}", err=True)
                failed += 1

    if results:
        try:
            results = choose_category_folders(config, results, Path(category_root))
        except Exception as exc:
            # Folder selection is an essential part of the hosted workflow; do
            # not silently fall back to an Imagga top-tag directory.
            typer.echo(f"Error: Gemini folder selection failed: {exc}", err=True)
            raise typer.Exit(code=1)

    if verbose:
        for ctx in results:
            typer.echo(f"\n  {Path(ctx.file_path).name}")
            typer.echo(f"    Folder   : {ctx.primary_folder}")
            typer.echo(f"    Tags     : {', '.join(ctx.tags[:5])}")
            typer.echo(f"    Caption  : {ctx.caption}")

    output_path = Path(output)
    if write_context:
        save_context(results, path, output_path)

    typer.echo(f"\n{'─' * 52}")
    typer.echo(f"  Processed : {len(results)} image(s)")
    if failed:
        typer.echo(f"  Failed    : {failed} image(s)")
    if write_context:
        typer.echo(f"  Cache     : {output_path.resolve()}")
    typer.echo(f"{'─' * 52}")

    if results:
        typer.echo(f"\n{'Filename':<30} {'Folder':<20} {'Top tags'}")
        typer.echo("─" * 80)
        for ctx in results:
            fname = Path(ctx.file_path).name
            top_tags = ", ".join(ctx.tags[:3])
            typer.echo(f"  {fname:<28} {ctx.primary_folder:<20} {top_tags}")

    return results


@app.command(name="refactor-text")
def refactor_text(
    path: str = typer.Argument(".", help="Directory containing documents to organize"),
    output_dir: str = typer.Option(".", "--output-dir", "-d"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    move: bool = typer.Option(True, "--move/--copy"),
) -> list:
    """Use Gemini to categorize .txt, .md, .pdf, and .docx files."""
    from pathlib import Path

    try:
        validate_path(path)
        out = Path(output_dir)
        if not out.exists() or not out.is_dir():
            raise ValueError(f"Output directory is not a directory: {output_dir}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    patterns = load_ignore_patterns()
    excluded = managed_text_dirs(out) if Path(path).resolve() == out.resolve() else set()
    documents = scan_documents(path, patterns, excluded)
    if not documents:
        typer.echo("No supported document files found in the specified directory.")
        return []

    typer.echo(f"Found {len(documents)} document(s) in '{path}'")
    try:
        contexts, failures = classify_documents(documents, out)
    except EnvironmentError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    for document, error in failures:
        typer.echo(f"  [!] Skipping {document.name}: {error}", err=True)

    if not contexts:
        typer.echo("No documents were categorized.")
        return []

    moves = plan_moves(contexts, out)
    if dry_run:
        typer.echo(f"\n[Dry Run] Planned document moves ({len(moves)} files):")
        for src, dst in moves:
            typer.echo(f"  {src} → {dst}")
        return contexts

    summary = execute_moves(moves, copy=not move)
    folders = {destination.parent.name for _, destination in moves}
    if not summary["failed"]:
        save_managed_text_dirs(out, folders)
    verb = "Moved" if move else "Copied"
    typer.echo(f"{verb} {summary['moved'] if move else summary['copied']} document(s).")
    return contexts


@app.command(name="refactor-images")
def refactor_images(
    path: str = typer.Argument(".", help="Directory containing images to organize"),
    context: str = typer.Option(
        ".refactor_image_context.json",
        "--context",
        "-c",
        help="Path to context cache (defaults to the source directory)",
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
        True,
        "--move/--copy",
        help="Move files into categories. Use --copy to preserve source files.",
    ),
    min_confidence: float = typer.Option(
        40.0,
        "--min-confidence",
        help="Minimum Imagga tag confidence to retain",
    ),
) -> list:
    """
    Generate fresh Imagga and Gemini context, then organise images into
    Gemini-selected subdirectories. The context cache is refreshed on every run.

    By default, images are MOVED. Use --copy to preserve source files.
    """
    from pathlib import Path
    try:
        validate_path(path)
        out = Path(output_dir)
        if not out.exists() or not out.is_dir():
            raise ValueError(f"Output directory is not a directory: {output_dir}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    context_path = Path(context)
    if context == DEFAULT_CACHE_FILE:
        context_path = Path(path) / DEFAULT_CACHE_FILE

    excluded = managed_category_dirs(out) if Path(path).resolve() == out.resolve() else set()
    if excluded:
        typer.echo(f"Skipping {len(excluded)} folder(s) created by an earlier Refactor run.")

    typer.echo("Generating image context with Imagga and Gemini...")
    contexts = get_image_context(
        path=path,
        output=str(context_path),
        min_confidence=min_confidence,
        verbose=False,
        category_root=output_dir,
        write_context=not dry_run,
    )

    if not contexts:
        typer.echo("Context cache is empty. Nothing to organize.")
        return []

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
        return contexts

    folders = {dst.parent.name for _, dst in moves}
    typer.echo(f"\nWill {action_word.lower()} {len(moves)} image(s) into {len(folders)} folder(s):")
    for folder in sorted(folders):
        count = sum(1 for _, dst in moves if dst.parent.name == folder)
        typer.echo(f"  {out / folder}  ({count} file(s))")

    summary = execute_moves(moves, copy=not move)
    if not summary["failed"]:
        save_managed_category_dirs(out, folders)

    typer.echo(f"\n{'─' * 52}")
    count = summary["moved"] if move else summary["copied"]
    verb_past = "moved" if move else "copied"
    typer.echo(f"  {verb_past.capitalize():<8}: {count} file(s)")
    if summary["failed"]:
        typer.echo(f"  Failed  : {summary['failed']} file(s)")
    typer.echo(f"  Output  : {out.resolve()}")
    typer.echo(f"{'─' * 52}")
    return contexts


@app.command(name="now")
def refactor_now(
    path: str = typer.Argument(".", help="Directory containing documents and images"),
    output_dir: str = typer.Option(".", "--output-dir", "-d"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    move: bool = typer.Option(True, "--move/--copy"),
    min_confidence: float = typer.Option(40.0, "--min-confidence"),
) -> None:
    """Categorize supported documents first, then images in a mixed folder."""
    typer.echo("\n[1/2] Categorizing documents")
    refactor_text(path=path, output_dir=output_dir, dry_run=dry_run, move=move)
    typer.echo("\n[2/2] Categorizing images")
    refactor_images(
        path=path,
        context=DEFAULT_CACHE_FILE,
        output_dir=output_dir,
        dry_run=dry_run,
        move=move,
        min_confidence=min_confidence,
    )


if __name__ == "__main__":
    app()
