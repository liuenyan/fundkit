"""Shared test fixtures — in-memory SQLite for db.py tests"""

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine

import db


@pytest.fixture()
def db_engine() -> Generator[Any, None, None]:
    """Replace db.engine with a fresh in-memory SQLite engine for each test."""
    test_engine = create_engine("sqlite://", echo=False)
    orig = db.engine
    db.engine = test_engine
    db.metadata.create_all(test_engine)
    db._DB_INITIALIZED = True
    yield test_engine
    db.engine = orig
    db._DB_INITIALIZED = False
