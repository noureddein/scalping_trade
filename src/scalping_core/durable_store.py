"""PostgreSQL persistence facade and explicitly disposable migration runner.

Migration execution is never automatic. The runner refuses database names
that do not clearly identify an isolated test database and verifies the
connected database name before applying SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from psycopg.conninfo import conninfo_to_dict

from .postgres_store import (
    PostgresDurableStateStore,
    PostgresPairReservationProvider,
    PostgresStartupReconciler,
)

_MIGRATION = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
_DISPOSABLE_DATABASE = re.compile(r"^(?:test_[a-z0-9_]+|[a-z0-9_]+_test)$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    path: Path


class MigrationRunner:
    """Apply sequential SQL migrations to a disposable PostgreSQL database.

    Construction and planning are local-only. ``apply`` requires an explicit
    disposable database name and checks it against the live connection before
    issuing any DDL.
    """

    def __init__(self, conninfo: str, migrations_dir: str | Path,
                 expected_database: str) -> None:
        parsed = conninfo_to_dict(conninfo)
        configured_database = parsed.get("dbname") or parsed.get("database")
        if configured_database != expected_database:
            raise ValueError("expected_database must match the connection string database")
        if not _DISPOSABLE_DATABASE.fullmatch(expected_database):
            raise ValueError("migration target must be explicitly named as a disposable test database")
        self.conninfo = conninfo
        self.expected_database = expected_database
        self.migrations_dir = Path(migrations_dir)

    def discover(self) -> tuple[Migration, ...]:
        found = []
        for path in self.migrations_dir.glob("*.sql"):
            match = _MIGRATION.fullmatch(path.name)
            if match:
                found.append(Migration(int(match.group(1)), path))
        found.sort(key=lambda item: item.version)
        versions = [item.version for item in found]
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError("migration files must be sequential starting at 001")
        return tuple(found)

    def pending(self, applied_versions: set[int]) -> tuple[Migration, ...]:
        migrations = self.discover()
        known = {item.version for item in migrations}
        if not applied_versions <= known:
            raise ValueError("database contains migration versions unknown to this code")
        if applied_versions and applied_versions != set(range(1, max(applied_versions) + 1)):
            raise ValueError("database migration history has a gap")
        return tuple(item for item in migrations if item.version not in applied_versions)

    def apply(self) -> tuple[int, ...]:
        import psycopg

        applied: list[int] = []
        migrations = self.discover()
        with psycopg.connect(self.conninfo, autocommit=True) as conn:
            actual_database = conn.execute("SELECT current_database()").fetchone()[0]
            if actual_database != self.expected_database:
                raise RuntimeError("connected database does not match disposable target")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            present = {row[0] for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()}
            for migration in self.pending(present):
                sql = migration.path.read_text(encoding="utf-8")
                commit_at = sql.upper().rfind("COMMIT;")
                if commit_at < 0:
                    raise ValueError(f"{migration.path.name} must own an explicit transaction")
                tracking = (
                    f"INSERT INTO schema_migrations(version) VALUES ({migration.version});\n"
                )
                sql = sql[:commit_at] + tracking + sql[commit_at:]
                conn.execute(sql)
                applied.append(migration.version)
            required_tables = {
                "daily_risk_state", "orders", "positions", "pair_reservations",
                "schema_account", "reconciliation_barrier", "operator_override_audit",
                "risk_events",
            }
            existing_tables = {row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()}
            missing_tables = required_tables - existing_tables
            if missing_tables:
                raise RuntimeError(f"migration verification missing tables: {sorted(missing_tables)}")
            risk_columns = {row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'daily_risk_state'"
            ).fetchall()}
            if "floating_pnl_usd" not in risk_columns:
                raise RuntimeError("migration verification missing daily floating P/L column")
            trigger_exists = conn.execute(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'trg_order_state_guard' AND NOT tgisinternal"
            ).fetchone()
            if trigger_exists is None:
                raise RuntimeError("migration verification missing order state guard")
        return tuple(applied)


__all__ = [
    "Migration", "MigrationRunner", "PostgresDurableStateStore",
    "PostgresPairReservationProvider", "PostgresStartupReconciler",
]
