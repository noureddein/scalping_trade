from __future__ import annotations

from pathlib import Path
import os

import pytest
from psycopg.conninfo import conninfo_to_dict

from scalping_core.durable_store import MigrationRunner


ROOT = Path(__file__).resolve().parents[1]
_DISPOSABLE_URL = os.environ.get("SCALPING_DISPOSABLE_DATABASE_URL")


def test_migration_runner_discovers_all_sequential_migrations():
    runner = MigrationRunner(
        "postgresql://localhost/scalping_test", ROOT / "migrations", "scalping_test",
    )
    migrations = runner.discover()
    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert [migration.version for migration in runner.pending(set())] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert [migration.version for migration in runner.pending({1, 2, 3, 4, 5, 6, 7, 8, 9, 10})] == [11]
    assert runner.pending({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}) == ()


def test_migration_runner_rejects_non_disposable_database_before_connecting():
    with pytest.raises(ValueError, match="disposable test database"):
        MigrationRunner("postgresql://localhost/scalping", ROOT / "migrations", "scalping")


def test_migration_runner_rejects_connection_target_mismatch():
    with pytest.raises(ValueError, match="match the connection string"):
        MigrationRunner("postgresql://localhost/scalping_test", ROOT / "migrations", "other_test")


def test_migration_history_must_be_sequential():
    runner = MigrationRunner(
        "postgresql://localhost/scalping_test", ROOT / "migrations", "scalping_test",
    )
    with pytest.raises(ValueError, match="gap"):
        runner.pending({1, 3})


@pytest.mark.skipif(not _DISPOSABLE_URL,
                    reason="SCALPING_DISPOSABLE_DATABASE_URL is unset")
def test_apply_and_upgrade_migrations_on_explicit_disposable_database():
    import psycopg
    assert _DISPOSABLE_URL is not None
    database = conninfo_to_dict(_DISPOSABLE_URL).get("dbname")
    assert database is not None
    # Drop all tables so migrations can be re-applied cleanly
    with psycopg.connect(_DISPOSABLE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    runner = MigrationRunner(_DISPOSABLE_URL, ROOT / "migrations", database)
    applied = runner.apply()
    assert set(applied) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
    assert runner.apply() == ()
