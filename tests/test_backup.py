"""Tests for scripts/backup.sh and the systemd timer (task 8.2).

backup.sh runs for real, with a FAKE `docker` first on PATH that prints a tiny dump (or fails),
so no container or database is needed. The real pg_dump + restore is checked by
scripts/restore_test.sh (docs/deploy.md §12).
"""

import gzip
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "scripts" / "backup.sh"
DAY = 24 * 3600

FAKE_DOCKER = """#!/bin/sh
echo "$@" > "$FAKE_ARGS"
case "$FAKE_MODE" in
  fail) printf -- '-- PostgreSQL database dump\\nCOPY public.companies (id) FROM stdin;\\n'; exit 1 ;;
  cut)  printf -- '-- PostgreSQL database dump\\nCOPY public.companies (id) FROM stdin;\\n1\\n' ;;
  *)    printf -- '-- PostgreSQL database dump\\nCOPY public.companies (id) FROM stdin;\\n1\\n\\\\.\\n\\n-- PostgreSQL database dump complete\\n\\n' ;;
esac
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run_backup(tmp_path: Path, mode: str = "ok") -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_MODE": mode,
           "FAKE_ARGS": str(tmp_path / "args.txt"), "BACKUP_DIR": str(tmp_path / "backups"),
           "REPO_DIR": "/srv/repo", "KEEP_DAYS": "14"}
    return subprocess.run(["bash", str(BACKUP)], env=env, capture_output=True, text=True, timeout=30)


def backups(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "backups").glob("*"))


def old_file(folder: Path, name: str, days: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"old")
    past = time.time() - days * DAY
    os.utime(path, (past, past))
    return path


def test_backup_is_dated_gzipped_private_and_printed(tmp_path: Path) -> None:
    result = run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    [path] = backups(tmp_path)
    assert result.stdout.strip() == str(path)  # wipe_demo.sh reads this line
    assert path.name.startswith("oil_change_20") and path.name.endswith(".sql.gz")
    assert "dump complete" in gzip.decompress(path.read_bytes()).decode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600  # names + phones inside (RISK-06)
    args = (tmp_path / "args.txt").read_text()
    assert "-f /srv/repo/docker-compose.prod.yml exec -T db" in args and "pg_dump" in args


def test_keeps_14_days_and_only_touches_own_files(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    gone = old_file(folder, "oil_change_2026-10-01_030000.sql.gz", days=15)
    kept = old_file(folder, "oil_change_2026-10-10_030000.sql.gz", days=13)
    other = old_file(folder, "notes.txt", days=40)
    assert run_backup(tmp_path).returncode == 0
    assert not gone.exists() and kept.exists() and other.exists()


@pytest.mark.parametrize("mode", ["fail", "cut"])
def test_failed_or_incomplete_dump_keeps_nothing_and_deletes_nothing(tmp_path: Path, mode: str) -> None:
    """pg_dump error, or a dump that stops early: exit != 0, no new file, old backups untouched."""
    old = old_file(tmp_path / "backups", "oil_change_2026-09-01_030000.sql.gz", days=30)
    result = run_backup(tmp_path, mode)
    assert result.returncode != 0
    assert backups(tmp_path) == [old]  # no new file, no .part left, retention did not run


def test_scripts_are_executable() -> None:
    for name in ("backup.sh", "restore_test.sh", "wipe_demo.sh"):
        assert os.access(ROOT / "scripts" / name, os.X_OK), name


def test_timer_runs_daily_at_3_ulaanbaatar_and_catches_up() -> None:
    timer = (ROOT / "deploy" / "systemd" / "ocp-backup.timer").read_text()
    service = (ROOT / "deploy" / "systemd" / "ocp-backup.service").read_text()
    assert "OnCalendar=*-*-* 03:00:00 Asia/Ulaanbaatar" in timer
    assert "Persistent=true" in timer and "WantedBy=timers.target" in timer
    assert "ExecStart=/root/oil-change-predictor/scripts/backup.sh" in service
    assert "Environment=KEEP_DAYS=14" in service and "Type=oneshot" in service
