# Serverless Deployment Guide (Google Cloud Run) (docs/SERVERLESS.md)

This guide provides step-by-step instructions to deploy the Barbershop Telegram queue bot to Google Cloud Run (container-based serverless).

The bot is designed to run in serverless mode with zero process memory dependency between requests:
- State is persisted in PostgreSQL and Redis.
- Updates are received via `POST /webhook/<WEBHOOK_PATH_SECRET>`.
- Background deadlines, lateness, reminders, and cleanups are triggered via `POST /internal/tick`.

---

## 1. Prerequisites

1. Google Cloud Project with Billing enabled.
2. `gcloud` CLI installed and authenticated.
3. Managed PostgreSQL (e.g. Google Cloud SQL for PostgreSQL or Neon/Supabase) with PgBouncer connection pooling enabled.
4. Upstash Redis or Memorystore for Redis (optional for FSM; falls back to PostgreSQL/Memory).

---

## 2. Setting Secrets in Google Secret Manager

Store sensitive credentials securely:
```bash
# Bot Token
gcloud secrets create BOT_TOKEN --data-file=- <<EOF
123456789:ABCdefGHIjklMNOpqrSTUvwxyz
EOF

# Database URL
gcloud secrets create DATABASE_URL --data-file=- <<EOF
postgresql+asyncpg://user:pass@pooler.neon.tech/barbershop?sslmode=require
EOF

# Webhook Secrets
gcloud secrets create WEBHOOK_SECRET --data-file=- <<EOF
super_random_webhook_secret_telegram_32chars
EOF

gcloud secrets create CRON_SECRET --data-file=- <<EOF
super_random_cron_tick_secret_key_32chars
EOF
```

---

## 3. Building and Pushing Container Image

Build the container image using Google Cloud Build:
```bash
gcloud builds submit --tag gcr.io/$PROJECT_ID/barbershop-bot:v1 .
```

---

## 4. Running Database Migrations

Use Cloud Run Jobs to execute Alembic migrations before deploying the web service:
```bash
gcloud run jobs create migrate-db \
    --image gcr.io/$PROJECT_ID/barbershop-bot:v1 \
    --command python \
    --args "-m","alembic","upgrade","head" \
    --set-secrets DATABASE_URL=DATABASE_URL:latest \
    --region us-central1

# Execute migration job
gcloud run jobs execute migrate-db --wait
```

---

## 5. Deploying the Cloud Run Service

Deploy the bot service:
```bash
gcloud run deploy barbershop-bot \
    --image gcr.io/$PROJECT_ID/barbershop-bot:v1 \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --min-instances 1 \
    --max-instances 10 \
    --timeout 30s \
    --set-env-vars RUN_MODE=webhook,INTERNAL_SCHEDULER=false,ENV=production,PAYMENTS_MODE=live,WEBHOOK_PATH_SECRET=wh_sec_path_route_key \
    --set-secrets BOT_TOKEN=BOT_TOKEN:latest,DATABASE_URL=DATABASE_URL:latest,WEBHOOK_SECRET=WEBHOOK_SECRET:latest,CRON_SECRET=CRON_SECRET:latest
```

> **IMPORTANT**: Set `--min-instances 1` to eliminate cold start latency for incoming Telegram webhook requests.

Note the assigned service URL, e.g. `https://barbershop-bot-xyz-uc.a.run.app`.

---

## 6. Configuring Google Cloud Scheduler (Cron Tick)

Create a scheduled job to invoke `POST /internal/tick` every minute:
```bash
gcloud scheduler jobs create http barbershop-cron-tick \
    --schedule="* * * * *" \
    --uri="https://barbershop-bot-xyz-uc.a.run.app/internal/tick" \
    --http-method=POST \
    --headers="X-Cron-Secret=super_random_cron_tick_secret_key_32chars" \
    --time-zone="Asia/Tashkent" \
    --location=us-central1
```

The endpoint processes overdue orders, in-service reminders, expired pending orders, and midnight cleanup idempotently.

---

## 7. Registering the Telegram Webhook

Run the `set_webhook.py` script locally or via Cloud Shell:
```bash
python scripts/set_webhook.py \
    --url "https://barbershop-bot-xyz-uc.a.run.app" \
    --secret "super_random_webhook_secret_telegram_32chars" \
    --drop-pending
```

Verify with:
```bash
python scripts/set_webhook.py --info-only
```

---

## 8. Platform Limits & Verification Checklist

- [x] **Cold Start Time**: Keep `--min-instances 1` so webhooks respond in < 150ms.
- [x] **Request Timeout**: Telegram expects webhook acknowledgement within 5-10 seconds. Webhook responds with HTTP 200 immediately after feeding update to dispatcher.
- [x] **Cron Frequency**: Cloud Scheduler supports 1-minute frequency (`* * * * *`). The tick function tolerates ticks arriving up to 60 seconds late.
- [x] **Database Connections**: With PgBouncer transaction mode and serverless pooling, client connection pooling is kept small (`pool_size=10`) with prepared statement caches disabled.
