import pytest

from app.services import master_repository, sheets_client


@pytest.fixture(autouse=True)
def _clear_master_repository_cache():
    """master_repository caches Master data (and derived normalized lookup
    columns) at module level via lru_cache. Tests monkeypatch _load_master_df
    with a different fixture DataFrame per test, so the derived caches must
    be cleared before each test - otherwise a later test can see normalized
    columns computed from an earlier test's DataFrame."""
    master_repository.clear_cache()
    yield
    master_repository.clear_cache()


@pytest.fixture(autouse=True)
def _clear_sheets_client_cache():
    """sheets_client caches worksheet objects and header rows at module
    level (see get_worksheet()/_get_header()). Tests monkeypatch get_worksheet
    with a different mock per test, so the header cache must be cleared
    before each test - otherwise a later test using the same (sheet_id,
    worksheet_name) pair can see a header cached from an earlier test's mock."""
    sheets_client.clear_worksheet_cache()
    yield
    sheets_client.clear_worksheet_cache()
