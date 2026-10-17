"""Apply every missing database migration, in order (task 6.1, D-041, D-069).

Migrations are the numbered plain-SQL files ``src/data/migrations/NNN_name.up.sql``.
The table ``schema_migrations(version, name, applied_at)`` remembers which ones ran.
Each missing file runs in ITS OWN transaction together with its schema_migrations
row: if it fails, that migration is rolled back completely, nothing after it runs,
and the ones before it stay applied.

"Missing" = every version not in schema_migrations, not only versions above the
highest one (D-069: on the dev database 003 was applied before 002).
A second run finds nothing missing and changes nothing.

``schema.sql`` (the base tables) is NOT a migration: on a fresh Docker volume the
db container runs it once (docker-entrypoint-initdb.d), then this script adds 001+.

A database whose migrations were applied by hand earlier (no schema_migrations
table, but the tables exist) is refused, so nothing runs twice. Record what is
already there first, without running it:

    python -m scripts.migrate --mark-applied 001 002 003

Run (same database settings as the API: DATABASE_URL or POSTGRES_*):

    python -m scripts.migrate                 # apply missing migrations
    python -m scripts.migrate --dry-run       # only list what would run
    docker compose -f docker-compose.prod.yml run --rm api python -m scripts.migrate
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from src.api.config import ConfigError, load_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "data" / "migrations"
FILE_PATTERN = re.compile(r"^(?P<version>\d{3})_(?P<name>\w+)\.up\.sql$")
# Any fixed number: two runs at the same moment wait for each other instead of both applying.
LOCK_ID = 6_100_041

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY CHECK (version ~ '^[0-9]{3}$'),
    name        TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """The migration files or the database are not in a state we can safely migrate."""


@dataclass(frozen=True)
class Migration:
    """One ``NNN_name.up.sql`` file."""

    version: str
    name: str
    path: Path


def find_migrations(folder: Path = MIGRATIONS_DIR) -> list[Migration]:
    """All *.up.sql files, sorted by version. Two files with one version -> MigrationError."""
    found: dict[str, Migration] = {}
    for path in folder.glob("*.up.sql"):
        match = FILE_PATTERN.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: expected NNN_name.up.sql (3 digits)")
        version = match["version"]
        if version in found:
            raise MigrationError(f"version {version} used twice: {found[version].path.name}, {path.name}")
        found[version] = Migration(version, match["name"], path)
    return [found[v] for v in sorted(found)]


def table_exists(conn: psycopg.Connection, table: str) -> bool:
    """True if ``table`` exists in the current schema (search_path)."""
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]


def applied_versions(conn: psycopg.Connection) -> set[str]:
    """Versions recorded in schema_migrations (empty set if the table does not exist yet)."""
    if not table_exists(conn, "schema_migrations"):
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def check_not_migrated_by_hand(conn: psycopg.Connection) -> None:
    """Refuse a database where 001 already ran but schema_migrations does not exist.

    Without this, 001 would run again and fail on "relation destinations already exists".
    """
    if not table_exists(conn, "schema_migrations") and table_exists(conn, "destinations"):
        raise MigrationError(
            "migrations were applied by hand on this database (destinations exists, schema_migrations "
            "does not). Record them first: python -m scripts.migrate --mark-applied 001 002 003")


def ensure_table(conn: psycopg.Connection) -> None:
    """Create schema_migrations if needed (its own transaction)."""
    with conn.transaction():
        conn.execute(CREATE_TABLE)


def apply_one(conn: psycopg.Connection, migration: Migration) -> None:
    """Run one migration file + record it, all in one transaction (all or nothing)."""
    with conn.transaction():
        conn.execute(migration.path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                     (migration.version, migration.name))


def mark_applied(conn: psycopg.Connection, migrations: list[Migration], versions: list[str]) -> list[str]:
    """Record ``versions`` as applied WITHOUT running them (for databases migrated by hand)."""
    known = {m.version: m for m in migrations}
    unknown = [v for v in versions if v not in known]
    if unknown:
        raise MigrationError(f"no migration file for version(s) {', '.join(unknown)}")
    ensure_table(conn)
    with conn.transaction():
        for version in versions:
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s) "
                         "ON CONFLICT (version) DO NOTHING", (version, known[version].name))
    return versions


def migrate(conn: psycopg.Connection, migrations: list[Migration], dry_run: bool = False) -> list[Migration]:
    """Apply every migration whose version is not in schema_migrations, oldest first.

    Returns the migrations applied (or, with ``dry_run``, the ones that would be).
    """
    check_not_migrated_by_hand(conn)
    missing = [m for m in migrations if m.version not in applied_versions(conn)]
    if dry_run:
        return missing
    ensure_table(conn)
    for migration in missing:
        apply_one(conn, migration)
    return missing


def connect() -> psycopg.Connection:
    """Autocommit connection: every ``conn.transaction()`` above is a real BEGIN ... COMMIT."""
    url = load_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url, autocommit=True, connect_timeout=10)


def main(argv: list[str] | None = None) -> int:
    """CLI: apply missing migrations (or --dry-run / --mark-applied) and print what happened."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list missing migrations, change nothing")
    parser.add_argument("--mark-applied", nargs="+", metavar="VERSION",
                        help="record these versions as applied without running them (databases migrated by hand)")
    args = parser.parse_args(argv)
    try:
        migrations = find_migrations()
        with connect() as conn:
            conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))  # released when the connection closes
            if args.mark_applied:
                print("marked as applied (not run):", ", ".join(mark_applied(conn, migrations, args.mark_applied)))
                return 0
            done = migrate(conn, migrations, dry_run=args.dry_run)
    except (MigrationError, ConfigError, psycopg.Error) as exc:
        print(f"migrate: FAILED: {exc}", file=sys.stderr)
        return 1
    if not done:
        print("migrate: database is up to date, nothing to apply")
    for m in done:
        print(f"migrate: {'would apply' if args.dry_run else 'applied'} {m.path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
