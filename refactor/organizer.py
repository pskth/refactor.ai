"""
refactor/organizer.py
~~~~~~~~~~~~~~~~~~~~~
Plans and executes image reorganization into tag-named directories.

Default behaviour: COPY files (non-destructive).
Pass copy=False to MOVE files instead.
"""

import shutil
from pathlib import Path

from refactor.imagga import ImageContext


def plan_moves(
    contexts: list[ImageContext],
    output_dir: Path,
) -> list[tuple[Path, Path]]:
    """
    Compute (source, destination) path pairs for all images.

    - Each image is placed under  output_dir/<primary_folder>/<filename>
    - If the destination filename already exists, a numeric suffix is appended
      (e.g. photo_1.jpg, photo_2.jpg).

    Returns a list of (src, dst) tuples.
    """
    moves: list[tuple[Path, Path]] = []
    # Track used destination paths to handle collisions
    used: set[Path] = set()

    for ctx in contexts:
        src = Path(ctx.file_path)
        folder = output_dir / ctx.primary_folder
        dst = folder / src.name

        # Resolve collisions
        if dst in used or dst.exists():
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while dst in used or dst.exists():
                dst = folder / f"{stem}_{counter}{suffix}"
                counter += 1

        used.add(dst)
        moves.append((src, dst))

    return moves


def execute_moves(
    moves: list[tuple[Path, Path]],
    copy: bool = True,
) -> dict[str, int]:
    """
    Execute the planned moves/copies.

    Args:
        moves: List of (src, dst) path pairs from plan_moves().
        copy:  True  → shutil.copy2  (default, non-destructive)
               False → Path.rename   (move/destructive)

    Returns:
        A summary dict: {"copied": N, "moved": N, "failed": N}
    """
    summary = {"copied": 0, "moved": 0, "failed": 0}

    for src, dst in moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)

            if copy:
                shutil.copy2(src, dst)
                summary["copied"] += 1
            else:
                src.rename(dst)
                summary["moved"] += 1

        except Exception as exc:
            print(f"  [!] Failed {src.name} → {dst}: {exc}")
            summary["failed"] += 1

    return summary
