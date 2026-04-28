from __future__ import annotations

from airflow.decorators import task
from airflow.models import Variable


@task
def execute_campaign_send_task(meta: dict) -> dict:
    from google.cloud import bigquery

    from lifecycle_platform_challenge.pipeline.esp import ESPClient
    from lifecycle_platform_challenge.pipeline.send import execute_campaign_send

    project = Variable.get("CAMPAIGN_BQ_PROJECT")
    sent_log_dir = Variable.get("CAMPAIGN_SENT_LOG_DIR", default_var="/tmp/campaign_logs")

    client = bigquery.Client(project=project)
    rows = client.query(
        f"SELECT renter_id, phone FROM `{meta['staging_table']}`"
    ).result()
    audience = [{"renter_id": row.renter_id, "phone": row.phone} for row in rows]

    # Deterministic path: retries within the same run_date resume from prior progress.
    sent_log_path = f"{sent_log_dir}/{meta['campaign_id']}_{meta['run_date']}.json"

    metrics = execute_campaign_send(
        campaign_id=meta["campaign_id"],
        audience=audience,
        esp_client=ESPClient(),
        sent_log_path=sent_log_path,
    )

    return {**meta, **metrics}
