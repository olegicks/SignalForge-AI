"""Shared fixtures.

Database tests run against a real, disposable PostgreSQL database given by TEST_DATABASE_URL
(a service container in CI). They are skipped when it is not set. The schema is built with
`alembic upgrade head`, so the migrations themselves are tested too.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from core.config import BACKEND_DIR, Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Make sure every test sees settings built from its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def alembic_config(url: str) -> Config:
    config = Config(str(Path(BACKEND_DIR) / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = Settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url)
    with engine.begin() as conn:
        # Start from a clean slate in case a previous run was interrupted.
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(alembic_config(test_database_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test, even if the code commits."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        yield session
        session.close()
        transaction.rollback()
