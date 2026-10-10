#!/usr/bin/env python3
"""
scripts/build_release.py
Builds a clean release zip from an explicit allowlist.
Ensures no secrets, environment files (.env), database files (*.db, *.sqlite),
or cache artifacts are included.
"""
from __future__ import annotations

import os
import re
import zipfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
OUTPUT_ZIP = os.path.join(DIST_DIR, "barbershop_bot_release.zip")

ALLOWLIST_TOP_FILES = [
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "alembic.ini",
    "Caddyfile",
    "docker-compose.yml",
    "docker-compose.test.yml",
    "docker-entrypoint.sh",
    "Dockerfile",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "requirements.txt",
]

ALLOWLIST_DIRS = [
    "app",
    "docs",
    "migrations",
    "scripts",
    "tests",
]

FORBIDDEN_FILE_PATTERNS = [
    r"^\.env($|\..*)",  # .env, .env.local, etc. (.env.example is explicitly handled)
    r".*\.db$",
    r".*\.sqlite.*",
    r".*\.pyc$",
    r".*\.log$",
]

FORBIDDEN_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    "dist",
    ".venv",
    "venv",
}

TOKEN_PATTERN = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")


def is_forbidden_file(rel_path: str) -> bool:
    basename = os.path.basename(rel_path)
    if basename == ".env.example":
        return False
    for pat in FORBIDDEN_FILE_PATTERNS:
        if re.search(pat, basename, re.IGNORECASE):
            return True
    return False


def build_release(output_path: str = OUTPUT_ZIP) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)

    files_to_pack: list[tuple[str, str]] = []

    # 1. Top-level files
    for fname in ALLOWLIST_TOP_FILES:
        full_path = os.path.join(PROJECT_ROOT, fname)
        if os.path.exists(full_path):
            files_to_pack.append((full_path, fname))

    # 2. Allowlisted directories
    for dname in ALLOWLIST_DIRS:
        dir_full = os.path.join(PROJECT_ROOT, dname)
        if not os.path.exists(dir_full):
            continue
        for root, dirs, files in os.walk(dir_full):
            dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIR_NAMES]
            for f in files:
                full_f = os.path.join(root, f)
                rel_f = os.path.relpath(full_f, PROJECT_ROOT)
                if not is_forbidden_file(rel_f):
                    files_to_pack.append((full_f, rel_f))

    # Scan and package
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full_path, arcname in sorted(files_to_pack, key=lambda x: x[1]):
            # Verify file content for leaked tokens
            try:
                with open(full_path, "rb") as f_in:
                    content = f_in.read()
                    try:
                        text_content = content.decode("utf-8")
                        if TOKEN_PATTERN.search(text_content):
                            raise ValueError(f"Leaked bot token detected in file: {arcname}")
                    except UnicodeDecodeError:
                        pass
            except Exception as e:
                if "Leaked bot token" in str(e):
                    raise

            zf.write(full_path, arcname)

    print(f"✅ Successfully built release zip with {len(files_to_pack)} files: {output_path}")
    return output_path


if __name__ == "__main__":
    build_release()
