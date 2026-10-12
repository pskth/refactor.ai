# refactor.ai

`refactor.ai` is a Python CLI for inspecting local directories before automating file organization. The package is published as [`refactor-cli`](https://pypi.org/project/refactor-cli/) and targets Python 3.8+.

## Current scope

The CLI entry point in [refactor/cli.py](refactor/cli.py) provides:

- `version` — prints the installed package version.
- `tree` — prints a recursive directory tree through [refactor/tree.py](refactor/tree.py).
- `scan` — collects basic file and directory metadata through [refactor/scanner.py](refactor/scanner.py) and [refactor/metadata.py](refactor/metadata.py).
- `setup` — configures a multimodal backend (`hosted` or `local`), persisted to `~/.refactor/config.json`.
- `get-image-context` — obtains image tags/captions and asks the configured
  backend to choose a destination category, then writes JSON context.
- `refactor-images` — automatically refreshes image context with the configured
  backend, then moves images into model-selected category folders (`--copy` is
  available when the originals must be retained).
- `refactor-text` — uses the configured backend to categorize `.txt`, `.md`,
  `.pdf`, and `.docx` files.
- `now` — runs `refactor-text` and then `refactor-images`, so mixed folders are
  organized in one invocation.
- Path checks through [refactor/validation.py](refactor/validation.py), including existence, directory type, and read access.
- Optional filename exclusions through [refactor/ignore.py](refactor/ignore.py).

On first CLI run, users are prompted to run setup. They can rerun setup anytime with `refactor setup` or edit `~/.refactor/config.json` directly.

## Setup workflow

After installing `refactor-cli`, the first CLI run prompts:

1. **Hosted model (bring your own API keys)**  
   - Prompts for `IMAGGA_API_KEY`, `IMAGGA_API_SECRET`, and `GEMINI_API_KEY`  
   - Saves credentials to `~/.refactor/.env` with restricted file permissions
2. **Local multimodal model with Ollama**
   - Detects CPU, memory, and NVIDIA hardware (even if VRAM is temporarily unavailable)
   - Recommends a vision model and verifies the local Ollama runtime
   - Guides the user to install Ollama or pulls the recommended model when Ollama is ready
   - Sends images to the local Ollama API for captions, tags, and category selection; documents are text-extracted locally and categorized through the same Ollama model. No image or document data is uploaded to Refactor services.

For a local setup, install [Ollama](https://ollama.com/download), then run the exact command printed by setup, for example:

```shell
ollama pull gemma3:4b
```

Run `refactor setup` again after the download finishes. Refactor verifies both the local Ollama service and the selected model before classifying images or documents.

For the hosted workflow, local images are uploaded to Imagga and classified with
the V3 `/tags` endpoint using `model=light` and `include_caption=true`. The
resulting tags/caption and the destination root's current folders are sent to
Gemini. Gemini selects one safe category name per image, reusing a suitable
folder where possible and naming a new category otherwise. The organizer creates
that directory as needed. The shim layer provides one interface for image
classification, regardless of hosted/local backend, so future modalities can
reuse the same abstraction.

Run `refactor refactor-images ./incoming --output-dir ./organized` to generate
fresh context and move the images. Add `--dry-run` to inspect destinations or
`--copy` to retain the originals.

Run `refactor now ./incoming --output-dir ./organized` to organize supported
documents and images together. Hosted mode sends PDFs to Gemini as native
document input; local mode text-extracts PDFs, text, Markdown, and Word files
before sending their contents to Ollama.

`--dry-run` saves a source-validated organization plan. Running the same command
without `--dry-run` reuses that plan without another Imagga or Gemini request,
provided the source files and output directory are unchanged. Any added, removed,
or modified source file invalidates the plan and triggers fresh classification.

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
