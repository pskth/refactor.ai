# Refactor.ai: Technical Implementation Record

**Document status:** implementation record for research-paper preparation  
**Repository:** `pskth/refactor.ai`  
**Evidence cut-off:** 12 October 2026 (working tree inspected locally)  
**Revision baseline:** commit `c384031dd91bedfea518a629461a4c9f2f632098` plus uncommitted workspace changes present at inspection time  
**Package:** `refactor-cli`; Python CLI entry point: `refactor`

## 1. Purpose and research framing

Refactor.ai is an AI-assisted local file-organization command-line tool. It discovers supported files recursively, obtains semantic evidence using either hosted APIs or a local multimodal model, selects exactly one category folder per file, and copies or moves files into category directories. The design includes a dry-run plan cache so a reviewed plan can be executed later without repeating model calls if the input snapshot is unchanged.

### Research problem

Unstructured personal or project directories mix images and documents whose filenames alone may not reveal their content. Rule-only organization is brittle, while fully autonomous model-based moves risk incorrect, irreversible placement. The system investigates whether multimodal semantic classification can propose usable folder destinations while maintaining operational controls: constrained output, safe folder names, collision handling, dry runs, source validation, and managed-folder exclusion.

### Candidate paper claims—only where supported

1. Refactor.ai implements an end-to-end, two-backend workflow for categorizing eight image extensions and four document formats.
2. The system separates semantic extraction from folder selection in the hosted image pipeline: Imagga produces tags/captions; Gemini selects a consistent category from that evidence and existing output folders.
3. A source-validated plan cache prevents reuse after a file is added, removed, resized, or modified (based on absolute path, byte size, and nanosecond mtime).
4. The implementation contains safety mechanisms, but **does not yet provide empirical evidence** that they improve semantic accuracy, user trust, or organization quality.

Do not claim superior accuracy, reduced cost, privacy guarantees, robustness, or conference-level evaluation until the experiments in Section 14 are run.

## 2. Scope and implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Recursive filesystem tree and metadata inspection | Implemented | `tree`, `scan` commands |
| Filename-only ignore rules | Implemented | `.refactorignore`, `fnmatch` |
| Hosted image semantics | Implemented | Imagga upload + V3 tags/captions |
| Hosted folder selection and document classification | Implemented | Gemini REST calls with JSON-constrained prompts |
| Local image and document classification | Implemented | Ollama `/api/chat` |
| Hardware-aware local model recommendation | Implemented | CPU/RAM/NVIDIA probes and rule-based policy |
| Document support | Implemented | `.txt`, `.md`, `.pdf`, `.docx` |
| Safe execution controls | Partially implemented | dry run, cache validation, sanitization, collision handling; no interactive approval before non-dry-run moves |
| Automated tests / benchmark suite | Not found | No test files or test configuration found |
| Evaluation results | Not found | Existing sample cache shows classifications, not ground-truth metrics |

## 3. System architecture

```text
CLI command
  -> path validation + filename ignore rules
  -> recursive modality-specific discovery
  -> valid cached plan? ---- yes -> move/copy planner
             | no                         |
             v                            v
       selected backend              collision resolution
       hosted or local                    |
             |                            v
       semantic context / folder     file copy or rename
             |                            |
             +-- save source snapshot ----+-- save managed-category manifest
```

The source and output directory can be the same. In that case, prior category directories recorded in a manifest are excluded from future scans, preventing repeated reorganization of already managed content.

### Modules and responsibilities

| Module | Responsibility |
| --- | --- |
| `cli.py` | Typer command registration and workflow orchestration |
| `validation.py` | Directory existence, type, and read-access checks |
| `scanner.py`, `tree.py`, `metadata.py` | Baseline local inspection commands |
| `ignore.py` | Loads `.refactorignore`; matches names with `fnmatch` |
| `image_scanner.py` | Recursive discovery of supported image formats |
| `text.py` | Document discovery, extraction, categorization orchestration, text manifests |
| `imagga.py` | Hosted upload, tag/caption retrieval, image context structure |
| `gemini.py` | Hosted JSON-output folder selection and document categorization |
| `shim.py` | Common backend selection plus Ollama implementations |
| `hardware.py` | Local machine probing and recommendation policy |
| `setup.py`, `config.py` | Interactive configuration and credentials/config persistence |
| `plan_cache.py` | Snapshot serialization and exact cache validation |
| `organizer.py` | Move/copy planning, collision resolution, execution, image manifests |
| `context_store.py` | Legacy/general image-context JSON serialization |

