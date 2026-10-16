"""Smoke tests: prove the test system and the repo skeleton work.

These are placeholders until real code exists. They check two things that
must stay true for the whole project: the right Python version, and that the
agreed folder structure (PROJECT_STATE.md §8) is present.
"""

import sys
from pathlib import Path

# Project root = the folder that contains tests/
ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = [
    "data",
    "src/common",
    "src/data",
    "src/ml",
    "src/cv",
    "src/api",
    "src/ui",  # Streamlit frontend; the empty frontend/ placeholder was removed (D-056)
    "notebooks",
    "models",
    "tests",
    "docs",
]


def test_python_version_is_3_11() -> None:
    """The project standard is Python 3.11 (same locally, in CI and in Docker)."""
    assert sys.version_info[:2] == (3, 11)


def test_repo_structure_exists() -> None:
    """Every folder from the agreed repo structure exists."""
    missing = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    assert missing == [], f"Missing folders: {missing}"
