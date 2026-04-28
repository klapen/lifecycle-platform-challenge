import re
from pathlib import Path

SQL_PATH = Path(__file__).parent.parent / "src" / "lifecycle_platform_challenge" / "sql" / "audience.sql"


def _sql() -> str:
    return SQL_PATH.read_text()


def test_no_dynamic_now():
    # Strip single-line comments before checking so header documentation
    # mentioning these functions doesn't cause a false positive.
    sql_no_comments = re.sub(r"--[^\n]*", "", _sql()).upper()
    assert "CURRENT_TIMESTAMP" not in sql_no_comments
    assert "CURRENT_DATE" not in sql_no_comments


def test_uses_run_date_parameter():
    assert "@run_date" in _sql()


def test_expected_output_columns():
    sql = _sql()
    # Strip CTE block, then find the final SELECT list up to the first FROM.
    # Match the SELECT after the closing parenthesis of the last CTE.
    final_select = re.search(r"\)\s*\n(SELECT.*?)FROM", sql, re.DOTALL | re.IGNORECASE)
    assert final_select, "Could not locate final SELECT block"
    select_block = final_select.group(1)
    for column in ("renter_id", "email", "phone", "last_login", "search_count", "days_since_login"):
        assert column in select_block, f"Expected output column '{column}' not found in final SELECT"


def test_excludes_suppression_list():
    sql = _sql().upper()
    assert "NOT EXISTS" in sql
    assert "SUPPRESSION_LIST" in sql


def test_search_window_90_days():
    assert "INTERVAL 90 DAY" in _sql()


def test_last_login_window_30_days():
    assert "INTERVAL 30 DAY" in _sql()
