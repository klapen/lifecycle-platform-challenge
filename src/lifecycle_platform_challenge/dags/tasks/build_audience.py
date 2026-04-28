from __future__ import annotations

from pathlib import Path

from airflow.decorators import task
from airflow.models import Variable

_SQL_PATH = Path(__file__).parent.parent.parent / "sql" / "audience.sql"


def _staging_table(project: str, dataset: str, campaign_id: str, run_date: str) -> str:
    compact = run_date.replace("-", "")
    return f"{project}.{dataset}.audience_{campaign_id}_{compact}"


@task
def build_audience(run_date: str, campaign_id: str) -> dict:
    from google.cloud import bigquery

    project = Variable.get("CAMPAIGN_BQ_PROJECT")
    dataset = Variable.get("CAMPAIGN_BQ_DATASET")
    staging_table = _staging_table(project, dataset, campaign_id, run_date)

    audience_sql = _SQL_PATH.read_text()
    materialization_sql = (
        f"CREATE OR REPLACE TABLE `{staging_table}` AS ({audience_sql})"
    )

    client = bigquery.Client(project=project)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_date", "DATE", run_date)]
    )
    client.query(materialization_sql, job_config=job_config).result()

    count_row = next(client.query(f"SELECT COUNT(*) AS cnt FROM `{staging_table}`").result())

    return {
        "campaign_id": campaign_id,
        "run_date": run_date,
        "staging_table": staging_table,
        "audience_count": count_row.cnt,
    }
