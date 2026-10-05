# refactor.ai

`refactor.ai` is a Python CLI for inspecting local directories before automating file organization. The package is published as [`refactor-cli`](https://pypi.org/project/refactor-cli/) and targets Python 3.8+.

## Current scope

The CLI entry point in [refactor/cli.py](refactor/cli.py) provides:

- `version` — prints the installed package version.
- `tree` — prints a recursive directory tree through [refactor/tree.py](refactor/tree.py).
- `scan` — collects basic file and directory metadata through [refactor/scanner.py](refactor/scanner.py) and [refactor/metadata.py](refactor/metadata.py).
- `setup` — configures a multimodal backend (`hosted` or `local`), persisted to `~/.refactor/config.json`.
- `get-image-context` — classifies images using a backend shim layer and writes JSON context.
- `refactor-images` — copies or moves images based on generated context.
- Path checks through [refactor/validation.py](refactor/validation.py), including existence, directory type, and read access.
- Optional filename exclusions through [refactor/ignore.py](refactor/ignore.py).

On first CLI run, users are prompted to run setup. They can rerun setup anytime with `refactor setup` or edit `~/.refactor/config.json` directly.

## Setup workflow

After installing `refactor-cli`, the first CLI run prompts:

1. **Hosted model (bring your own API keys)**  
   - Prompts for `IMAGGA_API_KEY`, `IMAGGA_API_SECRET`, and `GEMINI_API_KEY`  
   - Saves credentials to `~/.refactor/.env` with restricted file permissions
2. **Local multimodal recommendation (stub)**  
   - Detects basic hardware (CPU, memory, NVIDIA GPU/VRAM if available)  
   - Recommends an OSS multimodal model and records it in config  
   - Uses a local shim stub today (full local runtime integration is a follow-up)

The shim layer provides one interface for image classification, regardless of hosted/local backend, so future modalities can reuse the same abstraction.

## Techniques used

- **Recursive traversal with `pathlib`** — [refactor/scanner.py](refactor/scanner.py) uses [`Path.rglob()`](https://docs.python.org/3/library/pathlib.html#pathlib.Path.rglob) to discover nested paths. [refactor/tree.py](refactor/tree.py) recursively walks directory entries to render a text tree.

- **Filesystem metadata from stat data** — [refactor/metadata.py](refactor/metadata.py) reads [`Path.stat()`](https://docs.python.org/3/library/pathlib.html#pathlib.Path.stat) and combines it with path properties such as `name`, `suffix`, and `is_dir()`.

- **Glob-based ignore matching** — [refactor/ignore.py](refactor/ignore.py) loads patterns from an optional `.refactorignore` file and evaluates them with Python’s [`fnmatch`](https://docs.python.org/3/library/fnmatch.html). This keeps ignore rules lightweight while supporting familiar wildcard patterns.

- **Fail-fast input validation** — [refactor/validation.py](refactor/validation.py) validates paths before traversal and checks read permissions with [`os.access()`](https://docs.python.org/3/library/os.html#os.access). CLI commands convert validation failures into clear non-zero exits.

- **Declarative command registration** — [refactor/cli.py](refactor/cli.py) uses decorators to register commands on a Typer application. The package exports the `refactor` command through the console-script entry point in [pyproject.toml](pyproject.toml).

- **Versioning from Git tags** — [pyproject.toml](pyproject.toml) delegates package version discovery to [`setuptools-scm`](https://setuptools-scm.readthedocs.io/). Release versions can come from repository tags instead of being duplicated in source files.

## Technologies and libraries

- [Typer](https://typer.tiangolo.com/) — CLI framework built around Python type hints. It provides command dispatch, help output, and exit handling.
- [setuptools](https://setuptools.pypa.io/) — package build backend.
- [setuptools-scm](https://setuptools-scm.readthedocs.io/) — derives the distribution version from source-control metadata.
- [pathlib](https://docs.python.org/3/library/pathlib.html) — standard-library object model for portable path operations.
- [importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html) — reads the installed package version at runtime.

The project currently has no web UI, image assets, or bundled fonts.

## Project structure

```text
.
├── LICENSE
├── README.md
├── pyproject.toml
└── refactor/
```

- [refactor/](refactor/) contains the CLI and filesystem logic.
- [pyproject.toml](pyproject.toml) defines packaging metadata, the `refactor` command, supported Python version, and build configuration.
- [LICENSE](LICENSE) contains the Apache License 2.0 terms.

## Next steps

The package metadata describes the broader goal as AI-assisted file organization. The next development work can build on the current inspection layer:

- Add an AI integration that proposes organization decisions from scanned metadata.
- Add a review step so users can inspect proposed changes before any write operation.
- Implement explicit rename and move operations with dry-run support.
- Expand ignore handling beyond filename-only matching where needed.
- Add automated tests for traversal, ignore patterns, validation, and planned write operations.
- Provide structured scan output for scripts and other tooling.
