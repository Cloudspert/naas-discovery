import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings() is @lru_cache'd (app/core/config.py) so the real app
    only builds Settings once per process -- but that would leak state
    between tests that set different env vars. Clear it before and after
    every test.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def clusters_yaml(tmp_path):
    """Write a small clusters.yaml fixture and return its path."""

    def _write(content: str):
        path = tmp_path / "clusters.yaml"
        path.write_text(content)
        return str(path)

    return _write
