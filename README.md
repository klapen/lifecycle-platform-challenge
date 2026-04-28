# lifecycle-platform-challenge

A production-oriented marketing campaign pipeline covering audience selection, reliable message delivery, Airflow orchestration, ML model integration, and observability.

---

## How to run locally

**Requirements:** Python 3.11+, [`uv`](https://github.com/astral-sh/uv)

```bash
# Install dependencies
uv sync

# Run the full test suite
uv run pytest

# Run a single test
uv run pytest tests/test_send.py::test_dedup_filters_already_sent
```

No Airflow or GCP credentials are needed to run the tests — the DAG tests use a minimal Airflow mock (`tests/airflow_mock.py`) that operates without installing `apache-airflow`.

---

## Repository structure

```
.
├── docs/                  # Exercise prompts and design inputs (read-only context)
│   ├── bigquery.md
│   ├── pipeline-orchestration.md
│   ├── airflow.md
│   ├── value-model.md
│   └── observability.md
├── output/                # Design-only deliverables (Parts 4 & 5)
│   ├── value-model-integration.md
│   └── observability.md
├── src/
│   └── lifecycle_platform_challenge/
│       ├── sql/
│       │   └── audience.sql          # Part 1: parameterized BigQuery audience query
│       ├── pipeline/
│       │   ├── send.py               # Part 2: execute_campaign_send()
│       │   ├── dedup.py              # Sent-log persistence
│       │   ├── esp.py                # ESP client stub
│       │   ├── response.py           # HTTP response classification
│       │   └── logger.py             # Structured batch logger
│       └── dags/
│           ├── campaign_dag.py       # Part 3: Airflow DAG wiring
│           └── tasks/
│               ├── build_audience.py
│               ├── validate_audience.py
│               ├── send_campaign.py
│               └── notify.py
├── tests/
│   ├── airflow_mock.py    # Minimal Airflow mock for structural DAG tests
│   ├── test_audience_sql.py
│   ├── test_send.py
│   ├── test_dedup.py
│   ├── test_response.py
│   └── test_dag.py
└── ai-session/            # Claude Code session export (see submission instructions)
```

---

## Assumptions made

- **`run_date` is the single time anchor** sourced from Airflow's `logical_date`. No `CURRENT_TIMESTAMP()` or `datetime.now()` anywhere — all time windows resolve against `run_date` in UTC.
- **Idempotency key is `campaign_id + renter_id`**, enforced client-side via a file-based `sent_renters.json`. The exercise acknowledges this is not production-safe for distributed workers (a BigQuery `MERGE` or Redis SET would replace it).
- **Audience is materialized once per `run_date`** to a BigQuery staging table. Downstream tasks read that snapshot — they do not re-run the query.
- **ESP provides no idempotency guarantees.** The pipeline implements its own dedup layer; an Iterable-like ESP is assumed.
- **ML model dependency is soft.** The bounded-waiting strategy (up to 60 min) prioritises operational reliability over targeting quality — the explicit tradeoff is: waiting too long risks the SLA, sending without scores wastes SMS volume, and not sending at all loses revenue.
- **Renters without a model score are excluded** from the ML-filtered audience (no fallback score assigned).
- **`validate_audience` is a hard gate** — `count == 0` raises `AirflowSkipException`, `count > 2× historical avg` raises `AirflowFailException`. Neither proceeds to send.

---

## Design decisions and tradeoffs

| Decision | Rationale | Tradeoff |
|---|---|---|
| Audience materialized to staging table | Downstream tasks see a stable snapshot; retries are safe | Extra BQ storage cost per run |
| XCom carries only metadata (not rows) | Keeps XCom small; audience rows stay in BQ | Requires an extra COUNT query in `build_audience` |
| File-based dedup (`sent_renters.json`) | Simple, no extra infrastructure | Not safe for distributed workers |
| Circuit breaker on consecutive batch failures | Stops wasting retries against a dead ESP | May abort a run that would have self-healed |
| ML as soft dependency with bounded waiting | Preserves SLA even if scoring job is late | May send unfiltered if scores never arrive |
| Per-batch persistence (not end-of-run) | Crash loses at most one in-flight batch | More disk I/O; more BQ writes |

---

## How it would differ with more time

- **Distributed dedup backend** — replace the file-based `sent_renters.json` with an atomic BigQuery `MERGE` or a Redis SET so the dedup layer is safe across multiple Airflow workers.
- **Provider-level idempotency keys** — pass a deterministic key (`campaign_id + renter_id + run_date`) to the ESP on each request to let the provider deduplicate on its side.
- **Smarter ML fallback** — instead of send-all or skip, introduce a "send to high-confidence-only" tier: apply a higher threshold when full scores aren't available rather than a binary send/skip.
- **Partitioned staging tables** — partition `audience_{campaign_id}` by `run_date` and add a retention policy rather than `CREATE OR REPLACE TABLE` each day.
- **Integration tests against real BigQuery** — the SQL tests today validate structure; a test with a real (or emulated) BQ instance would validate the query logic against actual data distributions.
- **Datadog DogStatsD instrumentation** — the observability design (Part 5) is currently spec-only; the actual `statsd.increment()` / `statsd.gauge()` calls would be added to each task.
- **Airflow `BigQueryTablePartitionExistenceSensor`** with `mode="reschedule"` as an alternative to the retry-loop freshness check, to release worker slots between polls.

---

## AI usage notes

- **`docs/` as AI reference material.** The files under `docs/` were written as structured inputs for the AI — problem statements, schemas, constraints, and design considerations — rather than as user-facing documentation. They also serve as a durable plan for future tuning: if a design decision needs to be revisited, the relevant `docs/` file is the starting point.

- **Per-step plan files to reduce token consumption.** `docs/plan/` contains one file per implementation step (e.g., `01-bigquery.md`, `02-send-pipeline.md`). Each file is self-contained so the AI only needs to load the context relevant to the current step, rather than the full project history. This significantly reduces token usage and keeps responses focused.

- **Cross-validated with ChatGPT.** Several design outputs (Parts 4 and 5) and the prompts used to generate them were cross-checked with ChatGPT — running the same questions in both tools and using the differences to surface gaps or weak assumptions. Prompt wording was also iteratively refined using ChatGPT to get clearer, more precise outputs from Claude Code.

---

## Parts overview

| Part | Type | Location |
|---|---|---|
| 1 — Audience SQL | Implemented | `src/lifecycle_platform_challenge/sql/audience.sql` |
| 2 — Send pipeline | Implemented | `src/lifecycle_platform_challenge/pipeline/` |
| 3 — Airflow DAG | Implemented | `src/lifecycle_platform_challenge/dags/` |
| 4 — ML integration | Design | `output/value-model-integration.md` |
| 5 — Observability | Design | `output/observability.md` |
