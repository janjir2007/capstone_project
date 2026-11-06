"""Tests for the off-server copy (task 8.2c, plan docs/plans/8.2c_plan.md §10).

The real bash scripts run with FAKE `rclone`, `age`, `curl` and `docker` first on PATH (small
Python scripts written below), so there is no network, no OneDrive, no real key and no container.
- fake rclone: "OneDrive" is a folder on disk (FAKE_REMOTE); every call is logged as a JSON line.
- fake age: "encrypts" by writing the age header + the input bytes reversed, so a test can tell
  an encrypted file from a plain dump; "decrypts" by reversing it back.
- fake curl: only logs its arguments (the healthchecks.io ping).
- fake docker: pretends to be a Postgres container and answers the row-count queries.
Real OneDrive / age / systemd checks are done once by Ari on the server (docs/deploy.md §12).
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
OFFSITE = ROOT / "scripts" / "offsite_backup.sh"
RESTORE = ROOT / "scripts" / "offsite_restore_test.sh"
AWK = ROOT / "scripts" / "dump_row_counts.awk"
UB = ZoneInfo("Asia/Ulaanbaatar")
PING = "https://hc-ping.example/uuid-0000"
PLACEHOLDER = "FAKE-TOKEN-123"  # stands in for the OneDrive token; must never reach the output
AGE_HEADER = b"age-encryption.org/v1\n"

# Synthetic dump (no real data): two tables, 2 + 1 rows, one empty table.
DUMP = (
    "-- PostgreSQL database dump\n"
    "COPY public.companies (id, name) FROM stdin;\n1\tTest Driver One\n2\tTest Driver Two\n\\.\n\n"
    "COPY public.vehicles (id, plate) FROM stdin;\n1\t0000TEST\n\\.\n\n"
    "COPY public.reminders_sent (id) FROM stdin;\n\\.\n\n"
    "-- PostgreSQL database dump complete\n\n"
)
DUMP_COUNTS = {"public.companies": 2, "public.vehicles": 1, "public.reminders_sent": 0}

FAKE_RCLONE = r'''
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
with_value = {"--config", "--retries", "--low-level-retries", "--contimeout", "--timeout"}
pos, i = [], 0
while i < len(args):
    if args[i] in with_value:
        i += 2
    elif args[i].startswith("-"):
        i += 1
    else:
        pos.append(args[i]); i += 1
cmd, rest = pos[0], pos[1:]
mode = os.environ.get("FAKE_MODE", "")
root = Path(os.environ["FAKE_REMOTE"])
if mode == cmd + "-fail":
    sys.stderr.write('using token {"access_token":"' + os.environ["FAKE_SECRET"] + '"}\n'
                     "ERROR : could not reach OneDrive\n"
                     "Authorization: Bearer " + os.environ["FAKE_SECRET"] + "\n")
    sys.exit(1)
def remote(p):
    return root / p.split(":", 1)[1]
if cmd == "lsf":
    d = remote(rest[0])
    if not d.is_dir():
        sys.stderr.write("ERROR : directory not found\n"); sys.exit(3)
    for p in sorted(d.iterdir()):
        if p.is_file():
            print(p.name)
        elif "--files-only" not in args:
            print(p.name + "/")
elif cmd == "copyto":
    src, dst = rest
    if src.startswith("/"):
        remote(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, remote(dst))
    else:
        shutil.copyfile(remote(src), dst)
elif cmd == "lsjson":
    p = remote(rest[0])
    size = p.stat().st_size + (1 if mode == "badsize" else 0)
    print("[")
    print(json.dumps({"Path": p.name, "Name": p.name, "Size": size, "IsDir": False}, separators=(",", ":")))
    print("]")
elif cmd == "deletefile":
    remote(rest[0]).unlink()
else:
    sys.stderr.write("fake rclone: unknown command " + cmd + "\n"); sys.exit(2)
'''

FAKE_AGE = r'''
import os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_AGE_LOG"], "a") as f:
    f.write(" ".join(args) + "\n")
header = b"age-encryption.org/v1\n"
out, src = args[args.index("-o") + 1], args[-1]
data = Path(src).read_bytes()
if "-d" in args:
    if not Path(args[args.index("-i") + 1]).is_file() or not data.startswith(header):
        sys.exit(1)
    Path(out).write_bytes(data[len(header):][::-1])
else:
    Path(out).write_bytes(header + data[::-1])
'''

FAKE_CURL = r'''
import os, sys
with open(os.environ["FAKE_CURL_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
'''

FAKE_DOCKER = r'''
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(" ".join(args) + "\n")
mode = os.environ.get("FAKE_DOCKER", "")
counts = json.loads(os.environ["FAKE_COUNTS"])
if args[0] == "run":
    sys.exit(1 if mode == "run-fail" else 0)
if args[0] == "exec" and "pg_isready" in args:
    sys.exit(0)
if args[0] == "exec" and "psql" in args:
    sql = sys.stdin.read()
    if "information_schema.tables" in sql:
        print(len(counts))
    elif "count(*)" in sql:
        for t in re.findall(r"FROM (\S+?)(?: UNION|;)", sql):
            print(t, counts[t] + (1 if mode == "diff" else 0))
    elif mode == "restore-fail":
        sys.exit(1)
    sys.exit(0)
'''

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


# ---- helpers ------------------------------------------------------------------------------------

def write_fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)


def dump_name(when: datetime) -> str:
    return f"oil_change_{when:%Y-%m-%d_%H%M%S}.sql.gz"


def ub_now() -> datetime:
    return datetime.now(UB).replace(microsecond=0)


class Env:
    """One test's fake server: dirs, config files, fake tools, and a way to run the scripts."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.backups = tmp_path / "backups"
        self.remote = tmp_path / "onedrive"
        self.tmpdir = tmp_path / "tmpd"
        for d in (self.bin, self.backups, self.remote / "db", self.tmpdir):
            d.mkdir(parents=True)
        for name, body in (("rclone", FAKE_RCLONE), ("age", FAKE_AGE), ("curl", FAKE_CURL),
                           ("docker", FAKE_DOCKER)):
            write_fake(self.bin, name, body)
        self.log = tmp_path / "rclone.log"
        self.curl_log = tmp_path / "curl.log"
        self.recipients = tmp_path / "age_recipients.txt"
        self.recipients.write_text("# Mac key, paper key\nage1fakepublickeyone\nage1fakepublickeytwo\n")
        self.conf = tmp_path / "rclone.conf"
        self.write_conf(fence=True)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(self.tmpdir),
            "FAKE_LOG": str(self.log), "FAKE_REMOTE": str(self.remote), "FAKE_SECRET": PLACEHOLDER,
            "FAKE_AGE_LOG": str(tmp_path / "age.log"), "FAKE_CURL_LOG": str(self.curl_log),
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"), "FAKE_COUNTS": json.dumps(DUMP_COUNTS),
            "BACKUP_DIR": str(self.backups), "RCLONE_CONFIG": str(self.conf),
            "RECIPIENTS": str(self.recipients), "OFFSITE_PING_URL": PING,
        }
        for key in ("OFFSITE_FENCE", "FAKE_MODE", "FAKE_DOCKER"):
            self.env.pop(key, None)

    def write_conf(self, fence: bool, mode: int = 0o600) -> None:
        lines = ["[other]", "type = local", "root_folder_id = NOT-OURS", "",
                 "[ocp-offsite]", "type = onedrive", f"token = {PLACEHOLDER}", "drive_type = personal"]
        if fence:
            lines.append("root_folder_id = FAKEFOLDERID")
        self.conf.write_text("\n".join(lines) + "\n")
        self.conf.chmod(mode)

    def dump(self, minutes_ago: float, *, empty: bool = False, damaged: bool = False) -> str:
        """A local dump named and dated `minutes_ago` minutes in the past."""
        name = dump_name(ub_now() - timedelta(minutes=minutes_ago))
        path = self.backups / name
        data = b"" if empty else gzip.compress(DUMP.encode())
        path.write_bytes(data[:-10] if damaged else data)
        past = time.time() - minutes_ago * 60
        os.utime(path, (past, past))
        return name

    def remote_copy(self, name: str, folder: str = "db") -> None:
        (self.remote / folder).mkdir(parents=True, exist_ok=True)
        (self.remote / folder / name).write_bytes(AGE_HEADER + b"old copy")

    def run(self, script: Path = OFFSITE, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script), *args], env={**self.env, **extra},
                              capture_output=True, text=True, timeout=60)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def calls_of(self, cmd: str) -> list[list[str]]:
        return [c for c in self.calls() if cmd in c]

    def uploads(self) -> list[str]:
        """Remote targets of every upload, in order."""
        return [c[-1] for c in self.calls_of("copyto")]

    def pings(self) -> list[str]:
        return self.curl_log.read_text().splitlines() if self.curl_log.exists() else []

    def remote_names(self, folder: str = "db") -> list[str]:
        return sorted(p.name for p in (self.remote / folder).iterdir())


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def assert_failed(result: subprocess.CompletedProcess, env: Env, step: str) -> None:
    assert result.returncode == 1, result.stderr
    assert f"offsite: FAILED step={step}" in result.stderr
    assert any(p.endswith(f"{PING}/fail") for p in env.pings()), env.pings()


