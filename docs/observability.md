# Part 5 — Observability Design (Written)

In 1–2 paragraphs per question, describe:

1. **What Datadog metrics and alerts would you set up** for this pipeline? Think about: DAG latency, audience size anomalies, ESP error rates, send completion rates.
2. **How would you detect and prevent double-sends** if the pipeline runs twice due to an Airflow retry or manual re-trigger?
3. **What happens if the ESP goes down mid-send?** Describe your circuit-breaker or recovery strategy.
