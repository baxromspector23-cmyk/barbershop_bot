"""Validates the accuracy and integrity of docs/FIX_REPORT.md.

Ensures:
1. Every backticked `test_*` name cited in docs/FIX_REPORT.md actually exists in tests/.
2. Every backticked file path cited in docs/FIX_REPORT.md actually exists in the repository.
3. No forbidden buzzwords ('100% tested', 'production-ready', etc.) exist in the report.
4. Dependency versions quoted in docs/FIX_REPORT.md match requirements.txt and requirements.lock.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_FILE = ROOT / "docs" / "FIX_REPORT.md"

FORBIDDEN_PATTERNS = [
    re.compile(r"\b100%\s*tested\b", re.IGNORECASE),
    re.compile(r"\bproduction-ready\b", re.IGNORECASE),
    re.compile(r"\b100%\s*production\b", re.IGNORECASE),
]

TEST_NAME_RE = re.compile(r"`(test_[A-Za-z0-9_]+)`")

PATH_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_./-]+\.(?:py|md|yml|yaml|txt|lock|sh|toml)|[A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+|\.env\.example|\.gitignore|\.dockerignore|Makefile|Dockerfile)`"
)

DEP_VERSION_RE = re.compile(r"`([a-zA-Z0-9_-]+)(>=|==)([0-9][a-zA-Z0-9._-]*)`")


def collect_existing_tests() -> set[str]:
    existing: set[str] = set()
    tests_dir = ROOT / "tests"
    for py_file in tests_dir.glob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        existing.add(node.name)
        except Exception as e:
            print(f"Warning: could not parse {py_file}: {e}")
    return existing


def validate_dependencies(content: str, errors: list[str]) -> int:
    req_file = ROOT / "requirements.txt"
    lock_file = ROOT / "requirements.lock"
    if not req_file.exists() or not lock_file.exists():
        errors.append("requirements.txt or requirements.lock missing!")
        return 0

    req_text = req_file.read_text(encoding="utf-8")
    lock_text = lock_file.read_text(encoding="utf-8")

    matches = DEP_VERSION_RE.findall(content)
    checked_count = 0

    for pkg, op, ver in matches:
        if op == ">=":
            checked_count += 1
            m = re.search(rf"^{re.escape(pkg)}(?:\[[^\]]*\])?\s*>=\s*([0-9][^\s,;#]*)", req_text, re.I | re.M)
            if not m:
                errors.append(f"Report quotes dependency `{pkg}>={ver}`, but `{pkg}` is not found with lower bound in requirements.txt")
            elif m.group(1) != ver:
                errors.append(f"Report quotes `{pkg}>={ver}`, but requirements.txt specifies >={m.group(1)}")
        elif op == "==":
            checked_count += 1
            m = re.search(rf"^{re.escape(pkg)}==([0-9][^\s;#]*)", lock_text, re.I | re.M)
            if not m:
                errors.append(f"Report quotes pinned dependency `{pkg}=={ver}`, but `{pkg}` is not pinned in requirements.lock")
            elif m.group(1) != ver:
                errors.append(f"Report quotes `{pkg}=={ver}`, but requirements.lock pins =={m.group(1)}")

    return checked_count


def validate_report() -> bool:
    if not REPORT_FILE.exists():
        print(f"FAIL: Report file not found at {REPORT_FILE}")
        return False

    content = REPORT_FILE.read_text(encoding="utf-8")
    errors: list[str] = []

    # 1. Check forbidden buzzwords
    for pat in FORBIDDEN_PATTERNS:
        matches = pat.findall(content)
        if matches:
            errors.append(f"Forbidden buzzword pattern found ({pat.pattern}): {matches}")

    # 2. Check test names
    existing_tests = collect_existing_tests()
    cited_tests = set(TEST_NAME_RE.findall(content))

    missing_tests = sorted(t for t in cited_tests if t not in existing_tests)
    if missing_tests:
        errors.append(f"Cited test names that DO NOT exist in tests/ ({len(missing_tests)}): {missing_tests}")

    # 3. Check file paths
    raw_paths = set(PATH_TOKEN_RE.findall(content))
    missing_paths: list[str] = []
    checked_paths: list[str] = []

    for p in sorted(raw_paths):
        # Ignore placeholders, URLs, glob patterns
        if "*" in p or "://" in p or "<" in p or "USER" in p or "HOST" in p:
            continue
        cleaned = p.strip("/")
        target = ROOT / cleaned
        if not target.exists():
            missing_paths.append(p)
        else:
            checked_paths.append(p)

    if missing_paths:
        errors.append(f"Cited file paths that DO NOT exist in repo ({len(missing_paths)}): {missing_paths}")

    # 4. Check quoted dependency versions
    checked_deps = validate_dependencies(content, errors)

    if errors:
        print("FAIL: docs/FIX_REPORT.md verification failed:")
        for err in errors:
            print(f"  - {err}")
        return False

    print(
        f"OK: docs/FIX_REPORT.md verified cleanly.\n"
        f"  - {len(cited_tests)} cited test names verified existing in tests/\n"
        f"  - {len(checked_paths)} cited file paths verified on disk\n"
        f"  - {checked_deps} quoted dependency version references verified against requirements.txt and requirements.lock\n"
        f"  - Zero forbidden buzzwords detected."
    )
    return True


if __name__ == "__main__":
    if not validate_report():
        sys.exit(1)
