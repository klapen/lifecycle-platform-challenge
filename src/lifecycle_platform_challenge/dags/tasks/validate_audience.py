from __future__ import annotations

import requests
from airflow.decorators import task
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.models import Variable


def _post_slack(message: str) -> None:
    url = Variable.get("CAMPAIGN_SLACK_WEBHOOK_URL", default_var=None)
    if url:
        requests.post(url, json={"text": message}, timeout=10)


def _historical_avg(client, reporting_table: str, campaign_id: str, run_date: str, window_days: int) -> float:
    from google.cloud import bigquery

    sql = f"""
        SELECT AVG(audience_count) AS avg_count
        FROM `{reporting_table}`
        WHERE campaign_id = @campaign_id
          AND run_date >= DATE_SUB(@run_date, INTERVAL {window_days} DAY)
          AND status = 'success'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id),
            bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
        ]
    )
    row = next(client.query(sql, job_config=job_config).result())
    return float(row.avg_count or 0)


@task
def validate_audience(meta: dict) -> dict:
    from google.cloud import bigquery

    count = meta["audience_count"]
    campaign_id = meta["campaign_id"]
    run_date = meta["run_date"]

    # Empty audience is a valid outcome — skip downstream tasks cleanly.
    if count == 0:
        _post_slack(f":information_source: `{campaign_id}` skipped for {run_date}: no eligible audience.")
        raise AirflowSkipException("No eligible audience for this run_date — skipping send.")

    project = Variable.get("CAMPAIGN_BQ_PROJECT")
    reporting_table = Variable.get("CAMPAIGN_BQ_REPORTING_TABLE")
    window_days = int(Variable.get("CAMPAIGN_HISTORICAL_WINDOW_DAYS", default_var="14"))

    client = bigquery.Client(project=project)
    avg = _historical_avg(client, reporting_table, campaign_id, run_date, window_days)

    if avg > 0 and count > 2 * avg:
        _post_slack(
            f":x: `{campaign_id}` validation failed: "
            f"audience {count} exceeds 2× historical avg ({avg:.0f}) for {run_date}"
        )
        raise AirflowFailException(
            f"Audience {count} exceeds 2× historical average {avg:.0f} — possible data anomaly."
        )

    return meta
