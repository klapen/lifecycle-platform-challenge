# Campaign Pipeline DAG
#
# Required Airflow Variables:
#   CAMPAIGN_BQ_PROJECT            GCP project ID
#   CAMPAIGN_BQ_DATASET            BigQuery dataset for audience staging tables
#   CAMPAIGN_BQ_REPORTING_TABLE    Fully-qualified reporting table (project.dataset.table)
#   CAMPAIGN_SLACK_WEBHOOK_URL     Slack incoming webhook URL (optional — alerts skipped if absent)
#   CAMPAIGN_SENT_LOG_DIR          Directory for dedup JSON files (default: /tmp/campaign_logs)
#   CAMPAIGN_HISTORICAL_WINDOW_DAYS  Days of history used in validation avg (default: 14)
#
# Required Airflow Connections:
#   google_cloud_default   GCP service account with BigQuery read/write access
#
# Schedule : daily at 05:00 UTC
# SLA      : must complete by 08:00 UTC (3-hour window, enforced on final task)
# Retries  : 2 per task, 5-minute delay
#
# Empty-audience behaviour: validate_audience raises AirflowSkipException —
# the DAG run is marked skipped (not failed) and a Slack info message is posted.
# Audience anomaly (>2× historical avg): AirflowFailException — pages oncall.
# Message content is managed as an ESP template keyed by campaign_id (Iterable).

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.decorators import dag

from lifecycle_platform_challenge.dags.tasks.build_audience import build_audience
from lifecycle_platform_challenge.dags.tasks.notify import log_results_and_notify
from lifecycle_platform_challenge.dags.tasks.send_campaign import execute_campaign_send_task
from lifecycle_platform_challenge.dags.tasks.validate_audience import validate_audience

CAMPAIGN_ID = "reactivation_sms"

default_args = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "owner": "lifecycle-platform",
}


@dag(
    dag_id="campaign_pipeline",
    schedule="0 5 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    default_args=default_args,
    tags=["campaign", "lifecycle"],
)
def campaign_pipeline() -> None:
    meta = build_audience(run_date="{{ ds }}", campaign_id=CAMPAIGN_ID)
    validated = validate_audience(meta)
    sent = execute_campaign_send_task(validated)
    log_results_and_notify(sent)


dag = campaign_pipeline()
