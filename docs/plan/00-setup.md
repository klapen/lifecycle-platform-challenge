# Step 0 — Project Setup

## Goal

Initialize a `uv`-managed Python project with the directory skeleton, dependencies, and pytest configuration needed for Steps 1–3.

## Source doc

None — this step is infrastructure. Layout and tooling are mandated by `/CLAUDE.md`.

## Key constraints

- Python deps managed with `uv` (not `pip` directly)
- Code lives under `src/`, tests under `tests/`, design outputs under `output/`
- Pytest is the test runner, invoked via `uv run pytest`
- Keep dependencies minimal — only what each implementation step actually imports

## Files to create

```
pyproject.toml                  # uv-managed, src layout
.python-version                 # pinned via uv (e.g. 3.12)
.gitignore                      # __pycache__, .venv, .pytest_cache, *.pyc, sent_renters.json
src/__init__.py                 # not required for src layout, omit if not needed
src/sql/.gitkeep                # placeholder for Step 1
src/pipeline/__init__.py
src/dags/__init__.py
tests/__init__.py
tests/conftest.py               # shared fixtures (created empty for now)
```

`uv.lock` will be generated automatically.

## Implementation steps

1. Run `uv init --python 3.12 --package` (or `uv init` then adjust) at repo root. Confirm it produces `pyproject.toml` and `.python-version` without overwriting `README.md` or existing files.
2. Configure `pyproject.toml`:
   - `[project]` name `lifecycle-platform-challenge`, version `0.1.0`
   - `requires-python = ">=3.12"`
   - `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `pythonpath = ["src"]`
3. Add runtime dependencies via `uv add`:
   - `requests` (used by Step 2 for HTTP semantics around the ESPClient interface)
   - Note: `google-cloud-bigquery` is **not** added in Step 0 — Step 1 is SQL-only and runs offline; add it only if a future step needs to execute queries from Python.
   - Note: `apache-airflow` is **not** added in Step 0 — it has heavy transitive deps. Step 3 will decide whether to add it as a dev/optional extra or stub the imports for unit tests.
4. Add dev dependencies via `uv add --dev`:
   - `pytest`
   - `pytest-mock`
5. Create `src/{sql,pipeline,dags}/` and `tests/` with `__init__.py` files where needed (`src/sql/` uses `.gitkeep` since it holds SQL, not Python).
6. Write `.gitignore` covering Python artifacts and `sent_renters.json` (the dedup file is runtime state, never committed).
7. Run `uv sync` to materialize the venv and lockfile.
8. Run `uv run pytest --collect-only` to verify pytest discovers the empty `tests/` directory cleanly.

## Tests

No application tests in this step. Verification is:
- `uv run pytest --collect-only` exits 0 with "no tests collected" or similar
- `uv run python -c "import pipeline, dags"` succeeds (smoke test for src layout)

## Done when

- `pyproject.toml`, `.python-version`, `uv.lock`, `.gitignore` exist
- `src/{sql,pipeline,dags}/` and `tests/` directories exist and are reachable from pytest
- `uv sync` succeeds with no errors
- `uv run pytest` runs (zero tests, zero failures)

## Commit checkpoint

Before committing: show `git status` and `git diff` to the user. Wait for explicit approval. Suggested commit message:

```
chore: initialize uv project skeleton (src layout, pytest)
```

The first commit also includes `docs/plan/*` and any `CLAUDE.md` updates that landed in the planning phase — bundle them in this commit unless the user prefers to split.