## 4. User-facing interface

| Command | Function |
| --- | --- |
| `refactor version` | Prints installed distribution version via `importlib.metadata` |
| `refactor setup` | Configures hosted or local backend |
| `refactor tree [PATH]` | Displays a recursive text tree |
| `refactor scan [PATH]` | Prints name, extension, byte size, and directory flag |
| `refactor get-image-context PATH` | Produces image semantic context and category decisions |
| `refactor refactor-images PATH` | Categorizes images and executes/plans move or copy |
| `refactor refactor-text PATH` | Categorizes supported documents and executes/plans move or copy |
| `refactor now PATH` | Runs text workflow then image workflow |

Common options include `--output-dir`, `--dry-run`, `--move/--copy`, and (for images) `--min-confidence`. Runtime validation requires a readable source directory and an existing output directory.

## 5. Supported inputs and discovery

Image discovery accepts `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, and `.webp`, case-insensitively. Text discovery accepts `.txt`, `.md`, `.pdf`, and `.docx`.

Both modality-specific scanners use `Path.rglob("*")`. Ignore matching is only against `item.name`; therefore patterns cannot reliably express relative-path or directory rules. The repository’s current `.refactorignore` contains `*.txt`, so `.txt` files are skipped in runs launched from the repository root even though the text pipeline supports them.

## 6. Backend designs

### 6.1 Hosted backend: Imagga + Gemini

Setup asks for `IMAGGA_API_KEY`, `IMAGGA_API_SECRET`, and `GEMINI_API_KEY`. Secrets are persisted to `~/.refactor/.env`; an attempted `chmod(0o600)` follows writing on platforms that support it. Non-secret configuration is stored at `~/.refactor/config.json`.

For every discovered image, `ImaggaClient`:

1. uploads the bytes to Imagga V2 `/uploads`;
2. queries Imagga V3 `/tags` with `model=light` and `include_caption=true`;
3. flattens V3 grouped tags (while retaining compatibility with list-shaped results);
4. drops tags below a configurable confidence threshold (default 40.0), sorts descending, and retains at most 10;
5. creates an `ImageContext` containing absolute source path, remote upload id, tags, confidences, caption, and a provisional folder.

Gemini then receives the image filenames, retained tags, captions, and existing output-directory names. A temperature-zero prompt asks for JSON shaped as `{"folders":[{"id":0,"folder":"example"}]}` and requires one folder per input. The client rejects incomplete responses. Folder values are normalized to lower case and stripped to word characters, spaces, underscores, and hyphens before use.

For documents, Gemini receives an equivalent folder-selection prompt. PDFs up to 50 MiB are base64-encoded and sent as `application/pdf` inline data; the prompt states that the PDF is attached. For `.txt`, `.md`, and `.docx`, extracted text is inserted into the prompt. The configured default model string is `gemini-3.8-flash`; `GEMINI_MODEL` overrides it.

**Data boundary:** hosted image bytes go to Imagga. Hosted PDFs go to Gemini. Extracted text from hosted non-PDF documents is sent to Gemini. The project does not operate its own remote inference service, but these third-party transmissions must be disclosed in any study and assessed against provider terms and participant-consent requirements.

### 6.2 Local backend: Ollama

The local backend checks the Ollama server at `http://127.0.0.1:11434`, verifies the selected model by querying `/api/tags`, and invokes `/api/chat` with `stream: false` and `format: "json"`.

For images, the complete source file is base64-encoded and placed in the chat message’s `images` field. The model must return a caption, 1–5 lowercase tags, and a folder. Missing tags become `unclassified`; a missing caption receives a fallback message; and unsafe or empty folders are normalized/fallen back to the first tag. A second JSON-only call receives all per-image semantic contexts and existing folders to choose batch-consistent destinations.

For documents, `.txt` and `.md` are read with UTF-8 and replacement on errors; `.docx` is parsed directly from `word/document.xml`; PDFs use `pypdf.PdfReader`. Extracted text is truncated to 60,000 characters. The text is transmitted only to local Ollama according to the process design; actual locality depends on the user’s Ollama configuration and selected model.

### 6.3 Hardware recommendation policy

`detect_hardware()` reads CPU core count and physical memory through `os.sysconf`. NVIDIA presence is probed through `nvidia-smi -L`, `lspci`, `/proc/driver/nvidia/gpus`, or Windows WMIC; VRAM is queried from `nvidia-smi` where available. The current deterministic recommendation policy is:

