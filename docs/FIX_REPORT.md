# Task 10 (Round 8) Fix & Verification Report

This report documents the implementation and verification of the owner-only read-only client website (`app/site/app.py`, `app/site/security.py`), verified against the read-only reviewer test suite `tests/test_review_round8.py` (SHA-256 `e02e1e9ed51df62fc01d3e943f3d1dbf86d0a8077e00bf64b1a7c4900a3d93a3`) as well as all prior review suites (`tests/test_review_round1.py`, `tests/test_review_round2.py`, `tests/test_review_round3.py`, `tests/test_review_round4.py`, `tests/test_review_round6.py`).

---

## 1. Summary of Changes in Task 10

1. **Repository Methods (`app/repositories/user_repo.py`, `app/repositories/order_repo.py`)**:
   - Implemented `UserRepository.search_clients(query, limit=10)`: filters strictly by `UserRole.CLIENT`, strips leading `@`, strips NUL characters (`\x00`), truncates to 100 characters, normalizes phone queries (3+ digits) against stored phones with spaces/dashes/plus/brackets removed, and escapes `%`, `_`, and `\` for case-insensitive substring matching on `first_name`, `last_name`, and `username`. Verified by `test_R1_search_clients`.
   - Implemented `OrderRepository.get_client_visits(client_id, limit=10, offset=0)` and `OrderRepository.get_client_visit_stats(client_id)` returning completed orders newest first by `completed_at` and `(visit_count, total_price)`. Verified by `test_R2_visits_and_stats`.

2. **Password Hashing (`app/site/security.py`, `scripts/make_site_password_hash.py`)**:
   - Implemented `hash_password`, `verify_password`, and `is_valid_hash_format` using stdlib `hashlib.scrypt` with a 16-byte random salt (`scrypt$16384$8$1$<salt_hex>$<hash_hex>`) and constant-time comparison via `hmac.compare_digest`. Malformed hashes or empty inputs safely return `False` without raising exceptions. Verified by `test_S1_password_hashing`.
   - Created `scripts/make_site_password_hash.py` to prompt twice with `getpass` (minimum 12 characters) and output `SITE_PASSWORD_HASH` and `SITE_SESSION_SECRET`.

3. **Owner-Only Read-Only Website (`app/site/app.py`)**:
   - Implemented `create_site_app(session_factory, *, username, password_hash, secret, secure_cookies=True, now=time.time, trust_proxy=False)` exposing exclusively `GET /login`, `POST /login`, `POST /logout`, `GET /`, `GET /clients`, and `GET /clients/{id}`.
   - Enforced server-side sessions (SHA-256 of 32-byte random token, 8-hour absolute expiry via injected `now()`), `HttpOnly; SameSite=Strict` cookies (`Secure` when `secure_cookies=True`), HMAC-SHA256 CSRF protection on `/login` and `/logout`, constant-time login checks, and IP/global brute-force lockouts (5 failures per IP or 30 global failures within 15 minutes -> HTTP 429 with `Retry-After`).
   - Added strict security headers (`Cache-Control: no-store`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Content-Security-Policy` with `default-src 'self'; form-action 'self'; frame-ancestors 'none'`), `<meta name="robots" content="noindex">`, full HTML escaping on all user-controlled values, Tashkent timezone formatting (`dd.mm.yyyy HH:MM`), and `audit_log` entries (`SITE_LOGIN_OK`, `SITE_LOGIN_FAIL`, `SITE_LOGIN_LOCKED`, `SITE_LOGOUT`, `SITE_CLIENT_VIEW`).
   - Verified by `test_S2_anonymous_gets_no_data_and_site_is_read_only`, `test_S3_login_success_failure_and_cookie_flags`, `test_S4_csrf_is_required_on_login_and_logout`, `test_S5_brute_force_lockout_then_recovery`, `test_S6_session_expires_and_logout_kills_it_server_side`, `test_S7_clients_page_content_escaping_search_and_headers`, `test_S8_client_card_dates_prices_pagination_and_404`, and `test_S9_audit_log_never_contains_secrets`.

4. **Configuration, Startup & Deployment (`app/config.py`, `.env.example`, `app/main.py`, `Caddyfile`, `docker-compose.yml`, `docs/SITE.md`)**:
   - Added `SITE_ENABLED=false`, `SITE_USERNAME=owner`, `SITE_PASSWORD_HASH=`, `SITE_SESSION_SECRET=`, `SITE_SECURE_COOKIES=true`, `SITE_TRUST_PROXY=false`, and `SITE_PORT=8081` to `app/config.py` and `.env.example`.
   - Updated `Settings.validate_runtime()` to validate `SITE_USERNAME`, `SITE_PASSWORD_HASH`, `SITE_SESSION_SECRET`, and `SITE_SECURE_COOKIES` when `SITE_ENABLED=True`. Verified by `test_S10_site_settings_defaults_and_production_rules`.
   - Updated `app/main.py` to start the site on `HOST:SITE_PORT` in both `webhook` and `polling` modes when `SITE_ENABLED=True` and clean it up on shutdown.
   - Added `{$SITE_DOMAIN:site.localhost}` reverse-proxy block to `Caddyfile` (`app:8081`), kept port `8081` unexposed on the host in `docker-compose.yml`, and documented operations in `docs/SITE.md`.

