# AGENTS.md

## Scope

- This repository currently contains one skill package: `confluence-curation/`.
- Main authored files are `confluence-curation/SKILL.md`, `confluence-curation/agents/openai.yaml`, `confluence-curation/scripts/fetch_confluence.py`, `confluence-curation/scripts/curate_confluence.py`, and the planning references under `confluence-curation/references/`.
- The Python code is stdlib-only; there is no `pyproject.toml`, `requirements.txt`, `package.json`, or Makefile on the current `main` branch.
- There is no checked-in test suite yet, so validation is mostly smoke testing and syntax checking.

## Rule Files

- No `.cursorrules` file was found.
- No files were found under `.cursor/rules/`.
- No `.github/copilot-instructions.md` file was found.
- If any of those files are added later, treat them as higher-priority repo instructions and update this file.

## Repository Shape

- `confluence-curation/SKILL.md` defines the skill contract, workflow, and output expectations.
- `confluence-curation/agents/openai.yaml` contains the agent-facing metadata and default prompt.
- `confluence-curation/scripts/fetch_confluence.py` is the networked data collection CLI.
- `confluence-curation/scripts/curate_confluence.py` is the offline scoring and Markdown report generator.
- `confluence-curation/references/` contains prompt, scoring, architecture, and review references, not executable code.
- `confluence-curation/scripts/__pycache__/` is generated output and should not be edited by hand.

## Runtime Assumptions

- Target Python is modern 3.x and code already uses `from __future__ import annotations`.
- Scripts are designed to run directly with `python` or `python3`.
- The code assumes UTF-8 for JSON and Markdown output.
- User-facing output intentionally includes Korean text; preserve that behavior unless requirements change.

## Build Commands

- There is no formal build pipeline today.
- Fast syntax build-equivalent for both scripts:
  ```bash
  python -m py_compile confluence-curation/scripts/fetch_confluence.py confluence-curation/scripts/curate_confluence.py
  ```
- Whole-tree bytecode compilation:
  ```bash
  python -m compileall confluence-curation
  ```
- CLI contract check for the fetcher:
  ```bash
  python confluence-curation/scripts/fetch_confluence.py --help
  ```
- CLI contract check for the curator:
  ```bash
  python confluence-curation/scripts/curate_confluence.py --help
  ```

## Lint Commands

- No linter is configured in-repo today.
- Minimum safe validation is syntax compilation via `py_compile`.
- If you have local tooling installed, `ruff check confluence-curation` is the closest fit to the current style, but it is not yet a repository requirement.
- If you have local formatting tooling installed, `black confluence-curation` should be treated as optional and only used if the resulting diff matches the existing style.

## Test Commands

- No automated tests are checked in on the current branch.
- Use targeted smoke tests instead of inventing a fake test harness.
- Smoke test fetcher argument validation:
  ```bash
  python confluence-curation/scripts/fetch_confluence.py --help
  ```
- Smoke test curator argument validation:
  ```bash
  python confluence-curation/scripts/curate_confluence.py --help
  ```
- Syntax-check a single file:
  ```bash
  python -m py_compile confluence-curation/scripts/fetch_confluence.py
  ```
  ```bash
  python -m py_compile confluence-curation/scripts/curate_confluence.py
  ```
- End-to-end manual test pattern:
  1. Run `fetch_confluence.py` with a small scope and `--output tmp/fetch.json`.
  2. For the legacy flow, run `curate_confluence.py --input tmp/fetch.json --output tmp/report.md`.
  3. For the staged insight flow, run `normalize_confluence.py`, `cluster_confluence.py`, `extract_evidence.py`, `synthesize_insights.py`, `review_insights.py`, then `curate_confluence.py --insights-input ... --review-input ...`.
  4. Inspect the JSON and Markdown for schema and content regressions.

## Running A Single Test

- There is no single-test command in the repo because there is no checked-in unit test suite.
- For a single-file validation, use `python -m py_compile <file>`.
- For a single behavior check, run the specific script with the smallest relevant CLI invocation.
- If a pytest suite is added later, prefer `python -m pytest path/to/test_file.py::test_name`.