| Condition | Model | Rationale encoded in implementation |
| --- | --- | --- |
| NVIDIA GPU and at least 8 GiB readable VRAM | `gemma3:4b` | multimodal instruction-following model |
| NVIDIA GPU but unavailable/low VRAM measurement | `gemma3:4b` | verifies the same supported-file model, subject to memory availability |
| No NVIDIA GPU, RAM >=16 GiB | `gemma3:4b` | multimodal model with sufficient document context |
| No NVIDIA GPU, RAM >=8 GiB | `gemma3:4b` | smallest recommended local option; CPU-only execution may be slow |
| Otherwise | `gemma3:4b` | no lightweight fallback is claimed reliable for all supported file types |

This is a heuristic policy, not a measured performance model. A paper should not imply the recommendations are hardware-optimal without latency, memory, and quality benchmarks.

## 7. Classification and folder-selection constraints

The system intentionally separates semantic inference from filesystem mutation. Hosted image tags/captions supply evidence, then a generative model chooses a broad reusable folder informed by current categories. In local image mode, a per-image model response is similarly followed by a batch folder-selection response. This two-stage design aims to improve cross-file consistency, but it introduces extra model calls and has not been compared with single-stage or rule-based baselines.

Folder sanitizers prevent slashes and most punctuation. They normalize whitespace to underscores and use `uncategorized` for empty results. This reduces path traversal risk from model output. The controls do not semantically validate whether a category is appropriate, and a malicious or malformed response can still produce an undesirable but syntactically safe directory.

## 8. Planning, execution, and cache validity

`plan_moves()` maps each classified context to:

```text
<output_dir>/<primary_folder>/<original_filename>
```

If a path exists—or has already been selected within the same plan—the planner appends `_1`, `_2`, and so on before the extension. `execute_moves()` creates destination parents, calls `shutil.copy2` for copy mode, or `Path.rename` for move mode, and continues after individual errors while counting successful and failed operations.

The CLI defaults to **move**, notwithstanding the older `organizer.py` module docstring and function default that describe copy as default. In the current command implementation, `move=True` and `copy=not move`; users must pass `--copy` to preserve originals. This discrepancy is documentation debt and a safety-relevant paper limitation.

### Plan cache format and behavior

Plans are saved as JSON in the source directory by default:

| Modality | Default plan file |
| --- | --- |
| Images | `.refactor_image_context.json` |
| Text | `.refactor_text_context.json` |

A plan records modality (`kind`), resolved source and output directories, a sorted source snapshot, and context items. Each snapshot element is:

```json
{"path":"/absolute/path","size":1234,"mtime_ns":1234567890}
```

Reuse requires exact equality of all fields and of the entire sorted snapshot. Consequently, added, removed, renamed, resized, or mtime-modified inputs cause reclassification. The cache does not include backend choice, model identifier, prompt version, confidence threshold, dependency version, hash of file content, or output-category state; these are threats to reproducibility and cache correctness.

`--dry-run` prints planned actions but still generates and saves a plan when a valid cache does not exist. A later normal invocation reuses that valid cache and executes it. It therefore avoids filesystem moves/copies but is not an inference-free preview.

## 9. Managed-category manifests

After a fully successful action, the tool writes a modality-specific manifest in the output root:

```json
{"folders":["category_a","category_b"]}
```

`managed_category_dirs()` and `managed_text_dirs()` read these manifests and exclude recorded directories only when the resolved source and output roots are the same. This makes repeated in-place runs avoid prior destinations. Manifests are not written after any partial failure, so a retry may rescan content already placed in successfully created folders during the partial run.

The supplied `testing-dir` includes a text plan that classifies `GATE2027-IB.pdf` as `exams` and `Hackloop S05.pdf` as `hackathons`, plus a text-category manifest containing those folders. This is an execution artifact, not ground truth and not a valid evaluation result.

## 10. Reproducibility and operational protocol

### Software environment

The package metadata declares Python `>=3.8` and dependencies: `typer`, `requests`, `python-dotenv`, and `pypdf`. Builds use `setuptools>=61.0` with `setuptools-scm`; the console script resolves to `refactor.cli:app`. Release automation builds and publishes on GitHub Release publication using PyPI Trusted Publishing.

The code uses modern built-in generic annotations such as `list[str]` and `set[Path]`, as well as union syntax (largely covered by postponed annotations). The declared Python 3.8 floor should be verified in CI rather than treated as established compatibility. At inspection, the host environment could compile the package but could not run its CLI because `typer` was absent from that active interpreter; this is an environment observation, not a package defect after normal dependency installation.