---

## 2. Verification of All 6 Reviewer Test Files (Python 3.12)

All six read-only reviewer test files were verified byte-for-byte with `scripts/verify_review_tests.py`:

```text
Python 3.12.10
OK: tests/test_review_round1.py verified (721a82f0...)
OK: tests/test_review_round2.py verified (604e60f7...)
OK: tests/test_review_round3.py verified (a25d3d47...)
OK: tests/test_review_round4.py verified (f7ae5205...)
OK: tests/test_review_round6.py verified (9f049c99...)
OK: tests/test_review_round8.py verified (e02e1e9e...)
All review test files verified byte-for-byte.
```

---

## 3. Round 8 Reviewer Tests: Failing First, Then Passing

### 3.1 Failing First (Before Implementation, Python 3.12)

```text
Python 3.12.10
FAILED tests/test_review_round8.py::test_R1_search_clients - AttributeError: 'UserRepository' object has no attribute 'search_clients'
FAILED tests/test_review_round8.py::test_R2_visits_and_stats - AttributeError: 'OrderRepository' object has no attribute 'get_client_visits'
FAILED tests/test_review_round8.py::test_S1_password_hashing - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S2_anonymous_gets_no_data_and_site_is_read_only - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S3_login_success_failure_and_cookie_flags - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S4_csrf_is_required_on_login_and_logout - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S5_brute_force_lockout_then_recovery - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S6_session_expires_and_logout_kills_it_server_side - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S7_clients_page_content_escaping_search_and_headers - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S8_client_card_dates_prices_pagination_and_404 - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S9_audit_log_never_contains_secrets - ModuleNotFoundError: No module named 'app.site'
FAILED tests/test_review_round8.py::test_S10_site_settings_defaults_and_production_rules - ModuleNotFoundError: No module named 'app.site'
============================= 12 failed in 3.63s ==============================
```

### 3.2 Passing After Implementation (Python 3.12)

```text
Python 3.12.10
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\1\.gemini\antigravity\scratch\barbershop_bot
configfile: pyproject.toml
plugins: asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 12 items

tests/test_review_round8.py::test_R1_search_clients PASSED               [  8%]
tests/test_review_round8.py::test_R2_visits_and_stats PASSED             [ 16%]
tests/test_review_round8.py::test_S1_password_hashing PASSED             [ 25%]
tests/test_review_round8.py::test_S2_anonymous_gets_no_data_and_site_is_read_only PASSED [ 33%]
tests/test_review_round8.py::test_S3_login_success_failure_and_cookie_flags PASSED [ 41%]
tests/test_review_round8.py::test_S4_csrf_is_required_on_login_and_logout PASSED [ 50%]
tests/test_review_round8.py::test_S5_brute_force_lockout_then_recovery PASSED [ 58%]
tests/test_review_round8.py::test_S6_session_expires_and_logout_kills_it_server_side PASSED [ 66%]
tests/test_review_round8.py::test_S7_clients_page_content_escaping_search_and_headers PASSED [ 75%]
tests/test_review_round8.py::test_S8_client_card_dates_prices_pagination_and_404 PASSED [ 83%]
tests/test_review_round8.py::test_S9_audit_log_never_contains_secrets PASSED [ 91%]
tests/test_review_round8.py::test_S10_site_settings_defaults_and_production_rules PASSED [100%]

============================= 12 passed in 5.42s ==============================
```

---

## 4. Linter & Dependencies Check (Python 3.12)

No new third-party dependencies were added (`aiohttp>=3.9.5` in `requirements.txt` and `aiohttp==3.14.5` in `requirements.lock` are used alongside Python 3.12 stdlib `hashlib.scrypt`). `ruff check .` passes with zero errors:

```text
Python 3.12.10
All checks passed!
```

---

## 5. Alembic Upgrade Head & Check on Empty DB (Python 3.12)

```text
Python 3.12.10
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001_initial_schema, initial_schema
INFO  [alembic.runtime.migration] Running upgrade 001_initial_schema -> 002_refund_and_stale, refund_reason_and_stale_alerted_at
INFO  [alembic.runtime.migration] Running upgrade 002_refund_and_stale -> 003_schema_indexes_and_parity, schema_indexes_and_parity
INFO  [alembic.runtime.migration] Running upgrade 003_schema_indexes_and_parity -> 004_drop_barbers_user_id_key, drop redundant barbers_user_id_key constraint
INFO  [alembic.runtime.migration] Running upgrade 004_drop_barbers_user_id_key -> 005_manual_transfer_receipts, manual card-transfer payments: receipt photo columns
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
No new upgrade operations detected.
```

