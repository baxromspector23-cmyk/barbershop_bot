# Independent Review Remediation Report: `barbershop_bot`

**Date**: 2026-10-10  
**Environment**: Windows (local test runner with Python 3.10, SQLite async + PostgreSQL async schema compatibility)  
**Overall Status**: All 12 review findings (`F1, F2, F3, F4, F5a, F5b, F6, F7, F8, F9, F10a, F10b`) resolved; 80/80 automated tests passing; release zip packaged cleanly without secrets or database files.

---

## 1. Executive Summary & Baseline

### 1.1 Baseline Starting State
- **Previous claim**: Docs previously claimed "100% tested" and "production-ready".
- **Initial review findings test run (`tests/test_review_findings.py`)**:
  - Exactly 12 tests failed: `F1, F2, F3, F4, F5a, F5b, F6, F7, F8, F9, F10a, F10b`.
  - Sensitive files detected: `.env` with BotFather token, SQLite files `barbershop.db` and `simulated_day.db`.
  - Host ports `5432` and `6379` exposed in `docker-compose.yml`, weak default secrets, silent SQLite fallback in production.

### 1.2 Ground Rules Compliance
1. **Test-First**: Each defect was evaluated with red/green reproduction tests.
2. **Never Weaken Review Tests**: `tests/test_review_findings.py` copied verbatim; zero assertions modified or softened.
3. **No Secrets**: Compromised `.env` deleted; strict `.gitignore` and `.dockerignore` established; `scripts/build_release.py` scans for tokens matching `\b\d{8,10}:[A-Za-z0-9_-]{35}\b`.
4. **No Scope Creep**: Queue mechanics, business logic, and UI flows strictly preserved according to specification.
5. **Honesty Rule**: No false "100%" or "production-ready" claims; technical limitations documented in `docs/KNOWN_LIMITATIONS.md`; unverified host tasks explicitly identified.

---

## 2. Findings & Remediation Matrix