### Minimal execution protocol

```shell
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

refactor setup
refactor now ./incoming --output-dir ./organized --dry-run
refactor now ./incoming --output-dir ./organized
```

For a controlled experiment, record the operating system, Python version, package commit, all package versions, backend type, exact model identifier, model-server version, relevant environment variables excluding secrets, command line, input manifest, generated plan, output manifest, wall-clock time, number of requests, and any errors. Store a cryptographic hash for each input in addition to the current size/mtime snapshot.

## 11. Current repository evolution

| Date | Commit / milestone | Implementation effect |
| --- | --- | --- |
| 20 Apr 2026 | `5068567` | Initial repository |
| 20 Apr 2026 | `0ec0101` | `version` and `tree` commands |
| 13 Jun 2026 | `f633fdf` | Validation, ignore list, metadata |
| 21 Sep 2026 | `79429c9` | Image context and scanning |
| 5 Oct 2026 | `5ba9654` | Setup, hardware recommendation, backend shim |
| 11 Oct 2026 | `dc2b94b` / `28ba62e` | Gemini folder selection; release tag `v0.2.0` |
| 11 Oct 2026 | `d10da46` | Document categorization/organization |
| 12 Oct 2026 | `c384031` | Source-validated plans and dry-run reuse |

The working tree also contains uncommitted changes that add `pypdf`, extend local document support, revise the local model recommendation, and align documentation and CLI messages with the configured-backend abstraction. A formal artifact should either commit these changes or evaluate a clean tagged revision.

## 12. Security, privacy, and safety analysis

| Area | Existing control | Residual risk |
| --- | --- | --- |
| Credentials | Separate `.env`; attempted owner-only permission | Secrets still reside on disk; no OS keychain or rotation support |
| Model output paths | Folder-name sanitization | Safe names can still be semantically harmful or collide with user folders |
| Accidental overwrites | Numeric collision suffixes | No transaction, rollback, or pre-move confirmation |
| Destructive behavior | `--dry-run`; `--copy` | CLI defaults to moving and no interactive confirmation precedes execution |
| Cache reuse | Exact resolved paths, size, mtime snapshot | Does not bind plan to model/backend/prompt/category state or content hashes |
| Recursive scanning | Managed manifests exclude prior destinations in-place | Manifests are written only on all-success execution; symlink behavior is unexamined |
| Hosted privacy | Explicit external API design | Images/PDFs/text leave the machine; retention and regional processing are provider-dependent |
| Local privacy | Loopback Ollama endpoint | Locality depends on user runtime/model setup; logs and model provenance are not managed |

Potential conference studies involving personal files must obtain consent, avoid publishing sensitive file contents, redact filenames and captions, and document third-party provider data handling. The implementation itself has no telemetry-consent mechanism or data-retention controls.

## 13. Limitations and threats to validity

1. **No benchmark or ground truth:** semantic claims cannot be quantified from the repository artifacts.
2. **No automated tests:** behavior is not regression-protected; test coverage is unknown.
3. **Provider/model variability:** hosted endpoints and local models may change independently of the code.
4. **Prompt and model provenance:** prompts are versioned only implicitly in source; cache payloads omit them.
5. **Non-atomic execution:** exceptions are handled per file, allowing partial reorganization with no rollback.
6. **Name-only ignores:** users cannot express reliable path-based exclusions; ignore file discovery is relative to the process working directory, not the scanned directory.
7. **Mixed output categories:** text and images use separate manifests but both enumerate all existing output folders for model reuse; resulting modality boundaries may be unclear.
8. **Text extraction quality:** scanned PDFs, layouts, tables, embedded images, and DOCX elements may extract poorly or not at all.
9. **No quality-control interface:** the dry run displays planned paths but does not provide edit/approve/reject per item.
10. **Hardware policy is heuristic:** recommendations lack measured resource and accuracy validation.
11. **Move semantics:** `Path.rename` may fail across filesystems; behavior is not covered by fallback copy-and-delete logic.
12. **Time/cost accounting absent:** request count, token usage, rate limiting, retries, and latency are not instrumented.

## 14. Research-paper-ready evaluation plan

### Research questions

- **RQ1:** How accurately does Refactor.ai assign files to human-defined categories?
- **RQ2:** Does two-stage semantic extraction plus batch folder selection improve category consistency over direct single-stage categorization?
- **RQ3:** How do hosted and local backends compare in accuracy, latency, cost, and privacy exposure?
- **RQ4:** Do dry-run plans and safe execution mechanisms reduce unsafe or unwanted filesystem actions?