# ---- server job: happy path, catch-up ---------------------------------------------------------

def test_happy_path_uploads_one_encrypted_copy_and_pings(env: Env) -> None:
    name = env.dump(minutes_ago=20)
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.uploads() == [f"ocp-offsite:db/{name}.age"]
    copy = (env.remote / "db" / f"{name}.age").read_bytes()
    assert copy.startswith(AGE_HEADER)
    assert gzip.decompress(copy[len(AGE_HEADER):][::-1]).decode() == DUMP  # the right dump, encrypted
    assert "offsite: OK uploaded 1 (oil_change_" in result.stderr
    assert "-> ocp-offsite:db, 1 kept, 0 deleted" in result.stderr
    # Q1: exactly one success ping, no /fail, no /start; the URL itself is never printed
    assert len(env.pings()) == 1 and env.pings()[0].endswith(PING)
    assert PING not in result.stdout + result.stderr
    assert list(env.tmpdir.iterdir()) == []  # temp copies deleted


def test_never_uploads_plain_text(env: Env) -> None:
    for minutes in (20, 60 * 24, 60 * 48):
        env.dump(minutes_ago=minutes)
    assert env.run().returncode == 0
    for call in env.calls_of("copyto"):
        src = call[-2]
        assert src.endswith(".sql.gz.age"), call
    for path in (env.remote / "db").iterdir():
        assert path.read_bytes().startswith(AGE_HEADER)