## Imports

- Keep imports at the top of the file.
- Group imports by standard library first; there are currently no third-party imports.
- Within a group, keep imports stable and roughly alphabetical.
- Prefer explicit imports from `typing`, `dataclasses`, `datetime`, and `urllib` modules rather than wildcard imports.
- Avoid lazy imports unless they materially reduce startup cost or break import cycles.

## Formatting

- Follow PEP 8 style with readable line lengths; the existing files lean toward Black-compatible formatting without requiring Black.
- Use 4-space indentation.
- Preserve a single blank line between logically related helper blocks and two blank lines between top-level definitions.
- Keep long conditionals and function calls vertically aligned for readability.
- Prefer trailing commas in multiline literals and call sites when it improves diffs.
- End text and JSON files with a newline.

## Types

- Keep `from __future__ import annotations` at the top of Python files.
- Maintain type hints on public helpers and all non-trivial internal helpers.
- The existing style uses `Dict[str, Any]`, `List[...]`, `Optional[...]`, and `Tuple[...]`; follow that unless you are refactoring broadly.
- Use `argparse.Namespace` for parsed CLI arguments.
- Return structured tuples when a helper naturally yields both scores and evidence.
- Introduce `dataclass`es only when they simplify a real data shape; `AuthConfig` is the current example.

## Naming

- Use `snake_case` for functions, variables, and module-level helpers.
- Use `PascalCase` for classes and dataclasses.
- Use `UPPER_SNAKE_CASE` for constants such as `MAX_RPS`, `VERSION_LIMIT`, and status maps.
- Prefer descriptive names over abbreviated names, especially in scoring and normalization code.
- Name CLI entrypoints `main()` and exit through `raise SystemExit(main())`.

## Function Design

- Keep helpers focused and composable.
- Separate pure scoring or transformation logic from I/O whenever practical.
- Prefer passing explicit values into helpers rather than relying on hidden module state.
- Return evidence alongside computed scores when downstream reporting needs traceability.
- Preserve current behavior where report-building functions assemble lists of lines and join once at the end.

## Error Handling

- Fail fast on invalid CLI input with `argparse` validation.
- Use custom exceptions for domain-specific failures; `FetchError` is the existing pattern.
- Convert top-level operational failures into a clean stderr message and exit code `1`.
- Retry transient HTTP failures for statuses `429`, `500`, `502`, `503`, and `504`.
- Prefer recording partial-data issues in `warnings` when the run can still produce useful output.
- Do not silently swallow network or parsing failures unless the fallback path is explicit.

## I/O And Data Handling

- Read and write JSON with `encoding="utf-8"`, `ensure_ascii=False`, and `indent=2`.
- Create parent directories before writing outputs.
- Preserve the current cache-file pattern and avoid breaking cache key stability without reason.
- Treat API rate limiting as a hard product rule; do not exceed one request per second.
- Keep body text cleanup conservative; avoid over-processing content fetched from Confluence.

## Dependencies And Architecture

- Prefer the Python standard library unless a new dependency is clearly justified.
- Keep the fetch script network-aware and the curate script offline and deterministic.
- Do not move skill-definition content into the Python scripts unless the repo intentionally consolidates formats.
- Keep agent metadata, references, and executable scripts separated by responsibility.

## Content And Domain Rules

- Preserve the repo's distinction between freshness, trust, and uncertainty.
- Do not rewrite Korean output requirements into English unless the skill contract changes.
- When evidence conflicts, surface the conflict instead of collapsing it into a false certainty.
- Keep trust scoring heuristic and explainable, not overly clever.
- Preserve the instruction that higher job title is only a hint, not proof of correctness.

## Change Discipline

- Update `SKILL.md`, `openai.yaml`, and script behavior together when the user-facing contract changes.
- If you add tests or lint config, also update this `AGENTS.md` with the exact commands.
- Do not edit generated `__pycache__` files.
- Prefer small, reviewable diffs over wide stylistic rewrites.