### Dataset protocol

Create a stratified, consented dataset containing images, text/Markdown, born-digital PDFs, scanned PDFs, and DOCX files. Separate development, validation, and held-out test directories by user/domain. Define a controlled taxonomy and allow an `other/uncategorized` option. At least two independent annotators should label intended categories; report agreement (for example Cohen’s kappa) and adjudication policy. Never use the included `testing-dir` alone as a benchmark.

### Baselines and ablations

| System | Purpose |
| --- | --- |
| Filename/extension rule baseline | Tests value beyond trivial cues |
| Top Imagga tag as folder | Tests Gemini batch folder-selection contribution |
| Single local-model call per image | Tests value of local batch consistency pass |
| Hosted two-stage pipeline | Main hosted condition |
| Local Ollama pipeline | Main private/local condition |
| Refactor.ai without existing-folder context | Tests reuse-context contribution |

### Metrics

Report macro/micro precision, recall, and F1 for a fixed taxonomy; top-k accuracy if suggestions are exposed; normalized mutual information or adjusted Rand index for clustering-style category consistency; percentage of safe executable paths; collision rate; partial-failure rate; dry-run-to-execution cache-reuse rate; files/hour; end-to-end latency; requests/file; cost/file; and human acceptance/edit/rejection rates. Use paired confidence intervals or bootstrap intervals and predefine exclusion criteria.

### Required artifacts

- Versioned source commit and dependency lockfile.
- Versioned prompts, backend/model identifiers, and API/runtime versions.
- De-identified input manifest with cryptographic hashes and ground-truth labels.
- Raw model outputs, sanitized outputs, plans, execution summaries, and error logs.
- Experiment scripts and fixed randomization/ordering policy.
- An ethics/privacy statement, data license, and participant consent protocol when applicable.

## 15. Recommended implementation work before submission

1. Add unit and integration tests for scans, ignores, sanitizers, cache invalidation, collisions, move/copy behavior, partial failures, and both backend adapters with mocked HTTP.
2. Add a mandatory confirmation or explicit `--yes` flag for move mode; make copy the CLI default or clearly version the behavior change.
3. Make execution transactional where possible: preflight every destination, log an operation journal, and provide rollback.
4. Add content hashes and backend/model/prompt/config fingerprints to plans.
5. Record structured metrics (latency, requests, cost estimates, errors, cache decisions) without collecting sensitive content by default.
6. Resolve source/output and ignore-file semantics; support path-aware exclusions and symlink policy.
7. Pin and validate supported Python versions in CI, especially the declared 3.8 baseline.
8. Add a review file or interactive approval flow for per-item category corrections and use the corrections as evaluation data—not silent training data.

## 16. References and implementation evidence

### Repository evidence

- [README](README.md)
- [Package configuration](pyproject.toml)
- [CLI orchestration](refactor/cli.py)
- [Backend abstraction and Ollama implementation](refactor/shim.py)
- [Hosted Imagga client](refactor/imagga.py)
- [Hosted Gemini client](refactor/gemini.py)
- [Document pipeline](refactor/text.py)
- [Plan-cache implementation](refactor/plan_cache.py)
- [Organization/execution implementation](refactor/organizer.py)
- [Configuration and setup](refactor/config.py) and [interactive setup](refactor/setup.py)
- [Hardware policy](refactor/hardware.py)
- [PyPI publication workflow](.github/workflows/publish.yml)
- [Sample text plan](testing-dir/.refactor_text_context.json) and [sample category manifest](testing-dir/.refactor_text_categories.json)

### External technical references used by the implementation

- [Python pathlib documentation](https://docs.python.org/3/library/pathlib.html)
- [Python fnmatch documentation](https://docs.python.org/3/library/fnmatch.html)
- [Typer documentation](https://typer.tiangolo.com/)
- [Requests documentation](https://requests.readthedocs.io/)
- [python-dotenv documentation](https://bbc2.github.io/python-dotenv/)
- [pypdf documentation](https://pypdf.readthedocs.io/)
- [setuptools documentation](https://setuptools.pypa.io/)
- [setuptools-scm documentation](https://setuptools-scm.readthedocs.io/)
- [Ollama API documentation](https://docs.ollama.com/api)
- [Google Gemini API documentation](https://ai.google.dev/gemini-api/docs)
- [Imagga API documentation](https://docs.imagga.com/)
