import pytest

from app.services import master_repository


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