def test_catch_up_uploads_only_missing_files_oldest_first(env: Env) -> None:
    oldest = env.dump(minutes_ago=60 * 48)
    already = env.dump(minutes_ago=60 * 24)
    newest = env.dump(minutes_ago=20)
    env.remote_copy(f"{already}.age")
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.uploads() == [f"ocp-offsite:db/{oldest}.age", f"ocp-offsite:db/{newest}.age"]
    assert "offsite: OK uploaded 2" in result.stderr


def test_second_run_uploads_nothing_and_is_still_ok(env: Env) -> None:
    env.dump(minutes_ago=20)
    assert env.run().returncode == 0
    env.log.unlink()
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.uploads() == []
    assert "offsite: OK uploaded 0 -> ocp-offsite:db, 1 kept" in result.stderr


def test_old_dumps_are_caught_up_even_though_older_than_3h(env: Env) -> None:
    """The 3 h rule (A1) is for tonight's dump only."""
    names = [env.dump(minutes_ago=m) for m in (60 * 48, 60 * 24, 20)]
    assert env.run().returncode == 0
    assert env.uploads() == [f"ocp-offsite:db/{n}.age" for n in names]


# ---- server job: guards (A1, keys, fence) -------------------------------------------------------

@pytest.mark.parametrize("hours, ok", [(4, False), (2, True)])
def test_newest_dump_older_than_3h_fails(env: Env, hours: int, ok: bool) -> None:
    env.dump(minutes_ago=hours * 60)
    result = env.run()
    if ok:
        assert result.returncode == 0, result.stderr
    else:
        assert_failed(result, env, "check")
        assert "4 h old" in result.stderr and "did ocp-backup run?" in result.stderr
        assert env.uploads() == []


