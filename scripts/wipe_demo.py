"""Empty the demo data before real customers are entered (task 8.2d).

Run it ONLY through ``scripts/wipe_demo.sh``: that script takes a backup first and passes its
file name here (``--after-backup``); without it this refuses to start.

What is emptied: companies, vehicles, service_records, reminders_sent, reminder_stops (driver
phones that asked for no messages, migration 006, task 9.5b; skipped on an older database), plus every table that
references them through a foreign key, found from the database itself (today: predictions and
reminders), so a table added later cannot be forgotten or block the wipe.
What is kept: destinations (route lookup, D-064) and schema_migrations (migrate.py's record).
If a kept table would be emptied, the script stops before deleting anything.

All rows go in ONE transaction (TRUNCATE ... RESTART IDENTITY: real records start again at id 1),
and only after the operator types ``WIPE <database name>``. Anything else -> nothing is deleted.

    docker compose -f docker-compose.prod.yml run --rm api \
        python -m scripts.wipe_demo --after-backup oil_change_2026-10-23_120000.sql.gz
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

import psycopg

from src.api.config import ConfigError, load_settings

CORE_TABLES = ("companies", "vehicles", "service_records", "reminders_sent", "reminder_stops")
KEEP_TABLES = ("destinations", "schema_migrations")

# Foreign keys inside the current schema: (referencing table, referenced table).
FK_SQL = """
SELECT DISTINCT src.relname, dst.relname
FROM pg_constraint c
JOIN pg_class src ON src.oid = c.conrelid
JOIN pg_class dst ON dst.oid = c.confrelid
WHERE c.contype = 'f'
  AND src.relnamespace = current_schema()::regnamespace
  AND dst.relnamespace = current_schema()::regnamespace
"""


class WipeError(RuntimeError):
    """The wipe would touch something it must not; nothing was deleted."""


def tables_to_empty(conn: psycopg.Connection, core: tuple[str, ...] = CORE_TABLES) -> list[str]:
    """The core tables plus everything that references them (directly or through another table)."""
    edges = conn.execute(FK_SQL).fetchall()
    found = {t for t in core if _exists(conn, t)}  # reminder_stops exists only from migration 006 on
    grew = True
    while grew:  # keep adding referencing tables until nothing new appears
        new = {src for src, dst in edges if dst in found} - found
        found |= new
        grew = bool(new)
    hit = found & set(KEEP_TABLES)
    if hit:
        raise WipeError(f"would empty kept table(s) {sorted(hit)}; nothing deleted")
    return sorted(found)


def row_counts(conn: psycopg.Connection, tables: list[str]) -> dict[str, int]:
    """Exact row count per table (table names come from the catalog or our constants, not users)."""
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def wipe(conn: psycopg.Connection, tables: list[str]) -> None:
    """Empty ``tables`` in one transaction. No CASCADE: if an unlisted table still referenced
    them, PostgreSQL would refuse and roll back instead of silently emptying it too."""
    names = ", ".join(f'"{t}"' for t in tables)
    with conn.transaction():
        conn.execute(f"TRUNCATE {names} RESTART IDENTITY")


def run(conn: psycopg.Connection, backup_name: str, ask: Callable[[str], str] = input) -> int:
    """Show the plan, ask for the typed confirmation, wipe. Returns the exit code."""
    database = conn.execute("SELECT current_database()").fetchone()[0]
    tables = tables_to_empty(conn)
    before = row_counts(conn, tables)
    kept = row_counts(conn, [t for t in KEEP_TABLES if _exists(conn, t)])
    print(f"wipe_demo: database {database}, backup taken first: {backup_name}")
    print("  will be EMPTIED: " + ", ".join(f"{t} ({n})" for t, n in before.items()))
    print("  kept as is:      " + ", ".join(f"{t} ({n})" for t, n in kept.items()))
    phrase = f"WIPE {database}"
    if ask(f"Type '{phrase}' to delete these rows: ").strip() != phrase:
        print("wipe_demo: confirmation did not match, nothing deleted")
        return 1
    wipe(conn, tables)
    after = row_counts(conn, tables)
    if any(after.values()) or row_counts(conn, list(kept)) != kept:
        print(f"wipe_demo: FAILED check after wipe: {after}", file=sys.stderr)
        return 1
    print(f"wipe_demo: done, {sum(before.values())} rows deleted; kept tables unchanged. "
          f"Restore if needed: docs/deploy.md §12 with {backup_name}")
    return 0


def _exists(conn: psycopg.Connection, table: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    """CLI used by scripts/wipe_demo.sh."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--after-backup", required=True, metavar="FILE",
                        help="backup file made just before (wipe_demo.sh passes it)")
    args = parser.parse_args(argv)
    try:
        url = load_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
            return run(conn, args.after_backup)
    except (WipeError, ConfigError, psycopg.Error) as exc:
        print(f"wipe_demo: FAILED, nothing deleted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
