# Architecture and Design Decisions (docs/DECISIONS.md)

This document records all architectural choices, sensible defaults, and trade-offs made during the implementation of the Telegram queue bot for the barbershop.

---

## 1. Database Compatibility and Testing Engine
- **Decision**: Production uses PostgreSQL 16 with `asyncpg` via SQLAlchemy 2.0 async. For lightweight local testing and CI versatility without mandatory Postgres services, models and repositories are written to support standard SQLAlchemy async dialects (`postgresql+asyncpg` and `sqlite+aiosqlite`).
- **Details**:
  - `JSON` type maps to `JSONB` on PostgreSQL via `.with_variant(JSONB, "postgresql")` and JSON on SQLite.
  - Monotonic keys and identifiers use `BigInteger` (INTEGER in SQLite, BIGINT in Postgres).
  - Production connection engine disables client-side prepared statement cache (`prepared_statement_cache_size=0`) and enables `pool_pre_ping=True` to seamlessly support PgBouncer transaction pooling in serverless/pooled environments.

## 2. Queue Monotonic Key and Ticket Numbers
- **Decision**: Each order has a per-barber monotonic `position_key` (generated using atomic lock on barber or sequences/timestamps + sequence counter) and a human-readable daily `ticket_no` (e.g. #1, #2, #3 per barber per calendar date in Asia/Tashkent).
- **Position Calculation**:
  - `position = count(active orders of barber with position_key < order.position_key) + 1`.
  - Active statuses: `WAITING`, `CALLED`, `IN_SERVICE`.
  - When a client is late (moves back 1 place), their `position_key` is swapped with the immediate next `WAITING` order's `position_key`. This guarantees exact 1-place shift without mutating keys of any other clients.

## 3. Lateness and Deadline Handling
- **Decision**:
  - Lateness deadline is configured via `LATE_MINUTES` (default: 10 minutes).
  - Maximum moves back is configured via `MAX_LATE_MOVES` (default: 2).
  - If a client fails to show up (`deadline_at <= now` or barber clicks `Kelmadi`):
    - `late_count` is incremented.
    - If `late_count <= 2`: if another client is `WAITING` behind, swap positions, notify the late client, call the newly promoted first client. If no one is behind, grant a fresh 10-minute deadline and notify the client.
    - If `late_count == 3`: order becomes `CANCELLED_NO_SHOW`, client is notified, and next client is called.

## 4. Payment Integrations & Smallest Currency Unit
- **Decision**:
  - Currency: `UZS` (Uzbekistan So'm).
  - In Telegram Payments, ISO 4217 specifies UZS exponent as 2 (1 UZS = 100 tiyin). Amounts sent to Telegram Payments `LabeledPrice` are converted to tiyin (`amount * 100`). Receipts and user displays format in whole so'm (e.g. `50 000 so'm`).
  - **Payme & Click**: Integrated via Telegram Payments with provider tokens (`PAYME_PROVIDER_TOKEN`, `CLICK_PROVIDER_TOKEN`).
  - **Paynet**: Telegram does not have a native Paynet BotFather provider. Paynet merchant API uses direct HTTP merchant protocol (identification, check, perform). We provide a clean modular adapter interface `PaymentProvider` with `PaynetProvider` and document the exact requirements in `docs/PAYMENTS.md`.
  - **FakeProvider**: Active when `PAYMENTS_MODE=test`. Automatically rejected on startup if `ENV=production`.

## 5. Serverless and Webhook Idempotency
- **Decision**:
  - The webhook endpoint `POST /webhook/<WEBHOOK_PATH_SECRET>` verifies `X-Telegram-Bot-Api-Secret-Token`.
  - To prevent duplicate update processing during Telegram retries or network blips, update IDs are tracked in a dedicated `processed_updates` table (or Redis with a 48-hour TTL) with a unique constraint. If already processed, HTTP 200 is immediately returned.
  - Background work is executed via `POST /internal/tick` protected with `X-Cron-Secret`. An internal APScheduler loop (every 15s) can also run it when `INTERNAL_SCHEDULER=true`.

## 6. Timezones and Timestamps
- **Decision**: All database timestamps (`created_at`, `called_at`, `completed_at`, etc.) are stored in UTC (`timezone=True`). All business logic for ticket numbers, daily cleanup, and reports is evaluated in `Asia/Tashkent` (UTC+5).

## 7. Barber Self-Service and Permissions
- **Decision**:
  - If `ALLOW_BARBER_EDIT_OWN_SERVICES=true`, barbers can add, edit, and toggle active status for their own services. Barbers cannot view or edit other barbers' services.
  - The Owner can view, edit, and manage all barbers, queues, and services.
  - Owner invite links: `https://t.me/<bot>?start=barber_<token>`. Tokens are cryptographically random strings (SHA-256 hashed in DB), expiring in 24 hours with single-use restriction.
