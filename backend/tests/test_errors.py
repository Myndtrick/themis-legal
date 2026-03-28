import sqlite3
import pytest
from app.errors import (
    ThemisError,
    DbLockedError,
    NoLawNumberError,
    SearchFailedError,
    DuplicateImportError,
    ImportFailedError,
    map_exception_to_error,
)


def test_map_sqlite_locked():
    exc = sqlite3.OperationalError("database is locked")
    err = map_exception_to_error(exc)
    assert isinstance(err, DbLockedError)
    assert err.code == "db_locked"
    assert err.status_code == 503
    assert "wait" in err.message.lower()


def test_map_unknown_operational_error():
    exc = sqlite3.OperationalError("disk I/O error")
    err = map_exception_to_error(exc)
    assert err.code == "internal"
    assert err.status_code == 500


def test_no_law_number_error():
    err = NoLawNumberError()
    assert err.code == "no_law_number"
    assert err.status_code == 400
    assert "standard law number" in err.message


def test_search_failed_error():
    err = SearchFailedError()
    assert err.code == "search_failed"
    assert err.status_code == 502


def test_duplicate_import_error():
    err = DuplicateImportError("Legea 506/2004")
    assert err.code == "duplicate"
    assert err.status_code == 409
    assert "506/2004" in err.message


def test_import_failed_error():
    err = ImportFailedError("timeout connecting to source")
    assert err.code == "import_failed"
    assert err.status_code == 500
    assert "timeout" in err.message


def test_error_to_dict():
    err = DbLockedError()
    d = err.to_dict()
    assert d == {"code": "db_locked", "message": err.message}


def test_map_generic_exception():
    exc = RuntimeError("something broke")
    err = map_exception_to_error(exc)
    assert err.code == "internal"
    assert err.status_code == 500
    assert "Something went wrong" in err.message
    # Must NOT contain the raw exception message
    assert "something broke" not in err.message