| Finding ID | Priority | Status | Files Changed | Associated Tests | Remediation Summary & Evidence |
| :--- | :---: | :---: | :--- | :--- | :--- |
| **S1** | P0 | **FIXED** | `.gitignore`, `.dockerignore`, `docker-compose.yml`, `scripts/build_release.py`, `tests/test_repo_hygiene.py` | `test_repo_tree_hygiene`, `test_release_zip_hygiene` | Removed all `.env` and `*.db` files. Hardened compose (internal network only, required Postgres password, Redis `--requirepass`, non-root user). Added release packager with allowlist and token leak scanner. |
| **M1** (`F1`) | P1 | **FIXED** | `app/handlers/barber.py`, `app/handlers/client.py` | `test_f1_prepaid_client_no_second_pay_prompt`, `test_f1_pay_after_client_still_gets_keyboard` | Prepaid clients whose order already has `status == PAID` receive a thank-you receipt after service completion. Only pay-after clients receive payment method keyboards. |
| **M2** (`F5b`) | P1 | **FIXED** | `app/handlers/payments.py` | `test_f5b_pre_checkout_strict_validation`, `test_f5b_pre_checkout_reject_reasons_and_accept` | `handle_pre_checkout` validates currency (UZS only), price * 100, payer ID matching client ID, order existence, non-cancelled order status, and non-duplicate payment. |
| **M3** (`F5a`) | P1 | **FIXED** | `app/models/payment.py`, `app/repositories/payment.py`, `app/services/payment_service.py`, `migrations/versions/002_*.py` | `test_f5a_second_payment_creates_distinct_refund_row`, `test_f5a_same_id_idempotency`, `test_f5a_duplicate_charge_not_counted_in_revenue_reports`, `test_f5a_payment_on_dead_order` | Idempotent on identical `(method, provider_payment_id)`. Distinct charge on already `PAID` or dead order is saved as separate payment row with status `REFUND_PENDING` and audit reason, excluded from revenue reports. Primary payment lookup returns first `PAID` payment. |
| **M4** (`F4`) | P1 | **FIXED** | `app/handlers/client.py`, `app/handlers/payments.py`, `app/keyboards/client.py` | `test_f4_fake_payment_blocked_in_production`, `test_f4_client_callbacks_order_ownership` | FAKE payment is removed from keyboards and blocked in handlers unless `PAYMENTS_MODE=="test"` and `ENV!="production"`. All client callbacks carrying `order_id` verify order ownership. |
| **M5** (`F7`) | P1 | **FIXED** | `app/services/queue_service.py`, `app/services/due_work_service.py` | `test_f7_cancellation_paid_order_refund_pending`, `test_f7_staff_cancel_prepaid_order_refund_pending`, `test_f7_3rd_lateness_prepaid_order_refund_pending` | Any transition of a prepaid order into CANCELLED/EXPIRED marks payment as `REFUND_PENDING`, alerts the owner, and notifies the client. |
| **A1** (`F2`) | P2 | **FIXED** | `app/services/authorization.py`, `app/handlers/barber.py` | `test_f2_foreign_barber_cash_guard` | Enforced service-layer authorization via `assert_can_manage_order`. Foreign barber cannot mark cash payment. |
| **A2** (`F3`) | P2 | **FIXED** | `app/services/authorization.py`, `app/handlers/barber.py` | `test_f3_foreign_barber_service_toggle_guard` | Enforced service-layer authorization via `assert_can_manage_service`. Foreign barber cannot toggle another barber's service. |
| **A3** (`F9`) | P2 | **FIXED** | `app/services/authorization.py`, `app/handlers/barber.py` | `test_f9_barber_callback_authorization` | Applied authorization checks across all barber callbacks (`b_arrived`, `b_done`, `b_cancel`, `b_noshow`, `walkin_svc`). |
| **A4** | P2 | **FIXED** | `app/handlers/barber.py`, `app/services/authorization.py` | `tests/test_permissions.py` | Guarded `add_svc_prompt` and `AddServiceSG` handlers. When `ALLOW_BARBER_EDIT_OWN_SERVICES=false`, non-owner staff attempts are rejected. |
| **C1** (`F8`) | P3 | **FIXED** | `app/config.py` | `test_f8_validate_runtime_production_checks` | `validate_runtime()` in production validates `OWNER_TELEGRAM_IDS`, secret lengths (>=32 chars), Postgres dialect requirement, absence of `FAKE`, and disallowance of `PAYNET_ENABLED=true`, collecting and reporting all errors simultaneously. |
| **C2** | P3 | **FIXED** | `app/db/session.py` | `test_c2_sqlite_crash_in_production` | Silent fallback to SQLite removed. If dialect is SQLite when `ENV=="production"`, engine initialization raises `RuntimeError`. |
| **C3** | P3 | **FIXED** | `app/web/server.py` | `test_c3_secrets_timing_attack_protection` | Constant-time comparison using `hmac.compare_digest` applied to `X-Cron-Secret` and `X-Telegram-Bot-Api-Secret-Token`. |
| **C4** | P3 | **FIXED** | `app/web/server.py` | `test_c4_health_endpoint_no_env_leak` | `/health` returns `{status: "ok", db: "ok"}` without exposing environment names or configuration internals. |
| **D1** (`F10a`) | P4 | **FIXED** | `app/models/base.py`, `app/models/order.py`, `app/models/payment.py` | `test_f10a_timestamps_utc_and_timezone_aware` | Implemented `UtcDateTime` SQLAlchemy TypeDecorator guaranteeing all timestamp columns are saved and loaded as timezone-aware UTC `datetime` objects. |
| **D2** (`F6`) | P4 | **FIXED** | `app/models/order.py`, `app/services/due_work_service.py` | `test_f6_owner_alert_spam_prevented` | Stale `IN_SERVICE` orders persist `stale_alerted_at` timestamp. Subsequent 15s ticks do not spam owner alerts. |
| **D3** (`F10b`) | P4 | **FIXED** | `app/repositories/order.py` | `test_f10b_locked_read_sees_latest_committed_state` | `get_by_id(..., for_update=True)` uses `populate_existing=True` to prevent stale entity cache reads under concurrent transactions. |
| **O1** | Product | **FIXED** | `app/handlers/owner.py`, `app/handlers/barber.py`, `app/repositories/barber.py` | `test_owner_add_service_validation`, `test_service_price_historical_snapshot` | Added service creation validation (`price > 0`, `duration 5..480 min`). Confirmed orders preserve historical price/duration snapshots regardless of subsequent service edits. |
| **O2** | Product | **FIXED** | `app/handlers/owner.py`, `app/repositories/barber.py`, `app/services/queue_service.py` | `test_barber_management_card_metrics`, `test_barber_deactivation_policy`, `test_owner_revoke_barber_admin` | Barber management card displays phone, username, queue count, and revenue. Deactivated barbers are hidden from new joins while existing queues finish. Revocation downgrades role to `CLIENT`. |
| **O3** | Product | **FIXED** | `app/handlers/owner.py`, `app/services/queue_service.py` | `test_owner_working_hours_view_and_toggle`, `test_client_join_outside_working_hours_rejected` | Owner schedule UI allows day-off toggles and custom time spans. Out-of-hours joins rejected with localized notice. |
| **O4** | Product | **FIXED** | `app/keyboards/client.py`, `app/config.py`, `docs/PAYMENTS.md` | `test_o4_paynet_disabled_and_hidden` | Paynet button hidden from keyboards unless `PAYNET_ENABLED=true`. Blocked in production runtime validation. Full contract requirements documented. |
| **Q1** | Quality | **FIXED** | `docker-compose.test.yml`, `tests/test_alembic_drift.py`, `Makefile` | `test_alembic_schema_matches_models` | Parity verified between `Base.metadata` and Alembic migration head. Test compose configured. Local execution without Docker daemon noted under Unverified. |
| **Q2** | Quality | **FIXED** | `app/handlers/*.py`, `app/i18n/*.yaml`, `tests/test_no_hardcoded_strings.py`, `tests/test_i18n.py` | `test_no_hardcoded_strings_in_handlers`, `test_i18n_keys_match_across_catalogs` | Static AST audit verifies zero hardcoded literal strings in user-facing message calls. 100% key and placeholder parity across `uz`, `uz_cyrl`, and `ru`. |
| **Q3** | Quality | **FIXED** | `README.md`, `docs/DECISIONS.md`, `docs/KNOWN_LIMITATIONS.md`, `pyproject.toml`, `scripts/build_release.py` | `test_repo_tree_hygiene` | Removed all false "100%" and "production-ready" claims. Created comprehensive technical limitations guide. |
| **Q4** | Quality | **FIXED** | `scripts/simulate_day.py` | Script execution exit code 0 | `scripts/simulate_day.py` executes in temp directory and cleans up database artifacts in `finally` block. |

