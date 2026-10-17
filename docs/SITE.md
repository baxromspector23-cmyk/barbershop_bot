# Owner-Only Website (`app/site`)

## Overview
The owner-only website is a small, read-only web interface that runs outside Telegram in a standard web browser. It allows the barbershop owner ("katta barber") to log in with a username and password, view and search the full list of registered clients (including phone numbers), and open any client's profile to inspect their completed visit history (date/time in Tashkent timezone, service, price, and barber).

- **Read-Only & Direct Database Access**: Reads directly from the bot's database without any copy, sync, or second database. There are no write routes, no JSON/API endpoints, and no static file mounts.
- **Strict Access Control**: Barbers and clients have no access. Every route except `/login` requires a valid server-side session.
- **Language**: All page texts are intentionally in **Uzbek (Latin)** only, since the website is exclusively for the barbershop owner.

---

## How to Enable

1. **Generate the password hash and session secret** (requires a password of at least 12 characters):
   ```bash
   python scripts/make_site_password_hash.py
   ```
   Copy the two printed lines (`SITE_PASSWORD_HASH=...` and `SITE_SESSION_SECRET=...`).

2. **Configure `.env`**:
   ```env
   SITE_ENABLED=true
   SITE_USERNAME=owner
   SITE_PASSWORD_HASH=scrypt$16384$8$1$...
   SITE_SESSION_SECRET=...
   SITE_SECURE_COOKIES=true
   SITE_TRUST_PROXY=true
   SITE_PORT=8081
   SITE_DOMAIN=clients.example.com
   ```
   - Set `SITE_DOMAIN` to the DNS name pointed at your server for Caddy automatic HTTPS.
   - Set `SITE_TRUST_PROXY=true` when running behind Caddy so brute-force protection tracks real client IPs via `X-Forwarded-For`.

3. **Restart the bot / containers**:
   When `SITE_ENABLED=true`, `app/main.py` starts the owner site on `HOST:SITE_PORT` (`8081` by default) in both `polling` and `webhook` modes, separate from the bot's webhook server (`8080`). Caddy reverse-proxies `SITE_DOMAIN` over HTTPS to `app:8081` internally (`8081` is never published directly to the host in `docker-compose.yml`).

---

## Audit Logging
The site writes events to the `audit_log` table (`actor_user_id = NULL`):
- `SITE_LOGIN_OK` — successful owner login (`{"ip": "..."}`)
- `SITE_LOGIN_FAIL` — failed login attempt (`{"ip": "..."}`)
- `SITE_LOGIN_LOCKED` — request blocked by brute-force lockout (`{"ip": "..."}`)
- `SITE_LOGOUT` — owner logged out (`{"ip": "..."}`)
- `SITE_CLIENT_VIEW` — owner viewed a client's visit history (`entity="client"`, `entity_id="<client_id>"`, `{"page": 1, "ip": "..."}`)

Passwords, typed usernames, and session/CSRF tokens are **never** stored in the database or written to logs.

---

## Operational & Security Rules
- **Never enable without HTTPS in production**: `Settings.validate_runtime()` rejects `SITE_SECURE_COOKIES=false` when `ENV=production` and `SITE_ENABLED=true`.
- **Rotate the password if anybody else saw it**: There is no online password reset flow. To change or reset the password, run `python scripts/make_site_password_hash.py`, update `SITE_PASSWORD_HASH` (and optionally `SITE_SESSION_SECRET`) in `.env`, and restart the service.
- **Sessions end on restart**: Server-side sessions are stored in memory (hashed with SHA-256) with an absolute lifetime of 8 hours. Restarting the application invalidates all active sessions and requires logging in again.
