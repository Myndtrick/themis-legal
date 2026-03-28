import sqlite3
import time
import pytest
from unittest.mock import MagicMock
from app.errors import with_sqlite_retry, DbLockedError


def test_succeeds_first_try():
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert operation() == "ok"
    assert call_count == 1


def test_retries_on_db_locked():
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert operation() == "ok"
    assert call_count == 3


def test_raises_after_max_retries():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(DbLockedError):
        operation()


def test_no_retry_on_other_operational_error():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        operation()


def test_no_retry_on_non_sqlite_error():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        operation()


def test_calls_rollback_on_retry():
    """If a db session is the first arg, rollback is called on retry."""
    mock_db = MagicMock()
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation(db):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert operation(mock_db) == "ok"
    mock_db.rollback.assert_called_once()
