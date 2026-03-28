"""Structured error codes for Themis API responses."""

import sqlite3


class ThemisError(Exception):
    """Base error with code, HTTP status, and user-facing message."""

    code: str = "internal"
    status_code: int = 500
    message: str = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None):
        if message is not None:
            self.message = message
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class DbLockedError(ThemisError):
    code = "db_locked"
    status_code = 503
    message = "Another import is in progress. Please wait a moment and try again."


class NoLawNumberError(ThemisError):
    code = "no_law_number"
    status_code = 400
    message = (
        "This document cannot be auto-imported because it has no "
        "standard law number (e.g. Constituția)."
    )


class SearchFailedError(ThemisError):
    code = "search_failed"
    status_code = 502
    message = "Could not reach the legislation database. Please try again later."


class DuplicateImportError(ThemisError):
    code = "duplicate"
    status_code = 409

    def __init__(self, title: str = ""):
        msg = f"This law has already been imported as '{title}'." if title else "This law has already been imported."
        super().__init__(msg)


class ImportFailedError(ThemisError):
    code = "import_failed"
    status_code = 500

    def __init__(self, context: str = ""):
        msg = f"Import failed: {context}. Please try again." if context else "Import failed. Please try again."
        super().__init__(msg)


def map_exception_to_error(exc: Exception) -> ThemisError:
    """Map a raw exception to a structured ThemisError."""
    if isinstance(exc, ThemisError):
        return exc
    if isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc):
        return DbLockedError()
    if isinstance(exc, ValueError):
        return ImportFailedError(str(exc))
    return ThemisError()
