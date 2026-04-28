from __future__ import annotations

from datetime import timedelta

import requests
from airflow.decorators import task
from airflow.models import Variable


@task(sla=timedelta(hours=3))
def log_results_and_notify(meta: dict) -> None:
    from google.cloud import bigquery

    project = Variable.get("CAMPAIGN_BQ_PROJECT")
    reporting_table = Variable.get("CAMPAIGN_BQ_REPORTING_TABLE")

    client = bigquery.Client(project=project)
    errors = client.insert_rows_json(reporting_table, [{
        "campaign_id": meta["campaign_id"],
        "run_date": meta["run_date"],
        "audience_count": meta["audience_count"],
        "total_sent": meta.get("total_sent", 0),
        "total_failed": meta.get("total_failed", 0),
        "total_skipped": meta.get("total_skipped", 0),
        "elapsed_seconds": meta.get("elapsed_seconds", 0.0),
        "dag_run_id": meta.get("dag_run_id", ""),
        "status": "success",
    }])
    if errors:
        raise RuntimeError(f"Reporting insert failed: {errors}")

    url = Variable.get("CAMPAIGN_SLACK_WEBHOOK_URL", default_var=None)
    if url:
        text = (
            f":white_check_mark: `{meta['campaign_id']}` completed for {meta['run_date']}\n"
            f"Audience: {meta['audience_count']} | "
            f"Sent: {meta.get('total_sent', 0)} | "
            f"Failed: {meta.get('total_failed', 0)} | "
            f"Skipped: {meta.get('total_skipped', 0)}"
        )
        requests.post(url, json={"text": text}, timeout=10)
