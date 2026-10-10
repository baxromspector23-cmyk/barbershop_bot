from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import build_release

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_NAME_PATTERNS = [
    r"^\.env$",
    r"^\.env\.(?!example).+",
    r".*\.db$",
    r".*\.sqlite.*",
]

TOKEN_REGEX = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "dist",
}


def test_repo_tree_hygiene():
    """Verify that no .env, *.db, *.sqlite*, or token secrets exist anywhere in repo."""
    violations: list[str] = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Exclude ignored dirs in-place
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            file_path = Path(root) / file
            rel_path = file_path.relative_to(PROJECT_ROOT).as_posix()

            # 1. Check filename patterns
            for pat in FORBIDDEN_NAME_PATTERNS:
                if re.match(pat, file, re.IGNORECASE):
                    violations.append(f"Forbidden file pattern '{pat}': {rel_path}")

            # 2. Check file content for real-looking bot tokens
            # Skip binary files, images, etc.
            if file_path.suffix.lower() in [".py", ".md", ".txt", ".json", ".yaml", ".yml", ".ini", ".sh", ".env.example"]:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    matches = TOKEN_REGEX.findall(content)
                    if matches:
                        violations.append(f"Leaked token found in {rel_path}: {matches}")
                except Exception as e:
                    violations.append(f"Error reading {rel_path}: {e}")

    assert not violations, "Repo hygiene violations detected:\n" + "\n".join(violations)


def test_release_zip_hygiene(tmp_path):
    """Verify that the release zip built by build_release contains no forbidden files or secrets."""
    zip_path = tmp_path / "test_release.zip"
    build_release(str(zip_path))

    assert zip_path.exists(), "Release zip was not created"

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        for name in namelist:
            file_name = Path(name).name
            for pat in FORBIDDEN_NAME_PATTERNS:
                assert not re.match(pat, file_name, re.IGNORECASE), f"Forbidden file in zip: {name}"

            # Check contents
            if any(name.endswith(ext) for ext in [".py", ".md", ".txt", ".yaml", ".yml", ".ini"]):
                content = zf.read(name).decode("utf-8", errors="ignore")
                matches = TOKEN_REGEX.findall(content)
                assert not matches, f"Leaked token in zipped file {name}: {matches}"
