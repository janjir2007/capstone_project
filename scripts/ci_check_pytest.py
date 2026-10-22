"""Decide whether a CI pytest run passed, from its JUnit XML report (task 6.2).

Why not just pytest's exit code:
1. Known flake: after every test has passed, the Python process sometimes aborts while
   native libraries (torch / onnxruntime / OpenMP threads) shut down -> exit code 134
   (SIGABRT). The report is already written by then (pytest writes it when the session
   finishes, before interpreter teardown), so the report is the real result.
2. CI must actually RUN the database and UI tests. They skip themselves when Postgres or
   streamlit is missing, which would silently pass. Here every skip fails the run unless
   its reason matches an allowed, opt-in skip (the real-browser UI test).

Usage (CI):
    pytest -v --junitxml=pytest-report.xml; python -m scripts.ci_check_pytest pytest-report.xml $?
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Exit codes accepted when the report says everything passed: 0 = normal, 134 = abort in native teardown.
ACCEPTED_EXIT_CODES = (0, 134)
# Skips that are allowed in CI (substring of the skip message):
# - tests/test_ui_browser.py needs a real browser + running stack, opt-in by design (UI_BROWSER=1, docs/ui_run.md)
# - tests/test_serving.py real-ONNX checks: model files are git-ignored, so CI never has them
#   (the same code paths run on fake models in the other serving tests)
# - tests/test_seed_demo.py (7.2) and tests/test_zoom_figures.py (7.1e) real-model checks: same reason,
#   models/ is git-ignored; seed_demo and per_char logic are tested on fake/in-memory data elsewhere (8.1b)
ALLOWED_SKIPS = ("opt-in: set UI_BROWSER=1", "exported ONNX files missing",
                 "needs the served model files in models/ (git-ignored)", "needs models/ (git-ignored)")


@dataclass
class Report:
    """Counts from a JUnit XML file."""

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skips: list[str] = field(default_factory=list)  # "test id: message"


def read_report(path: Path) -> Report:
    """Count tests, failures, errors and collect skip messages (all <testsuite> elements)."""
    root = ET.parse(path).getroot()
    report = Report()
    for case in root.iter("testcase"):
        report.tests += 1
        report.failures += len(case.findall("failure"))
        report.errors += len(case.findall("error"))
        for skip in case.findall("skipped"):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            # A module-level skip has message "collection skipped"; its reason is in the element text.
            reason = " ".join(part for part in (skip.get("message"), (skip.text or "").strip()) if part)
            report.skips.append(f"{name}: {reason}")
    return report


def problems(report: Report, exit_code: int) -> list[str]:
    """Everything that makes the run a failure; empty list = passed."""
    found = []
    if exit_code not in ACCEPTED_EXIT_CODES:
        found.append(f"pytest exit code {exit_code}")
    if report.tests == 0:
        found.append("no tests in the report")
    if report.failures or report.errors:
        found.append(f"{report.failures} failed, {report.errors} errors")
    found += [f"unexpected skip: {s}" for s in report.skips if not any(a in s for a in ALLOWED_SKIPS)]
    return found


def main(argv: list[str] | None = None) -> int:
    """CLI: print a summary; exit 1 if the run did not pass."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="JUnit XML from pytest --junitxml")
    parser.add_argument("exit_code", type=int, help="pytest's exit code ($?)")
    args = parser.parse_args(argv)
    if not args.report.exists():
        print(f"ci_check_pytest: {args.report} missing (pytest crashed before the end, exit {args.exit_code})")
        return 1
    report = read_report(args.report)
    print(f"ci_check_pytest: {report.tests} tests, {report.failures} failed, {report.errors} errors, "
          f"{len(report.skips)} skipped, pytest exit {args.exit_code}")
    if args.exit_code == 134:
        print("ci_check_pytest: exit 134 = abort during native teardown after the run (known flake); "
              "judged by the report")
    found = problems(report, args.exit_code)
    for p in found:
        print(f"ci_check_pytest: FAIL: {p}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