---

## 6. Live Site Verification with `curl` (Python 3.12)

Started the site with `ENV=development`, `SITE_ENABLED=true`, `SITE_SECURE_COOKIES=false`, `RUN_MODE=polling` on SQLite and verified all 5 HTTP flows with `curl.exe`:

```text
Python 3.12.10
=== 1. GET /clients (unauthenticated -> 303 to /login) ===
HTTP/1.1 303 See Other
Content-Type: text/plain; charset=utf-8
Location: /login
Cache-Control: no-store
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'
Content-Length: 14
Date: Fri, 16 Oct 2026 11:46:27 GMT
Server: Python/3.12 aiohttp/3.9.5

=== 2. POST /login wrong password (attempt 1 -> 401) ===
HTTP/1.1 401 Unauthorized
Content-Type: text/html; charset=utf-8
Cache-Control: no-store
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'
Content-Length: 2700
Date: Fri, 16 Oct 2026 11:46:27 GMT
Server: Python/3.12 aiohttp/3.9.5

=== 3. POST /login 6th attempt -> 429 Too Many Requests ===
HTTP/1.1 429 Too Many Requests
Retry-After: 900
Content-Type: text/html; charset=utf-8
Cache-Control: no-store
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'
Content-Length: 2742
Date: Fri, 16 Oct 2026 11:46:28 GMT
Server: Python/3.12 aiohttp/3.9.5

=== 4. POST /login correct password -> 303 See Other & Set-Cookie flags ===
HTTP/1.1 303 See Other
Content-Type: text/plain; charset=utf-8
Location: /clients
Cache-Control: no-store
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'
Content-Length: 14
Set-Cookie: site_session=mkFYsHyw4C9KvRppCXWQzQBPZzYv4TKQDBK1kJ1ZoL0; HttpOnly; Max-Age=28800; Path=/; SameSite=Strict
Date: Fri, 16 Oct 2026 11:46:28 GMT
Server: Python/3.12 aiohttp/3.9.5

=== 5. GET /clients with session cookie -> 200 OK & security headers ===
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Cache-Control: no-store
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'
Content-Length: 2637
Date: Fri, 16 Oct 2026 11:46:28 GMT
Server: Python/3.12 aiohttp/3.9.5

<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Mijozlar ro&#x27;yxati</title>
```

---

## 7. Full Test Suite on SQLite (Python 3.12)

The complete test suite (237 tests total: 223 passed, 14 skipped for PostgreSQL-specific concurrency/load tests) passed on SQLite:

```text
Python 3.12.10
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\1\.gemini\antigravity\scratch\barbershop_bot
configfile: pyproject.toml
testpaths: tests
plugins: asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 237 items

tests\test_alembic_drift.py .s                                           [  0%]
tests\test_barber_management.py ...                                      [  2%]
tests\test_button_styles.py ..........                                   [  6%]
tests\test_client_registration_and_info.py ...                           [  7%]
tests\test_concurrency.py .                                              [  8%]
tests\test_config_and_security.py ....                                   [  9%]
tests\test_conftest_safety.py ..                                         [ 10%]
tests\test_due_work.py ...                                               [ 11%]
tests\test_i18n.py ..                                                    [ 12%]
tests\test_lateness.py ...                                               [ 13%]
tests\test_manual_payments.py ........ss..................               [ 25%]
tests\test_no_hardcoded_strings.py .                                     [ 26%]
tests\test_owner_services_management.py ...                              [ 27%]
tests\test_payment_hardening.py ...                                      [ 28%]
tests\test_payments.py .....                                             [ 30%]
tests\test_permissions.py ..                                             [ 31%]
tests\test_phone.py .....................                                [ 40%]
tests\test_queue.py .....                                                [ 42%]
tests\test_repo_hygiene.py ..                                            [ 43%]
tests\test_reports.py .                                                  [ 43%]
tests\test_review_findings.py ........................................   [ 60%]
tests\test_review_round1.py ............                                 [ 65%]
tests\test_review_round2.py ssssss...................                    [ 76%]
tests\test_review_round3.py ..ss                                         [ 78%]
tests\test_review_round4.py .....                                        [ 80%]
tests\test_review_round6.py ...........................sss               [ 92%]
tests\test_review_round8.py ............                                 [ 97%]
tests\test_serverless.py ..                                              [ 98%]
tests\test_working_hours_ui.py ...                                       [100%]

================= 223 passed, 14 skipped in 233.76s (0:03:53) =================
```

---

## 8. PostgreSQL Suite

NOT RUN — PostgreSQL 16 server is not installed/running on this local Windows workstation. All 223 non-PG-specific tests (including all 12 tests in `tests/test_review_round8.py`) passed on SQLite.

---

## 9. Report Validation (Python 3.12)

```text
Python 3.12.10
OK: docs/FIX_REPORT.md verified cleanly.
```
