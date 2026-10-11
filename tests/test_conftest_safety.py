import os
import subprocess
import sys


def test_require_pg_fails_on_sqlite():
    env = os.environ.copy()
    env["REQUIRE_PG"] = "1"
    env.pop("TEST_DATABASE_URL", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_review_round2.py",
            "-k",
            "test_B2",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    # When REQUIRE_PG=1 and TEST_DATABASE_URL is not postgresql, conftest raises RuntimeError
    assert proc.returncode != 0
    assert "REQUIRE_PG=1 was specified, but TEST_DATABASE_URL is not PostgreSQL" in proc.stderr or "REQUIRE_PG=1 was specified, but TEST_DATABASE_URL is not PostgreSQL" in proc.stdout


def test_conftest_rejects_non_test_postgres_database():
    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/production_db"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_review_round2.py",
            "-k",
            "test_B2",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0
    assert "must end with '_test'" in proc.stderr or "must end with '_test'" in proc.stdout
