import inspect
import sys
from datetime import timedelta

import tests.airflow_mock as airflow_mock

# Must run before campaign_dag (and its task imports) are loaded.
airflow_mock.install()

from lifecycle_platform_challenge.dags.campaign_dag import dag  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dag_id():
    assert dag.dag_id == "campaign_pipeline"


def test_dag_schedule():
    assert dag.schedule_interval == "0 5 * * *"


def test_default_args_retries():
    assert dag.default_args["retries"] == 2


def test_default_args_retry_delay():
    assert dag.default_args["retry_delay"] == timedelta(minutes=5)


def test_catchup_disabled():
    assert dag.catchup is False


def test_linear_task_dependencies():
    task_ids = [t.task_id for t in dag.topological_sort()]
    assert task_ids == [
        "build_audience",
        "validate_audience",
        "execute_campaign_send_task",
        "log_results_and_notify",
    ]


def test_sla_on_final_task():
    final = dag.get_task("log_results_and_notify")
    assert final.sla == timedelta(hours=3)


def test_no_audience_rows_in_task_signatures():
    for task_id in ("validate_audience", "execute_campaign_send_task"):
        fn = dag.get_task(task_id).python_callable
        for name, param in inspect.signature(fn).parameters.items():
            assert param.annotation is not list, (
                f"{task_id}.{name} is annotated list — audience rows must not pass via XCom"
            )