def test_empty_newest_dump_fails(env: Env) -> None:
    env.dump(minutes_ago=60 * 24)
    env.dump(minutes_ago=10, empty=True)
    result = env.run()
    assert_failed(result, env, "check")
    assert "is empty" in result.stderr
    assert env.calls() == []  # no rclone call at all


def test_no_local_dump_fails(env: Env) -> None:
    result = env.run()
    assert_failed(result, env, "check")
    assert "no local dump" in result.stderr


def test_missing_backup_dir_fails(env: Env) -> None:
    result = env.run(BACKUP_DIR=str(env.tmp / "does-not-exist"))
    assert_failed(result, env, "check")


def test_damaged_old_dump_is_skipped_and_the_run_fails_without_pruning(env: Env) -> None:
    bad = env.dump(minutes_ago=60 * 24, damaged=True)
    good = env.dump(minutes_ago=20)
    for days in range(40, 50):  # old copies that a good run would prune
        env.remote_copy(dump_name(ub_now() - timedelta(days=days)) + ".age")
    result = env.run()
    assert_failed(result, env, "check")
    assert f"dump {bad} is damaged" in result.stderr
    assert env.uploads() == [f"ocp-offsite:db/{good}.age"]  # the good one still goes up
    assert env.calls_of("deletefile") == []


def test_private_key_on_server_is_refused(env: Env) -> None:
    env.dump(minutes_ago=20)
    env.recipients.write_text("age1fakepublickeyone\nAGE-SECRET-KEY-1FAKE\n")
    result = env.run()
    assert_failed(result, env, "check")
    assert "PRIVATE key" in result.stderr
    assert env.calls() == []
    assert "AGE-SECRET-KEY-1FAKE" not in result.stderr


@pytest.mark.parametrize("content", ["age1fakepublickeyone\n", "age1a\nage1b\nage1c\n", "age1a\nage1b\nhello\n"])
def test_recipients_must_be_exactly_two_public_keys(env: Env, content: str) -> None:
    env.dump(minutes_ago=20)
    env.recipients.write_text(content)
    assert_failed(env.run(), env, "check")
    assert env.calls() == []


def test_rclone_conf_must_be_mode_600(env: Env) -> None:
    env.dump(minutes_ago=20)
    env.write_conf(fence=True, mode=0o644)
    result = env.run()
    assert_failed(result, env, "check")
    assert "mode 600" in result.stderr
    assert env.calls() == []


def test_fence_missing_refuses_without_any_rclone_call(env: Env) -> None:
    """root_folder_id under [ocp-offsite] is required; the one under [other] does not count."""
    env.dump(minutes_ago=20)
    env.write_conf(fence=False)
    result = env.run()
    assert_failed(result, env, "check")
    assert "folder fence missing" in result.stderr
    assert env.calls() == []
    assert PLACEHOLDER not in result.stdout + result.stderr


def test_every_remote_path_is_inside_the_fence(env: Env) -> None:
    """Env vars that look like a remote setting change nothing: the path is a constant."""
    env.dump(minutes_ago=60 * 24)
    env.dump(minutes_ago=20)
    for days in range(35, 45):
        env.remote_copy(dump_name(ub_now() - timedelta(days=days)) + ".age")
    result = env.run(OFFSITE_REMOTE="other:", REMOTE="other:", REMOTE_DIR="other:x", RCLONE_REMOTE="other:")
    assert result.returncode == 0, result.stderr
    assert env.calls_of("deletefile")  # prune ran, so its paths are checked too
    for call in env.calls():
        cmd_index = next(i for i, a in enumerate(call) if a in ("lsf", "copyto", "lsjson", "deletefile"))
        remote_args = [a for a in call[cmd_index + 1:] if not a.startswith(("/", "-")) and ":" in a]
        assert remote_args, call
        for arg in remote_args:
            assert arg.startswith("ocp-offsite:db") and ".." not in arg, call


