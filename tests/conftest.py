from __future__ import annotations

import sqlite3

import pytest

from bucketio import db


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture()
def conn(db_path):
    connection = db.migrate(db_path)
    yield connection
    connection.close()


def pytest_configure(config):
    assert sqlite3.sqlite_version_info >= (3, 35), "BucketIO needs SQLite >= 3.35"
