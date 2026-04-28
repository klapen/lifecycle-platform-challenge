# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

A marketing campaign pipeline built as a system-design exercise. Three parts are implemented in code (BigQuery audience query, Python send pipeline, Airflow DAG); two are design-only (ML model integration, observability).

## Layout

- `docs/` — **inputs for AI**: original exercise prompts, schemas, requirements, and prior design notes. Treat as read-only context unless the user explicitly asks for edits.
- `output/` — **design-document outputs**: written deliverables for the design-only parts (Part 4 ML integration, Part 5 observability) and any other design write-ups.
- `src/` — all implementation code (Python modules, SQL, DAGs).
- `tests/` — pytest suite.

The reading order for `docs/` is encoded in `README.md` ("How to Use This Repository") and is not alphabetical.

## Tooling

- **Python deps:** `uv` — `uv add <pkg>` (not `pip install`), `uv run <cmd>` to execute inside the project env, `uv sync` to install from lockfile.
- **Tests:** `pytest` via `uv run pytest`. Single test: `uv run pytest tests/path/to/test_file.py::test_name`.

## Cross-Cutting Invariants

These constraints recur across the SQL, Python, and DAG code — changing one usually requires updating the others and the corresponding `docs/` file. If a request would break one, flag it before editing.

- **`run_date` is the single time anchor.** Sourced from Airflow's `logical_date`. No `CURRENT_TIMESTAMP()`, no `datetime.now()`. All time windows ("past 30 days", "past 90 days", `dnd_until` checks) resolve against `run_date` in UTC.
- **Idempotency key is `campaign_id + renter_id`**, enforced client-side. The assumed Iterable-like ESP provides no idempotency guarantees. The exercise uses a file-based `sent_renters.json`; explicitly acknowledged as not production-safe.
- **Audience is materialized once per `run_date`** to a staging table. Downstream tasks read the snapshot — they do not re-run the query.
- **Pipeline stages are linear:** `build_audience → validate_audience → execute_campaign_send → log_results_and_notify`. SLA: 5:00 AM UTC start, 8:00 AM UTC completion. Retries: 2 per task, 5-minute delay.
- **ESP batch cap is 100 recipients.** Rate-limit handling is exponential backoff with jitter, max 5 retries per batch, respecting `Retry-After` if present.
- **Validation gate before send:** `audience_count > 0` AND `audience_count <= 2× historical average`. Failure stops the pipeline and notifies — does not proceed to send.
- **ML score dependency is *soft* with bounded waiting** (30–60 min), not a hard block. The business tradeoff (wasted SMS volume vs. lost revenue) is the rationale — preserve it when editing Part 4.

## Code Style

- **One file per concern.** Split modules by single responsibility — logger, HTTP response handling, persistence, orchestration each get their own file. Do not consolidate into one large module even when the total line count is small. Propose the split upfront.
- **Parametrize tests when applicable.** Use `@pytest.mark.parametrize` whenever a test covers the same logic across multiple inputs (e.g. status codes, retryable vs non-retryable cases, boundary values). Prefer parametrized tests over duplicated test functions.

## Editing Conventions for `output/`

- Mirror the structure of `docs/` files: original problem statement verbatim at the top, followed by a numbered assumptions/design-decisions section (`### 1. Title`, `### 2. Title`, ...) separated by `---` rules.
- Keep design docs aligned with the cross-cutting invariants above.