def test_fixed_path_fallback_uses_only_the_fixed_folder(env: Env) -> None:
    """PM-approved fallback: no root_folder_id, constant path GeoExpert-Backups/db."""
    env.write_conf(fence=False)
    (env.remote / "GeoExpert-Backups" / "db").mkdir(parents=True)
    name = env.dump(minutes_ago=20)
    result = env.run(OFFSITE_FENCE="fixed_path")
    assert result.returncode == 0, result.stderr
    assert env.uploads() == [f"ocp-offsite:GeoExpert-Backups/db/{name}.age"]
    for call in env.calls():
        for arg in call:
            if arg.startswith("ocp-offsite:"):
                assert arg.startswith("ocp-offsite:GeoExpert-Backups/db"), call


def test_fixed_path_with_root_folder_id_is_refused(env: Env) -> None:
    env.dump(minutes_ago=20)
    assert_failed(env.run(OFFSITE_FENCE="fixed_path"), env, "check")
    assert env.calls() == []


def test_unknown_fence_mode_is_refused(env: Env) -> None:
    env.dump(minutes_ago=20)
    result = env.run(OFFSITE_FENCE="other:")
    assert_failed(result, env, "check")
    assert env.calls() == []


# ---- server job: upload / verify failures, secrets --------------------------------------------

def test_upload_failure_fails_deletes_nothing_and_hides_the_token(env: Env) -> None:
    env.dump(minutes_ago=20)
    for days in range(40, 50):
        env.remote_copy(dump_name(ub_now() - timedelta(days=days)) + ".age")
    result = env.run(FAKE_MODE="copyto-fail")
    assert_failed(result, env, "upload")
    assert "could not reach OneDrive" in result.stderr  # rclone's last useful line is shown
    assert env.calls_of("deletefile") == []
    output = result.stdout + result.stderr
    assert PLACEHOLDER not in output and "Bearer" not in output
    assert list(env.tmpdir.iterdir()) == []  # temp copies deleted after a failure too


def test_list_failure_fails_and_hides_the_token(env: Env) -> None:
    env.dump(minutes_ago=20)
    result = env.run(FAKE_MODE="lsf-fail")
    assert_failed(result, env, "list")
    assert env.uploads() == []
    assert PLACEHOLDER not in result.stdout + result.stderr


def test_size_mismatch_after_upload_fails_and_deletes_nothing(env: Env) -> None:
    env.dump(minutes_ago=20)
    for days in range(40, 50):
        env.remote_copy(dump_name(ub_now() - timedelta(days=days)) + ".age")
    result = env.run(FAKE_MODE="badsize")
    assert_failed(result, env, "verify")
    assert re.search(r"remote \d+ bytes, local \d+ bytes", result.stderr)
    assert env.calls_of("deletefile") == []


def test_rclone_always_gets_config_and_never_verbose_flags(env: Env) -> None:
    env.dump(minutes_ago=60 * 24)
    env.dump(minutes_ago=20)
    assert env.run().returncode == 0
    assert env.calls()
    for call in env.calls():
        assert call[call.index("--config") + 1] == str(env.conf), call
        assert not {"-v", "-vv", "--verbose"} & set(call), call
        assert not any(a.startswith("--dump") for a in call), call


def test_no_ping_url_means_no_curl_and_still_ok(env: Env) -> None:
    env.dump(minutes_ago=20)
    env.env.pop("OFFSITE_PING_URL")
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.pings() == []


# ---- server job: retention ----------------------------------------------------------------------

def copy_name(days_ago: int) -> str:
    return dump_name((ub_now() - timedelta(days=days_ago)).replace(hour=3, minute=0, second=0)) + ".age"


def test_retention_deletes_copies_older_than_30_days_and_keeps_foreign_files(env: Env) -> None:
    for days in range(40):
        env.remote_copy(copy_name(days))
    (env.remote / "db" / "notes.txt").write_text("Ari's note")
    env.dump(minutes_ago=20)
    result = env.run()
    assert result.returncode == 0, result.stderr
    cutoff = (ub_now() - timedelta(days=30)).strftime("%Y-%m-%d")
    deleted = sorted(Path(c[-1]).name for c in env.calls_of("deletefile"))
    assert deleted == sorted(copy_name(d) for d in range(40) if copy_name(d)[11:21] < cutoff)
    assert len(deleted) == 9  # days 31..39
    assert "notes.txt" in env.remote_names()
    assert ", 9 deleted" in result.stderr


