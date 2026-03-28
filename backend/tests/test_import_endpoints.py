"""Test that import endpoints use structured errors."""
import pytest
from app.errors import NoLawNumberError, DuplicateImportError, SearchFailedError, ImportFailedError


def test_no_law_number_error_shape():
    err = NoLawNumberError()
    assert err.status_code == 400
    assert err.to_dict() == {"code": "no_law_number", "message": err.message}


def test_duplicate_import_error_shape():
    err = DuplicateImportError("Legea 506/2004")
    assert err.status_code == 409
    assert "506/2004" in err.to_dict()["message"]


def test_import_laws_uses_structured_errors():
    """Verify that laws.py imports ThemisError classes (not just HTTPException)."""
    from app.routers import laws
    import inspect
    source = inspect.getsource(laws.import_suggestion)
    # Should use ThemisError raises, not HTTPException
    assert "NoLawNumberError" in source
    assert "DuplicateImportError" in source
    assert "ImportFailedError" in source


def test_import_endpoint_uses_structured_errors():
    """Verify import_law also uses structured errors."""
    from app.routers import laws
    import inspect
    source = inspect.getsource(laws.import_law)
    assert "DuplicateImportError" in source
    assert "ImportFailedError" in source
