# Known Limitations & Technical Realities (docs/KNOWN_LIMITATIONS.md)

This document provides a factual, honest overview of current system boundaries, external dependencies, and operational requirements for `barbershop_bot`.

---

## 1. Paynet Integration Status
- **Current State**: Telegram BotFather does not have a native in-app provider integration for Paynet.
- **Merchant Contract Required**: Integrating Paynet into production requires an official merchant contract with Paynet PJSC, signed NDA, protocol specification, and static IP whitelisting.
- **Safety Enforcement**:
  - `PAYNET_ENABLED=true` is strictly blocked in production runtime validation (`Settings.validate_runtime()`).
  - The `PaynetProvider` adapter serves as an extensible HTTP client template for when production merchant credentials and webhook URLs are provisioned.
  - Paynet payment options are automatically hidden from user keyboards when disabled.

---

## 2. Telegram Payments: Test vs Live Credentials
- **Test Mode**: In `PAYMENTS_MODE=test`, test provider tokens from BotFather and test card numbers are accepted. FAKE instant payments are permitted only when `PAYMENTS_MODE=test` and `ENV!=production`.
- **Live Mode**: In `PAYMENTS_MODE=live`:
  - FAKE payments are rejected at startup and hidden from all menus.
  - BotFather provider tokens must be live production tokens (not starting with `:TEST:`).
  - All online transactions settle directly into the barbershop's single merchant bank account.

---

## 3. Database Engine: SQLite vs PostgreSQL
- **Development & Testing**: SQLite with `aiosqlite` is permitted solely for local development (`ENV in {"dev", "test"}`) and fast automated unit tests.
- **Production**: Production **strictly requires PostgreSQL 16+** with `asyncpg` (`postgresql+asyncpg://...`).
- **Safety Enforcement**: Any attempt to start production with SQLite or any non-Postgres dialect immediately raises a fatal `RuntimeError` (`Silent SQLite fallback is eliminated`).

---

## 4. Single-Tenant Architecture
- The bot is designed and structured for a **single barbershop business** with multiple barbers (e.g., 1 owner/katta barber + 3 small barbers).
- It is not designed as a multi-tenant SaaS. All barbers belong to one establishment, and all online payments route to the business owner's merchant account.

---

## 5. Background Scheduler & Lateness Progression
- Automatic 10-minute lateness progression, 3rd no-show cancellations, and stale order alerts rely on `process_due_work()` being executed periodically (every 15 seconds).
- In standalone Docker or VPS mode, this is handled by APScheduler when `INTERNAL_SCHEDULER=true`.
- In serverless setups (such as Google Cloud Run), an external scheduler (e.g. Google Cloud Scheduler or cron) must hit `POST /internal/tick` with header `X-Cron-Secret`.

---

## 6. Manual Refund Processing
- When an order with a paid online transaction is cancelled (by client, staff, 3rd lateness, or end-of-day expiry), the system records the payment as `REFUND_PENDING` with an audit reason.
- Telegram Payments does not execute automated bank account clawbacks.
- The owner is notified with the transaction details (order ID, amount, provider charge ID) and must disburse the refund via the Click/Payme merchant portal, then acknowledge it in the bot panel via "Qaytarildi" (`mark_refunded`).

---

## 7. Intentionally Uzbek-Only Elements
- **Fallback Entity Names**: Fallback names `"Mijoz"` (for deleted or walk-in client records without a display nickname) and `"Barber"` (when a referenced barber profile is inaccessible or deleted) in `app/utils/formatting.py`, `app/models/order.py`, `app/handlers/barber.py`, and `app/handlers/owner.py` are intentionally preserved in Uzbek Latin as domain-standard terminology for the local business establishment.
- **Administrative CSV Export Headers**: The CSV export header row in `app/services/report_service.py` (`"Sana,Barber,Mijoz,Xizmat,Summa,Usul,Holat"`) is intentionally maintained in Uzbek Latin to match local accounting/bookkeeping software imports (e.g. 1C / Excel templates in Uzbekistan).