def test_retention_always_keeps_the_newest_7(env: Env) -> None:
    for days in range(60, 70):  # 10 copies, all 60+ days old
        env.remote_copy(copy_name(days))
    env.dump(minutes_ago=20)  # + tonight's upload = 11 copies
    result = env.run()
    assert result.returncode == 0, result.stderr
    kept = [n for n in env.remote_names() if n.endswith(".age")]
    assert len(kept) == 7
    assert kept == sorted(kept)[-7:]  # the newest 7 by name
    assert ", 7 kept, 4 deleted" in result.stderr


def test_retention_keeps_everything_when_only_5_old_copies(env: Env) -> None:
    for days in range(60, 65):
        env.remote_copy(copy_name(days))
    env.dump(minutes_ago=20)
    assert env.run().returncode == 0
    assert env.calls_of("deletefile") == []


# ---- systemd units, deploy guide ----------------------------------------------------------------

def test_units_run_at_0320_after_backup_without_starting_it() -> None:
    timer = (ROOT / "deploy" / "systemd" / "ocp-offsite.timer").read_text()
    service = (ROOT / "deploy" / "systemd" / "ocp-offsite.service").read_text()
    assert "OnCalendar=*-*-* 03:20:00 Asia/Ulaanbaatar" in timer
    assert "Persistent=true" in timer and "WantedBy=timers.target" in timer
    assert re.search(r"^After=.*ocp-backup\.service", service, re.M)
    assert not re.search(r"^(Wants|Requires|BindsTo)=.*ocp-backup", service, re.M)
    assert "EnvironmentFile=/root/.config/ocp/offsite.env" in service
    assert "ExecStart=/root/oil-change-predictor/scripts/offsite_backup.sh" in service
    assert "Type=oneshot" in service and "TimeoutStartSec=30min" in service


def test_env_example_holds_names_only() -> None:
    text = (ROOT / "deploy" / "offsite.env.example").read_text()
    assert re.search(r"^OFFSITE_PING_URL=$", text, re.M)
    values = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert values == ["OFFSITE_PING_URL="]  # names only, no real URL


def offsite_guide() -> str:
    text = (ROOT / "docs" / "deploy.md").read_text()
    start = text.index("### Off-server copy")
    return text[start:text.index("\n## ", start)]


def test_deploy_guide_pins_rclone_with_checksum() -> None:
    guide = offsite_guide()
    assert re.search(r"RCLONE_VERSION=v?\d+\.\d+\.\d+", guide)
    assert re.search(r"\b[0-9a-f]{64}\b", guide)
    assert "sha256sum -c" in guide
    assert not re.search(r"apt(-get)? install[^\n]*\brclone\b", guide)


# ---- Mac restore test -----------------------------------------------------------------------------

def encrypted_copy(folder: Path, days_ago: int = 0) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / copy_name(days_ago)
    path.write_bytes(AGE_HEADER + gzip.compress(DUMP.encode())[::-1])
    return path


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "keys" / "ari.key"
    path.parent.mkdir()
    path.write_text("AGE-SECRET-KEY-1FAKE\n")
    return path


def test_restore_prints_only_counts_and_cleans_up(env: Env, key: Path) -> None:
    copy = encrypted_copy(env.tmp / "downloads")
    result = env.run(RESTORE, "--key", str(key), str(copy))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert re.fullmatch(r"dump: oil_change_\S+ \(\d{4}-\d{2}-\d{2}, 0 days old\)", lines[0])
    assert lines[1].split() == ["table", "in_dump", "restored", "result"]
    assert sorted(lines[2:]) == sorted(f"{t:<24} {n:>10} {n:>10}  OK" for t, n in DUMP_COUNTS.items())
    assert "Test Driver" not in result.stdout + result.stderr  # no row data, only counts
    assert "offsite_restore_test: OK, 3 tables" in result.stderr
    assert list(env.tmpdir.iterdir()) == []  # decrypted + encrypted temp files gone
    docker = (env.tmp / "docker.log").read_text()
    assert "--tmpfs /var/lib/postgresql/data" in docker and " -p " not in docker
    assert "rm -f ocp-restore-" in docker


