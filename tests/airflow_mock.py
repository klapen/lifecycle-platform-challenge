"""
Minimal Airflow mock for structural DAG tests.

Implements just enough of the TaskFlow API to let campaign_dag.py be imported
and its task graph inspected without installing apache-airflow.

Usage — call install() before importing any airflow-dependent module:

    import tests.airflow_mock as airflow_mock
    airflow_mock.install()
"""

import sys
from types import ModuleType


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AirflowFailException(Exception):
    pass


class AirflowSkipException(Exception):
    pass


# ---------------------------------------------------------------------------
# Variable stub
# ---------------------------------------------------------------------------

class Variable:
    @staticmethod
    def get(key, default_var=None):
        return default_var


# ---------------------------------------------------------------------------
# Task graph primitives
# ---------------------------------------------------------------------------

class _MockTask:
    def __init__(self, fn, sla=None):
        self.task_id = fn.__name__
        self.python_callable = fn
        self.sla = sla
        self.upstream_task_ids: set[str] = set()


class _XComRef:
    """Returned when a task is called inside a DAG; carries the source task_id."""
    def __init__(self, task_id: str):
        self.source_task_id = task_id


class _TaskFactory:
    """Produced by @task. Registers a _MockTask with the active DAG on __call__."""

    def __init__(self, fn, sla=None):
        self._fn = fn
        self._sla = sla

    def __call__(self, *args, **kwargs):
        mock_task = _MockTask(self._fn, sla=self._sla)
        for arg in list(args) + list(kwargs.values()):
            if isinstance(arg, _XComRef):
                mock_task.upstream_task_ids.add(arg.source_task_id)
        if _active_dag is not None:
            _active_dag._tasks[mock_task.task_id] = mock_task
        return _XComRef(mock_task.task_id)


# ---------------------------------------------------------------------------
# DAG mock
# ---------------------------------------------------------------------------

_active_dag: "_MockDAG | None" = None


class _MockDAG:
    def __init__(self, dag_id, schedule, default_args, catchup=True, **kwargs):
        self.dag_id = dag_id
        self.schedule_interval = schedule
        self.default_args = default_args
        self.catchup = catchup
        self._tasks: dict[str, _MockTask] = {}

    def get_task(self, task_id: str) -> _MockTask:
        return self._tasks[task_id]

    def topological_sort(self) -> list[_MockTask]:
        """Kahn's algorithm; preserves insertion order for equal-priority tasks."""
        tasks = list(self._tasks.values())
        in_degree = {t.task_id: len(t.upstream_task_ids) for t in tasks}
        queue = [t for t in tasks if in_degree[t.task_id] == 0]
        result = []
        while queue:
            current = queue.pop(0)
            result.append(current)
            for other in tasks:
                if current.task_id in other.upstream_task_ids:
                    in_degree[other.task_id] -= 1
                    if in_degree[other.task_id] == 0:
                        queue.append(other)
        return result


# ---------------------------------------------------------------------------
# @task and @dag decorators
# ---------------------------------------------------------------------------

def task(fn=None, **kwargs):
    if fn is None:
        def decorator(fn):
            return _TaskFactory(fn, sla=kwargs.get("sla"))
        return decorator
    return _TaskFactory(fn)


def dag(**dag_kwargs):
    def decorator(fn):
        def wrapper():
            global _active_dag
            mock_dag = _MockDAG(**dag_kwargs)
            _active_dag = mock_dag
            try:
                fn()
            finally:
                _active_dag = None
            return mock_dag
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# sys.modules injection
# ---------------------------------------------------------------------------

def _make_module(name: str, **attrs) -> ModuleType:
    m = ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def install() -> None:
    """Inject mock airflow packages into sys.modules.

    Must be called before any import that transitively imports airflow.
    Evicts previously cached DAG modules so they re-import with the mock.
    """
    _make_module("airflow")
    _make_module("airflow.decorators", task=task, dag=dag)
    _make_module("airflow.exceptions",
                 AirflowFailException=AirflowFailException,
                 AirflowSkipException=AirflowSkipException)
    _make_module("airflow.models", Variable=Variable)

    for key in list(sys.modules):
        if "lifecycle_platform_challenge.dags" in key:
            del sys.modules[key]
