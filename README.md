# Campaign Pipeline — System Design Overview

This repository contains a **system design for a production-ready marketing campaign pipeline**, focused on:

- Data-driven audience selection
- Reliable pipeline orchestration
- Safe message delivery
- Integration with predictive models
- Observability and operational robustness

The goal is to demonstrate how to design a **deterministic, idempotent, and scalable pipeline** that integrates data engineering, backend systems, and ML outputs.

---

## System Overview

The system is composed of the following logical components:

1. **BigQuery Layer**
   - Defines the campaign audience
   - Applies business rules and filters
   - Integrates predictive model scores

2. **Airflow DAG**
   - Orchestrates the end-to-end pipeline
   - Manages dependencies, retries, and scheduling
   - Ensures deterministic execution

3. **Pipeline Orchestration Layer**
   - Handles batching, retries, and rate limiting
   - Ensures idempotent message delivery
   - Integrates with external messaging providers

4. **Value Model Integration**
   - Filters audience using ML predictions
   - Supports multiple models and configurable thresholds
   - Handles model availability and freshness

5. **Observability Layer**
   - Tracks execution metrics and outcomes
   - Provides logging and alerting
   - Enables debugging and auditing

---

## Repository Structure

```
.
├── docs
│   ├── airflow.md
│   ├── bigquery.md
│   ├── observability.md
│   ├── pipeline-orchestration.md
│   └── value-model.md
└── README.md
```

Each document contains:
- The original problem context
- Design assumptions
- Key decisions
- Tradeoffs and limitations

---

## Design Principles

### Determinism
- All executions are based on a fixed `run_date`
- Results must be reproducible across retries and reruns

---

### Idempotency
- No user should receive the same campaign twice
- All side effects (e.g., message sends) are protected against duplication

---

### Separation of Concerns
- BigQuery → data processing
- Airflow → orchestration
- Python modules → external integrations

---

### Materialization Over Recalculation
- Intermediate results (audience) are persisted
- Downstream steps operate on stable snapshots

---

### Resilience
- Supports retries, partial failures, and rate limiting
- Ensures forward progress even under failure conditions

---

### Configurability
- Campaign parameters (thresholds, models, batching) are configurable
- Avoids hardcoded logic to support future extensions

---

### Scalability
- Designed to handle large datasets efficiently
- Uses BigQuery for heavy computation and filtering

---

## Key Challenges Addressed

- Ensuring **consistent audience selection** despite changing data
- Handling **external API limitations** (rate limits, retries, failures)
- Preventing **duplicate message delivery**
- Managing **dependencies between data pipelines (ML → campaign)**
- Balancing **business tradeoffs** (accuracy vs timeliness)
- Supporting **future extensibility** (multiple models, segments)

---

## Business Context

The system is designed for **campaign-based user engagement**, where:

- Targeting accuracy directly impacts ROI
- Timing is critical (daily scheduled campaigns)
- External providers introduce uncertainty
- Data and ML pipelines must be coordinated

---

## How to Use This Repository

- Start with `docs/bigquery.md` to understand audience definition
- Continue with `docs/pipeline-orchestration.md` for delivery logic
- Review `docs/airflow.md` for orchestration design
- Explore `docs/value-model.md` for ML integration
- Finish with `docs/observability.md` for monitoring and reliability

---

## Scope & Limitations

This design intentionally simplifies certain aspects for clarity:

- File-based deduplication instead of distributed storage
- No transactional guarantees between send and logging
- No provider-level idempotency keys
- Simplified ML pipeline dependency handling

These are acknowledged tradeoffs for the purpose of the exercise and would be addressed in a production system.

---

## Final Note

This repository focuses on **how to think about building reliable systems**, not just how to implement them.

The emphasis is on:
- making assumptions explicit
- designing for failure
- balancing technical and business constraints
```