@pytest.mark.parametrize("mode", ["restore-fail", "run-fail"])
def test_restore_failure_still_cleans_up(env: Env, key: Path, mode: str) -> None:
    copy = encrypted_copy(env.tmp / "downloads")
    result = env.run(RESTORE, "--key", str(key), str(copy), FAKE_DOCKER=mode)
    assert result.returncode == 1
    assert "offsite_restore_test: FAILED" in result.stderr
    assert list(env.tmpdir.iterdir()) == []
    assert "rm -f ocp-restore-" in (env.tmp / "docker.log").read_text()


def test_restore_reports_different_counts(env: Env, key: Path) -> None:
    copy = encrypted_copy(env.tmp / "downloads")
    result = env.run(RESTORE, "--key", str(key), str(copy), FAKE_DOCKER="diff")
    assert result.returncode == 1
    assert "DIFFERENT" in result.stdout


def test_restore_of_an_old_dump_is_not_a_pass(env: Env, key: Path) -> None:
    copy = encrypted_copy(env.tmp / "downloads", days_ago=5)
    result = env.run(RESTORE, "--key", str(key), str(copy))
    assert result.returncode == 1
    assert "5 days old" in result.stderr


def test_restore_refuses_a_cloud_synced_temp_folder(env: Env, key: Path) -> None:
    copy = encrypted_copy(env.tmp / "downloads")
    cloud = env.tmp / "Library" / "CloudStorage" / "OneDrive-Personal"
    cloud.mkdir(parents=True)
    result = env.run(RESTORE, "--key", str(key), str(copy), TMPDIR=str(cloud))
    assert result.returncode == 1
    assert "cloud-synced" in result.stderr
    assert not (env.tmp / "docker.log").exists()
    assert list(cloud.iterdir()) == []


def test_restore_downloads_the_newest_copy_with_rclone(env: Env, key: Path) -> None:
    encrypted_copy(env.remote / "db", days_ago=3)
    newest = encrypted_copy(env.remote / "db", days_ago=0)
    result = env.run(RESTORE, "--key", str(key))
    assert result.returncode == 0, result.stderr
    assert [c[-2] for c in env.calls_of("copyto")] == [f"ocp-offsite:db/{newest.name}"]
    assert "top level of ocp-offsite:: db/" in result.stdout
    assert list(env.tmpdir.iterdir()) == []


def test_restore_via_rclone_needs_the_fence(env: Env, key: Path) -> None:
    encrypted_copy(env.remote / "db")
    env.write_conf(fence=False)
    result = env.run(RESTORE, "--key", str(key))
    assert result.returncode == 1
    assert "folder fence missing" in result.stderr
    assert env.calls() == []


def test_restore_needs_a_key(env: Env) -> None:
    result = env.run(RESTORE, str(encrypted_copy(env.tmp / "downloads")))
    assert result.returncode == 1 and "--key" in result.stderr


# ---- shared awk, executables --------------------------------------------------------------------

def test_shared_awk_counts_rows_per_table() -> None:
    out = subprocess.run(["awk", "-f", str(AWK)], input=DUMP, capture_output=True, text=True, check=True)
    assert dict((t, int(n)) for t, n in (line.split() for line in out.stdout.splitlines())) == DUMP_COUNTS


def test_both_restore_scripts_use_the_shared_awk() -> None:
    for script in ("restore_test.sh", "offsite_restore_test.sh"):
        text = (ROOT / "scripts" / script).read_text()
        assert "dump_row_counts.awk" in text, script
        assert "/^COPY /" not in text, script  # the rule lives only in the awk file


def test_offsite_scripts_are_executable() -> None:
    for name in ("offsite_backup.sh", "offsite_restore_test.sh"):
        assert os.access(ROOT / "scripts" / name, os.X_OK), name