---

## 3. Test Suite & Verification Results

### 3.1 Pytest Execution Summary
```
tests/test_alembic_drift.py .                                            [  1%]
tests/test_barber_management.py ...                                      [  5%]
tests/test_concurrency.py .                                              [  6%]
tests/test_config_and_security.py ....                                   [ 11%]
tests/test_due_work.py ...                                               [ 15%]
tests/test_i18n.py ..                                                    [ 17%]
tests/test_lateness.py ...                                               [ 21%]
tests/test_no_hardcoded_strings.py .                                     [ 22%]
tests/test_owner_services_management.py ...                              [ 26%]
tests/test_payments.py .....                                             [ 32%]
tests/test_permissions.py ..                                             [ 35%]
tests/test_queue.py .....                                                [ 41%]
tests/test_repo_hygiene.py ..                                            [ 43%]
tests/test_reports.py .                                                  [ 45%]
tests/test_review_findings.py ........................................   [ 95%]
tests/test_serverless.py ..                                              [ 97%]
tests/test_working_hours_ui.py ..                                        [100%]

============================= 80 passed in 30.28s =============================
```

### 3.2 Linter (`ruff check .`)
```
All checks passed!
```

### 3.3 Repo & Packaging Hygiene (`tests/test_repo_hygiene.py`)
```
============================== 2 passed in 0.29s ==============================
- test_repo_tree_hygiene: PASSED (Zero .env, *.db, *.sqlite*, or token secrets in project tree)
- test_release_zip_hygiene: PASSED (Release zip contains 100 clean allowlisted files; zero leaks)
```

---

## 4. NOT VERIFIED List (Transparent Operational Disclosure)

In accordance with Ground Rule 5 (Honesty Rule):
1. **Docker Container Execution on Host Machine**: The local development machine does not have an active Docker daemon. Docker Compose orchestration, container non-root user execution, and container startup (`make test-pg`) have not been run against a local daemon.
2. **Live Bank Card Charges**: Actual bank card debiting via Click and Payme requires live production provider tokens issued by BotFather connected to an authorized merchant bank account. Real financial settlement was not executed in real money; behavior was validated using Telegram Payments protocol test fixtures and verified sandbox schemas.
3. **Paynet Production Merchant Gateway**: Paynet direct billing requires a signed merchant contract, VPN/static IP whitelisting, and Paynet protocol certification. The adapter is implemented as an interface and intentionally disabled for production runtime.
