from collections.abc import Iterator

import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Make sure every test sees settings built from its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
