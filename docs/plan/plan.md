# Master Plan — Campaign Pipeline Implementation

## Overview

Implement a daily marketing campaign pipeline that selects an audience in BigQuery, sends SMS via an Iterable-like ESP through a Python module, and orchestrates the flow with Airflow. Two additional parts are design-only deliverables (ML model integration and observability). The work is split into six steps; each has a self-contained plan file in this directory and is loaded individually when executing that step.

## Conventions

Layout, tooling, and cross-cutting invariants are defined in `/CLAUDE.md` at the repo root. Per-step files reference it rather than duplicating its contents. The most load-bearing invariants:

- `run_date` is the single time anchor (no `CURRENT_TIMESTAMP()` / `datetime.now()`)
- Idempotency key: `campaign_id + renter_id`
- Audience materialized once per `run_date`; downstream reads the snapshot
- ESP batch cap: 100; backoff: exponential + jitter, max 5 retries
- Validation gate: `count > 0` AND `count <= 2× historical_avg`
- ML score dependency is *soft* with bounded waiting

## Workflow

1. **One commit per step.** Each step (00–05) ends in its own commit. No bulk commits, no merging steps.
2. **User-validation gate before every commit.** When a step's code is ready, show a diff/summary and wait for explicit approval. Never commit silently.
3. **Load one step at a time.** Future sessions should load only the active step's plan file plus this master and `CLAUDE.md` — not all step files at once.
4. **Update the source `docs/` doc when an invariant or assumption changes** during implementation. The source docs and code stay in sync.

## Step Index

| Step | Plan file | Source doc | Output |
| --- | --- | --- | --- |
| 0 | [00-setup.md](00-setup.md) | — | `pyproject.toml`, `src/{sql,pipeline,dags}/`, `tests/` skeleton |
| 1 | [01-bigquery.md](01-bigquery.md) | [../bigquery.md](../bigquery.md) | `src/sql/audience.sql`, `tests/test_audience_sql.py` |
| 2 | [02-send-pipeline.md](02-send-pipeline.md) | [../pipeline-orchestration.md](../pipeline-orchestration.md) | `src/pipeline/send.py`, `tests/test_send.py` |
| 3 | [03-airflow-dag.md](03-airflow-dag.md) | [../airflow.md](../airflow.md) | `src/dags/campaign_dag.py`, `tests/test_dag.py` |
| 4 | [04-value-model.md](04-value-model.md) | [../value-model.md](../value-model.md) | `output/value-model.md` (design) |
| 5 | [05-observability.md](05-observability.md) | [../observability.md](../observability.md) | `output/observability.md` (design) |

## Per-step file structure

Every step file (00–05) follows the same shape so a fresh session can pick it up cold:

1. **Goal** — one sentence
2. **Source doc** — link to corresponding `docs/*.md`
3. **Key constraints from source** — the assumptions that drive implementation choices
4. **Files to create / modify** — explicit paths
5. **Implementation steps** — numbered checklist
6. **Tests** — pytest coverage (or "design-only — no tests")
7. **Done when** — exit criteria
8. **Commit checkpoint** — reminder to request user approval before committing
