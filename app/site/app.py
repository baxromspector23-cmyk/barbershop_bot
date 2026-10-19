from __future__ import annotations

import hashlib
import hmac
import html
import logging
import math
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlencode

from aiohttp import web

from app.models.enums import PaymentMethod, UserRole
from app.repositories.audit_repo import AuditRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.user_repo import UserRepository
from app.services.report_service import ReportService
from app.site.security import verify_password
from app.utils.formatting import format_money
from app.utils.time_utils import format_datetime

logger = logging.getLogger("barbershop_bot.site")

_SESSION_COOKIE = "site_session"
_PRE_COOKIE = "site_pre"
_SESSION_LIFETIME_SEC = 8 * 3600
_LOCKOUT_WINDOW_SEC = 15 * 60
_MAX_FAILS_PER_IP = 5
_MAX_FAILS_GLOBAL = 30
_CLIENTS_PER_PAGE = 25
_VISITS_PER_PAGE = 10

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}

_BASE_CSS = """
:root {
  --bg-dark: #090b10;
  --bg-card: rgba(18, 22, 31, 0.86);
  --bg-card-hover: rgba(25, 31, 44, 0.94);
  --gold: #d4af37;
  --gold-light: #f3e5ab;
  --gold-dark: #aa820a;
  --gold-glow: rgba(212, 175, 55, 0.28);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --border-gold: rgba(212, 175, 55, 0.26);
  --border-subtle: rgba(255, 255, 255, 0.08);
  --danger-bg: rgba(185, 28, 28, 0.22);
  --danger-border: rgba(248, 113, 113, 0.45);
  --danger-text: #fca5a5;
}

* { box-sizing: border-box; }

@keyframes poleSlide {
  0% { background-position: 0 0; }
  100% { background-position: 56px 0; }
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 18px rgba(212, 175, 55, 0.18); }
  50% { box-shadow: 0 0 30px rgba(212, 175, 55, 0.36); }
}

body {
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  margin: 0;
  min-height: 100vh;
  color: var(--text-main);
  background-color: var(--bg-dark);
  background-image:
    radial-gradient(circle at 15% 15%, rgba(212, 175, 55, 0.14) 0%, transparent 42%),
    radial-gradient(circle at 85% 80%, rgba(185, 28, 28, 0.10) 0%, transparent 45%),
    radial-gradient(circle at 50% 50%, rgba(15, 23, 42, 0.92) 0%, #07090e 100%),
    repeating-linear-gradient(45deg, rgba(212, 175, 55, 0.025) 0px, rgba(212, 175, 55, 0.025) 1px, transparent 1px, transparent 28px),
    repeating-linear-gradient(-45deg, rgba(212, 175, 55, 0.025) 0px, rgba(212, 175, 55, 0.025) 1px, transparent 1px, transparent 28px);
  background-attachment: fixed;
}

.barber-pole-bar {
  height: 5px;
  width: 100%;
  background: repeating-linear-gradient(
    -45deg,
    #b91c1c 0px, #b91c1c 14px,
    #f8fafc 14px, #f8fafc 28px,
    #1d4ed8 28px, #1d4ed8 42px,
    #f8fafc 42px, #f8fafc 56px
  );
  background-size: 56px 56px;
  animation: poleSlide 2.2s linear infinite;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}

.container {
  max-width: 1040px;
  margin: 0 auto;
  padding: 28px 18px 48px;
}

header.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  background: var(--bg-card);
  backdrop-filter: blur(14px);
  border: 1px solid var(--border-gold);
  border-radius: 14px;
  padding: 14px 22px;
  margin-bottom: 26px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  animation: fadeInUp 0.45s ease-out;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.4px;
  color: var(--gold-light);
  text-decoration: none;
}

.brand:hover {
  color: #ffffff;
  text-decoration: none;
}

.brand-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(212,175,55,0.22), rgba(212,175,55,0.05));
  border: 1px solid var(--border-gold);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--gold);
}

.nav-menu {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.nav-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 15px;
  border-radius: 9px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-muted);
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.nav-tab:hover {
  color: var(--gold-light);
  background: rgba(212, 175, 55, 0.08);
  text-shadow: none;
}

.nav-tab.active {
  color: #090b10;
  background: linear-gradient(135deg, #e5c158 0%, #d4af37 100%);
  box-shadow: 0 3px 12px rgba(212, 175, 55, 0.28);
}

h1, h2 {
  margin: 0 0 14px 0;
  color: #ffffff;
  letter-spacing: 0.3px;
}

h1 { font-size: 24px; font-weight: 700; }
h2 { font-size: 19px; font-weight: 600; color: var(--gold-light); margin-top: 8px; }

a {
  color: var(--gold);
  text-decoration: none;
  transition: color 0.2s ease, text-shadow 0.2s ease;
}

a:hover {
  color: var(--gold-light);
  text-shadow: 0 0 10px var(--gold-glow);
}

.phone-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 8px;
  background: rgba(34, 197, 94, 0.12);
  border: 1px solid rgba(34, 197, 94, 0.35);
  color: #86efac;
  font-weight: 600;
  font-size: 13.5px;
  transition: all 0.2s ease;
}

.phone-link:hover {
  background: rgba(34, 197, 94, 0.24);
  border-color: #4ade80;
  color: #ffffff;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.25);
  text-shadow: none;
}

.card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-gold);
  border-radius: 16px;
  padding: 26px;
  margin-bottom: 24px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
  animation: fadeInUp 0.5s ease-out;
}

.login-wrapper {
  min-height: calc(100vh - 90px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-card {
  width: 100%;
  max-width: 430px;
  padding: 36px 32px;
  position: relative;
  overflow: hidden;
  animation: fadeInUp 0.55s cubic-bezier(0.16, 1, 0.3, 1), pulseGlow 5s infinite;
}

.login-badge {
  width: 68px;
  height: 68px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(212, 175, 55, 0.22) 0%, rgba(212, 175, 55, 0.04) 70%);
  border: 1.5px solid var(--gold);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--gold);
  box-shadow: 0 0 24px rgba(212, 175, 55, 0.25);
}

.login-subtitle {
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
  margin: 0 0 26px 0;
}

.field-group {
  margin-bottom: 18px;
}

.field-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--gold-light);
  margin-bottom: 7px;
}

.input-box {
  position: relative;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: 14px;
  color: var(--text-muted);
  pointer-events: none;
  display: flex;
  align-items: center;
}

input[type="text"], input[type="password"] {
  width: 100%;
  padding: 12px 44px 12px 42px;
  background: rgba(9, 11, 16, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  color: #ffffff;
  font-size: 15px;
  transition: all 0.25s ease;
}

/* Pure CSS password eye toggle (works without inline JS, full CSP compliance) */
input.pwd-masked {
  -webkit-text-security: disc;
  text-security: disc;
}

.pwd-toggle-chk {
  display: none;
}

.pwd-eye-label {
  position: absolute;
  right: 12px;
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.2s ease, background 0.2s ease;
  user-select: none;
}

.pwd-eye-label:hover {
  color: var(--gold-light);
  background: rgba(212, 175, 55, 0.12);
}

.pwd-eye-label .eye-off { display: none; }
.pwd-toggle-chk:checked ~ .input-box .pwd-eye-label { color: var(--gold); }
.pwd-toggle-chk:checked ~ .input-box .pwd-eye-label .eye-on { display: none; }
.pwd-toggle-chk:checked ~ .input-box .pwd-eye-label .eye-off { display: inline; }
.pwd-toggle-chk:checked ~ .input-box input.pwd-masked {
  -webkit-text-security: none !important;
  text-security: none !important;
}

input.search-input {
  padding-left: 16px;
  padding-right: 16px;
}

input[type="text"]::placeholder, input[type="password"]::placeholder {
  color: #64748b;
}

input[type="text"]:focus, input[type="password"]:focus {
  outline: none;
  border-color: var(--gold);
  background: rgba(15, 19, 28, 0.95);
  box-shadow: 0 0 0 3px rgba(212, 175, 55, 0.2);
}

button, .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 11px 20px;
  background: linear-gradient(135deg, #e5c158 0%, #d4af37 50%, #b5891c 100%);
  color: #090b10;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.4px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(212, 175, 55, 0.28);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease, filter 0.2s ease;
  text-decoration: none;
}

button:hover, .btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(212, 175, 55, 0.45);
  filter: brightness(1.07);
  color: #090b10;
  text-shadow: none;
}

button:active, .btn:active {
  transform: translateY(0) scale(0.98);
}

button.secondary, .btn.secondary {
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-main);
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: none;
  font-weight: 600;
}

button.secondary:hover, .btn.secondary:hover {
  background: rgba(255, 255, 255, 0.13);
  border-color: var(--gold);
  color: var(--gold-light);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
}

.btn-sm {
  padding: 7px 14px;
  font-size: 13px;
  border-radius: 8px;
}

.error {
  color: var(--danger-text);
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  padding: 12px 14px;
  border-radius: 10px;
  margin-bottom: 18px;
  font-size: 14px;
  text-align: center;
  animation: fadeInUp 0.3s ease-out;
}

.table-wrap {
  overflow-x: auto;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: rgba(11, 14, 21, 0.65);
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  text-align: left;
  padding: 13px 16px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 14px;
}

th {
  background: rgba(212, 175, 55, 0.1);
  color: var(--gold-light);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 12px;
  letter-spacing: 0.7px;
}

tbody tr {
  transition: background-color 0.18s ease;
}

tbody tr:hover {
  background: rgba(212, 175, 55, 0.06);
}

tbody tr:last-child td {
  border-bottom: none;
}

.badge-count {
  display: inline-block;
  padding: 4px 11px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 999px;
  background: rgba(212, 175, 55, 0.15);
  border: 1px solid var(--border-gold);
  color: var(--gold-light);
  margin-left: 8px;
  vertical-align: middle;
}

.pager {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
  gap: 14px;
  margin: 18px 0 26px;
}

.meta-box {
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.015));
  border: 1px solid var(--border-gold);
  padding: 16px;
  border-radius: 12px;
  transition: transform 0.2s ease, border-color 0.2s ease;
}

.meta-box:hover {
  transform: translateY(-2px);
  border-color: var(--gold);
}

.meta-box strong {
  display: block;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.meta-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--gold-light);
}

.progress-track {
  width: 100%;
  height: 8px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 6px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #d4af37, #f3e5ab);
  border-radius: 999px;
}

.leader-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
  padding: 18px 22px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.20) 0%, rgba(18, 22, 31, 0.9) 100%);
  border: 1.5px solid var(--gold);
  margin-bottom: 24px;
  box-shadow: 0 8px 26px rgba(212, 175, 55, 0.16);
}
"""

_SCISSORS_SVG = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="6" cy="6" r="3"></circle>'
    '<circle cx="6" cy="18" r="3"></circle>'
    '<line x1="20" y1="4" x2="8.12" y2="15.88"></line>'
    '<line x1="14.47" y1="14.48" x2="20" y2="20"></line>'
    '<line x1="8.12" y1="8.12" x2="12" y2="12"></line>'
    "</svg>"
)

_PHONE_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 '
    '19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 '
    '2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 '
    '12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>'
)


def _format_phone_html(phone: str | None) -> str:
    if not phone:
        return "—"
    safe_display = html.escape(phone)
    dial_digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if len(dial_digits) >= 7:
        return f'<a href="tel:{html.escape(dial_digits)}" class="phone-link" title="Qo\'ng\'iroq qilish">{_PHONE_SVG} {safe_display}</a>'
    return safe_display


def _page_shell(title: str, body_html: str, *, logout_csrf: str | None = None, active_tab: str = "clients") -> str:
    safe_title = html.escape(title)
    nav_html = ""
    if logout_csrf is not None:
        safe_csrf = html.escape(logout_csrf)
        clients_cls = "nav-tab active" if active_tab == "clients" else "nav-tab"
        reports_cls = "nav-tab active" if active_tab == "reports" else "nav-tab"
        nav_html = (
            '<header class="topbar">'
            f'<a href="/clients" class="brand"><span class="brand-icon">{_SCISSORS_SVG}</span>'
            "<span>BARBERSHOP</span></a>"
            '<div class="nav-menu">'
            f'<a href="/clients" class="{clients_cls}">👥 Mijozlar ro\'yxati</a>'
            f'<a href="/clients?view=reports&amp;period=month" class="{reports_cls}">📊 Barberlar statistikasi va Hisobotlar</a>'
            '<form method="post" action="/logout" style="margin:0">'
            f'<input type="hidden" name="csrf" value="{safe_csrf}">'
            '<button type="submit" class="secondary btn-sm">Chiqish</button>'
            "</form>"
            "</div>"
            "</header>"
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="uz">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex">\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{_BASE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="barber-pole-bar"></div>\n'
        '<div class="container">\n'
        f"{nav_html}\n"
        f"{body_html}\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    )


def _parse_page(raw: str | None) -> int:
    if not raw:
        return 1
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return 1
    if val < 1:
        return 1
    if val > 100_000:
        return 100_000
    return val


def _parse_offset(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return 0
    return max(-120, min(120, val))


_PASSWORD_HASH_KEY = web.AppKey("password_hash", str)
_current_site_app: web.Application | None = None


def get_current_site_app() -> web.Application | None:
    return _current_site_app


def set_current_site_password_hash(new_hash: str) -> None:
    global _current_site_app
    if _current_site_app is not None:
        _current_site_app[_PASSWORD_HASH_KEY] = new_hash


def create_site_app(
    session_factory: Any,
    *,
    username: str,
    password_hash: str,
    secret: str,
    secure_cookies: bool = True,
    now: Callable[[], float] = time.time,
    trust_proxy: bool = False,
) -> web.Application:
    sessions: dict[str, float] = {}
    ip_failures: dict[str, list[float]] = {}
    global_failures: list[float] = []
    secret_bytes = secret.encode("utf-8")
    expected_username_bytes = username.encode("utf-8")

    def _get_client_ip(request: web.Request) -> str:
        if trust_proxy:
            xff = request.headers.get("X-Forwarded-For", "")
            if xff:
                first_ip = xff.split(",")[0].strip()
                if first_ip:
                    return first_ip
        return request.remote or "unknown"

    def _make_csrf(token_val: str) -> str:
        sig = hmac.new(secret_bytes, f"csrf:{token_val}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{token_val}.{sig}"

    def _verify_csrf(token_val: str | None, submitted_csrf: str | None, *, allow_self_signed: bool = False) -> bool:
        if not submitted_csrf or not isinstance(submitted_csrf, str) or "." not in submitted_csrf:
            return False
        sub_nonce, _ = submitted_csrf.split(".", 1)
        if not sub_nonce or len(sub_nonce) < 16:
            return False
        if token_val:
            expected = _make_csrf(token_val)
            return hmac.compare_digest(expected, submitted_csrf)
        if allow_self_signed:
            expected = _make_csrf(sub_nonce)
            return hmac.compare_digest(expected, submitted_csrf)
        return False

    def _set_cookie(response: web.StreamResponse, name: str, value: str, max_age: int | None = None) -> None:
        response.set_cookie(
            name,
            value,
            httponly=True,
            secure=bool(secure_cookies),
            samesite="Strict",
            path="/",
            max_age=max_age,
        )

    def _get_valid_session_token(request: web.Request) -> str | None:
        raw_token = request.cookies.get(_SESSION_COOKIE)
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expiry = sessions.get(token_hash)
        current_time = now()
        if expiry is None or current_time >= expiry:
            sessions.pop(token_hash, None)
            return None
        return raw_token

    async def _write_audit(action: str, entity: str, entity_id: str | None = None, data: dict[str, Any] | None = None) -> None:
        try:
            async with session_factory() as s:
                repo = AuditRepository(s)
                await repo.log(
                    action=action,
                    entity=entity,
                    actor_user_id=None,
                    entity_id=entity_id,
                    data=data,
                )
                await s.commit()
        except Exception as exc:
            logger.warning("Failed to write site audit log (%s): %s", action, exc)

    def _prune_failures(current_time: float) -> None:
        cutoff = current_time - _LOCKOUT_WINDOW_SEC
        global_failures[:] = [t for t in global_failures if t > cutoff]
        for ip in list(ip_failures.keys()):
            kept = [t for t in ip_failures[ip] if t > cutoff]
            if kept:
                ip_failures[ip] = kept
            else:
                ip_failures.pop(ip, None)

    def _check_lockout(ip: str, current_time: float) -> int | None:
        _prune_failures(current_time)
        ip_list = ip_failures.get(ip, [])
        retry_after = 0
        locked = False
        if len(ip_list) >= _MAX_FAILS_PER_IP:
            locked = True
            oldest = min(ip_list)
            retry_after = max(retry_after, int(math.ceil((oldest + _LOCKOUT_WINDOW_SEC) - current_time)))
        if len(global_failures) >= _MAX_FAILS_GLOBAL:
            locked = True
            oldest_g = min(global_failures)
            retry_after = max(retry_after, int(math.ceil((oldest_g + _LOCKOUT_WINDOW_SEC) - current_time)))
        if locked:
            return max(1, retry_after)
        return None

    @web.middleware
    async def security_headers_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        is_webapp = request.path.startswith("/webapp")
        if is_webapp:
            from app.site.webapp import WEBAPP_SECURITY_HEADERS
            hdrs = WEBAPP_SECURITY_HEADERS
        else:
            hdrs = _SECURITY_HEADERS
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            for k, v in hdrs.items():
                exc.headers[k] = v
            raise
        for k, v in hdrs.items():
            response.headers[k] = v
        return response

    def _render_login_page(csrf_token: str, error_msg: str | None = None, status: int = 200, headers: dict[str, str] | None = None) -> web.Response:
        err_block = f'<div class="error">{html.escape(error_msg)}</div>' if error_msg else ""
        safe_csrf = html.escape(csrf_token)
        user_icon = (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>'
        )
        lock_icon = (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>'
        )
        eye_on_svg = (
            '<svg class="eye-on" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>'
        )
        eye_off_svg = (
            '<svg class="eye-off" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>'
            '<line x1="1" y1="1" x2="23" y2="23"></line></svg>'
        )
        body = (
            '<div class="login-wrapper">'
            '<div class="card login-card">'
            f'<div class="login-badge">{_SCISSORS_SVG}</div>'
            '<h1 style="text-align:center; margin-bottom:6px;">BARBERSHOP</h1>'
            '<p class="login-subtitle">Faqat sartaroshxona rahbari uchun boshqaruv paneli</p>'
            f"{err_block}"
            '<form method="post" action="/login">'
            f'<input type="hidden" name="csrf" value="{safe_csrf}">'
            '<div class="field-group">'
            '<label for="username" class="field-label">Login</label>'
            '<div class="input-box">'
            f'<span class="input-icon">{user_icon}</span>'
            '<input type="text" id="username" name="username" placeholder="Loginni kiriting..." required autofocus autocomplete="username">'
            "</div>"
            "</div>"
            '<div class="field-group" style="margin-bottom: 24px;">'
            '<label for="password" class="field-label">Maxfiy parol</label>'
            '<input type="checkbox" id="show_pwd" class="pwd-toggle-chk">'
            '<div class="input-box">'
            f'<span class="input-icon">{lock_icon}</span>'
            '<input type="text" class="pwd-masked" id="password" name="password" placeholder="Parolni kiriting..." required autocomplete="current-password" spellcheck="false" autocapitalize="off">'
            f'<label for="show_pwd" class="pwd-eye-label" title="Parolni ko\'rsatish / yashirish">{eye_on_svg}{eye_off_svg}</label>'
            "</div>"
            "</div>"
            '<button type="submit" style="width:100%; padding:13px 20px; font-size:15px;">Tizimga kirish &rarr;</button>'
            "</form>"
            "</div>"
            "</div>"
        )
        html_doc = _page_shell("Tizimga kirish — Barbershop", body)
        return web.Response(text=html_doc, status=status, content_type="text/html", charset="utf-8", headers=headers)

    async def handle_login_get(request: web.Request) -> web.Response:
        pre_val = request.cookies.get(_PRE_COOKIE)
        new_cookie = False
        if not pre_val or len(pre_val) < 16:
            pre_val = secrets.token_urlsafe(32)
            new_cookie = True
        csrf_token = _make_csrf(pre_val)
        resp = _render_login_page(csrf_token)
        if new_cookie:
            _set_cookie(resp, _PRE_COOKIE, pre_val)
        return resp

    async def handle_login_post(request: web.Request) -> web.Response:
        form = await request.post()
        submitted_csrf = str(form.get("csrf", "")) if "csrf" in form else ""
        pre_val = request.cookies.get(_PRE_COOKIE)
        if not _verify_csrf(pre_val, submitted_csrf, allow_self_signed=True):
            new_pre = pre_val or secrets.token_urlsafe(32)
            resp = _render_login_page(_make_csrf(new_pre), error_msg="CSRF tasdiqlash xatosi. Qayta urinib ko'ring.", status=403)
            if not pre_val:
                _set_cookie(resp, _PRE_COOKIE, new_pre)
            return resp
        active_pre = pre_val or submitted_csrf.split(".", 1)[0]

        ip = _get_client_ip(request)
        current_time = now()
        retry_after = _check_lockout(ip, current_time)
        if retry_after is not None:
            await _write_audit("SITE_LOGIN_LOCKED", "site_auth", data={"ip": ip})
            return _render_login_page(
                _make_csrf(active_pre),
                error_msg="Juda ko'p xato urinishlar. Birozdan so'ng qayta urinib ko'ring.",
                status=429,
                headers={"Retry-After": str(retry_after)},
            )

        sub_user = str(form.get("username", ""))
        sub_pass = str(form.get("password", ""))

        # Always run both checks to avoid timing leaks
        user_ok = hmac.compare_digest(sub_user.encode("utf-8"), expected_username_bytes)
        active_hash = request.app.get(_PASSWORD_HASH_KEY, password_hash)
        pass_ok = verify_password(sub_pass, active_hash)

        if not (user_ok and pass_ok):
            ip_failures.setdefault(ip, []).append(current_time)
            global_failures.append(current_time)
            await _write_audit("SITE_LOGIN_FAIL", "site_auth", data={"ip": ip})
            return _render_login_page(
                _make_csrf(active_pre),
                error_msg="Login yoki parol noto'g'ri",
                status=401,
            )

        # Success
        ip_failures.pop(ip, None)
        session_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        sessions[token_hash] = current_time + _SESSION_LIFETIME_SEC

        await _write_audit("SITE_LOGIN_OK", "site_auth", data={"ip": ip})
        resp = web.HTTPSeeOther(location="/clients")
        _set_cookie(resp, _SESSION_COOKIE, session_token, max_age=_SESSION_LIFETIME_SEC)
        return resp

    async def handle_logout_post(request: web.Request) -> web.Response:
        session_token = _get_valid_session_token(request)
        form = await request.post()
        submitted_csrf = str(form.get("csrf", "")) if "csrf" in form else ""
        if not session_token or not _verify_csrf(session_token, submitted_csrf, allow_self_signed=False):
            return web.Response(
                text=_page_shell("Xatolik", '<div class="card"><div class="error">CSRF xatosi</div></div>'),
                status=403,
                content_type="text/html",
                charset="utf-8",
            )
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        sessions.pop(token_hash, None)
        ip = _get_client_ip(request)
        await _write_audit("SITE_LOGOUT", "site_auth", data={"ip": ip})
        resp = web.HTTPSeeOther(location="/login")
        _set_cookie(resp, _SESSION_COOKIE, "", max_age=0)
        return resp

    async def handle_root(request: web.Request) -> web.Response:
        session_token = _get_valid_session_token(request)
        if not session_token:
            raise web.HTTPSeeOther(location="/login")
        raise web.HTTPSeeOther(location="/clients")

    async def _render_reports_view(request: web.Request, session_token: str) -> web.Response:
        period = request.query.get("period", "month")
        if period not in ("today", "week", "month"):
            period = "month"
        offset = _parse_offset(request.query.get("offset"))

        async with session_factory() as s:
            rep_service = ReportService(s)
            summary = await rep_service.generate_report(period_type=period, offset=offset)
            _, _, month_title = rep_service.get_period_bounds("month", 0)
            month_summary = (
                summary
                if (period == "month" and offset == 0)
                else await rep_service.generate_report(period_type="month", offset=0)
            )
            payments = await rep_service.payment_repo.get_revenue_payments_in_range(summary.start_utc, summary.end_utc)
            transfer_sum = sum(p.amount for p in payments if p.method == PaymentMethod.TRANSFER.value)

        period_names = {
            "today": "Bugungi",
            "week": "Haftalik",
            "month": "Oylik",
        }
        p_tabs = []
        for p_key, p_label in (("today", "📅 Bugun"), ("week", "📆 Hafta"), ("month", "🗓 Shu oy")):
            cls = "btn btn-sm" if period == p_key and offset == 0 else "btn secondary btn-sm"
            p_tabs.append(f'<a href="/clients?view=reports&amp;period={p_key}&amp;offset=0" class="{cls}">{p_label}</a>')

        nav_prev = f'/clients?view=reports&amp;period={period}&amp;offset={int(offset - 1)}'
        nav_next = f'/clients?view=reports&amp;period={period}&amp;offset={int(offset + 1)}'

        leader_html = ""
        top_barber = next((r for r in summary.rankings if r.is_top), None)
        if top_barber:
            leader_html = (
                '<div class="leader-banner">'
                "<div>"
                '<div style="font-size:12px; text-transform:uppercase; letter-spacing:0.8px; color:var(--gold);">🏆 Davr peshqadami (Eng ko\'p tushum)</div>'
                f'<div style="font-size:22px; font-weight:800; color:#fff; margin-top:4px;">🥇 {html.escape(top_barber.display_name)}</div>'
                "</div>"
                '<div style="text-align:right;">'
                f'<div style="font-size:20px; font-weight:800; color:var(--gold-light);">{html.escape(format_money(int(top_barber.revenue)))}</div>'
                f'<div style="font-size:13px; color:var(--text-muted);">{int(top_barber.services_count)} ta yakunlangan xizmat</div>'
                "</div>"
                "</div>"
            )

        ranking_rows = []
        max_rev = max((r.revenue for r in summary.rankings), default=0) or 1
        for idx, item in enumerate(summary.rankings, 1):
            if idx == 1 and item.revenue > 0:
                medal = "🥇 1-o'rin"
            elif idx == 2 and item.revenue > 0:
                medal = "🥈 2-o'rin"
            elif idx == 3 and item.revenue > 0:
                medal = "🥉 3-o'rin"
            else:
                medal = f"#{int(idx)}"
            pct = int(round((item.revenue / summary.total_revenue) * 100)) if summary.total_revenue > 0 else 0
            bar_w = int(round((item.revenue / max_rev) * 100)) if item.revenue > 0 else 0
            ranking_rows.append(
                "<tr>"
                f"<td><strong>{medal}</strong></td>"
                f"<td><strong style=\"color:#fff; font-size:15px;\">{html.escape(item.display_name)}</strong>"
                f'<div class="progress-track"><div class="progress-fill" style="width:{bar_w}%"></div></div></td>'
                f"<td>{int(item.services_count)} ta</td>"
                f'<td style="color:var(--gold-light); font-weight:700;">{html.escape(format_money(int(item.revenue)))}</td>'
                f"<td><span class=\"badge-count\">{pct}%</span></td>"
                "</tr>"
            )

        rankings_table = (
            "\n".join(ranking_rows)
            if ranking_rows
            else '<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">Sartaroshlar topilmadi.</td></tr>'
        )

        body = (
            '<div class="card">'
            '<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:20px;">'
            f'<div><h1 style="margin-bottom:4px;">📊 Moliya va Barberlar Statistikasi</h1>'
            f'<div style="color:var(--text-muted); font-size:14px;">{html.escape(period_names.get(period, "Davr"))}: <strong style="color:var(--gold-light);">{html.escape(summary.period_title)}</strong></div></div>'
            f'<div style="display:flex; gap:8px; flex-wrap:wrap;">{" ".join(p_tabs)}</div>'
            "</div>"
            '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:22px;">'
            f'<a href="{nav_prev}" class="btn secondary btn-sm">&larr; Oldingi davr</a>'
            f'<span style="color:var(--gold-light); font-weight:600;">{html.escape(summary.period_title)}</span>'
            f'<a href="{nav_next}" class="btn secondary btn-sm">Keyingi davr &rarr;</a>'
            "</div>"
            f"{leader_html}"
            '<div class="meta-grid">'
            f'<div class="meta-box"><strong>Tanlangan davr tushumi</strong><span class="meta-val">{html.escape(format_money(int(summary.total_revenue)))}</span>'
            f'<div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Jami xizmatlar: {int(summary.total_services)} ta</div></div>'
            f'<div class="meta-box"><strong>Shu oyda jami tushum ({html.escape(month_title)})</strong><span class="meta-val">{html.escape(format_money(int(month_summary.total_revenue)))}</span>'
            f'<div style="font-size:12px; color:var(--text-muted); margin-top:4px;">1 oylik xizmatlar: {int(month_summary.total_services)} ta</div></div>'
            f'<div class="meta-box"><strong>💵 Naqd pul (Cash)</strong><span class="meta-val">{html.escape(format_money(int(summary.cash_sum)))}</span></div>'
            f'<div class="meta-box"><strong>💳 Karta / O\'tkazma (Transfer)</strong><span class="meta-val">{html.escape(format_money(int(transfer_sum + summary.click_sum + summary.payme_sum + summary.paynet_sum)))}</span></div>'
            "</div>"
            "<h2>💈 Sartaroshlar reytingi (Kim qancha pul topdi)</h2>"
            '<div class="table-wrap">'
            "<table>"
            "<thead><tr><th>O'rin</th><th>Sartarosh</th><th>Mijozlar (Xizmat)</th><th>Topgan puli</th><th>Ulushi</th></tr></thead>"
            f"<tbody>{rankings_table}</tbody>"
            "</table>"
            "</div>"
            "</div>"
        )
        html_doc = _page_shell("Barberlar statistikasi va Hisobotlar", body, logout_csrf=_make_csrf(session_token), active_tab="reports")
        return web.Response(text=html_doc, status=200, content_type="text/html", charset="utf-8")

    async def handle_clients_list(request: web.Request) -> web.Response:
        session_token = _get_valid_session_token(request)
        if not session_token:
            raise web.HTTPSeeOther(location="/login")

        if request.query.get("view") == "reports":
            return await _render_reports_view(request, session_token)

        has_q = "q" in request.query
        raw_q = request.query.get("q", "")
        cleaned_q = raw_q.replace("\x00", "")[:100].strip()
        page = _parse_page(request.query.get("page"))

        async with session_factory() as s:
            user_repo = UserRepository(s)
            total_clients = await user_repo.count_clients()
            if has_q and (raw_q != "" or cleaned_q != ""):
                clients = await user_repo.search_clients(cleaned_q, limit=_CLIENTS_PER_PAGE)
            else:
                offset = (page - 1) * _CLIENTS_PER_PAGE
                clients = await user_repo.get_all_clients(limit=_CLIENTS_PER_PAGE, offset=offset)

        safe_q = html.escape(cleaned_q)
        rows_html = []
        for cl in clients:
            cid = int(cl.id)
            full_name = " ".join(p for p in (cl.first_name, cl.last_name) if p) or "—"
            safe_name = html.escape(full_name)
            safe_user = f"@{html.escape(cl.username.lstrip('@'))}" if cl.username else "—"
            phone_html = _format_phone_html(cl.phone)
            rows_html.append(
                "<tr>"
                f'<td><a href="/clients/{cid}" style="font-weight:600;">{safe_name}</a></td>'
                f"<td>{safe_user}</td>"
                f"<td>{phone_html}</td>"
                f'<td><a href="/clients/{cid}" class="btn secondary btn-sm">Tarixni ko\'rish &rarr;</a></td>'
                "</tr>"
            )

        table_body = (
            "\n".join(rows_html)
            if rows_html
            else '<tr><td colspan="4" style="text-align:center; padding:28px; color:var(--text-muted);">Mijozlar topilmadi.</td></tr>'
        )

        pager_html = ""
        if not cleaned_q:
            total_pages = max(1, math.ceil(total_clients / _CLIENTS_PER_PAGE))
            pager_links = []
            if page > 1:
                pager_links.append(f'<a href="/clients?{urlencode({"page": page - 1})}" class="btn secondary btn-sm">&larr; Oldingi</a>')
            pager_links.append(f'<span style="color:var(--text-muted); font-size:14px;">Sahifa {int(page)} / {int(total_pages)}</span>')
            if page * _CLIENTS_PER_PAGE < total_clients:
                pager_links.append(f'<a href="/clients?{urlencode({"page": page + 1})}" class="btn secondary btn-sm">Keyingi &rarr;</a>')
            pager_html = f'<div class="pager">{" ".join(pager_links)}</div>'

        body = (
            '<div class="card">'
            f'<h1>Mijozlar ro\'yxati <span class="badge-count">Jami: {int(total_clients)}</span></h1>'
            '<form method="get" action="/clients" style="display:flex; gap:10px; margin:18px 0 22px; flex-wrap:wrap;">'
            f'<input type="text" class="search-input" name="q" value="{safe_q}" placeholder="Ism, @username yoki telefon raqam orqali qidirish..." style="flex:1; min-width:220px;">'
            '<button type="submit">Qidirish</button>'
            + ('<a href="/clients" class="btn secondary">Tozalash</a>' if cleaned_q else "")
            + "</form>"
            '<div class="table-wrap">'
            "<table>"
            "<thead><tr><th>Ism</th><th>Username</th><th>Telefon (Bosib qo'ng'iroq qilish)</th><th>Tashriflar</th></tr></thead>"
            f"<tbody>{table_body}</tbody>"
            "</table>"
            "</div>"
            f"{pager_html}"
            "</div>"
        )
        html_doc = _page_shell("Mijozlar ro'yxati", body, logout_csrf=_make_csrf(session_token), active_tab="clients")
        return web.Response(text=html_doc, status=200, content_type="text/html", charset="utf-8")

    async def handle_client_detail(request: web.Request) -> web.Response:
        session_token = _get_valid_session_token(request)
        if not session_token:
            raise web.HTTPSeeOther(location="/login")

        raw_id = request.match_info.get("id", "")
        if not raw_id.isdigit():
            raise web.HTTPNotFound(text="Mijoz topilmadi")
        client_id = int(raw_id)
        if client_id <= 0:
            raise web.HTTPNotFound(text="Mijoz topilmadi")

        page = _parse_page(request.query.get("page"))
        offset = (page - 1) * _VISITS_PER_PAGE

        async with session_factory() as s:
            user_repo = UserRepository(s)
            client_obj = await user_repo.get_by_id(client_id)
            if not client_obj or client_obj.role != UserRole.CLIENT.value:
                raise web.HTTPNotFound(text="Mijoz topilmadi")

            order_repo = OrderRepository(s)
            visit_count, total_spent = await order_repo.get_client_visit_stats(client_id)
            visits = await order_repo.get_client_visits(client_id, limit=_VISITS_PER_PAGE, offset=offset)

        await _write_audit(
            "SITE_CLIENT_VIEW",
            "client",
            entity_id=str(client_id),
            data={"page": int(page), "ip": _get_client_ip(request)},
        )

        full_name = " ".join(p for p in (client_obj.first_name, client_obj.last_name) if p) or "—"
        safe_name = html.escape(full_name)
        safe_user = f"@{html.escape(client_obj.username.lstrip('@'))}" if client_obj.username else "—"
        phone_html = _format_phone_html(client_obj.phone)
        safe_total_spent = html.escape(format_money(int(total_spent)))

        visit_rows = []
        for v in visits:
            dt_str = format_datetime(v.completed_at) if v.completed_at else "—"
            svc_name = v.service_name or (v.service.name if v.service else "—")
            barber_name = v.barber.display_name if v.barber else "—"
            price_str = format_money(int(v.price))
            visit_rows.append(
                "<tr>"
                f"<td>{html.escape(dt_str)}</td>"
                f"<td><strong>{html.escape(svc_name)}</strong></td>"
                f'<td style="color:var(--gold-light); font-weight:600;">{html.escape(price_str)}</td>'
                f"<td>{html.escape(barber_name)}</td>"
                "</tr>"
            )

        if visit_rows:
            visits_section = (
                '<div class="table-wrap">'
                "<table>"
                "<thead><tr><th>Sana va vaqt</th><th>Xizmat</th><th>Narx</th><th>Sartarosh</th></tr></thead>"
                f"<tbody>{''.join(visit_rows)}</tbody>"
                "</table>"
                "</div>"
            )
        else:
            visits_section = '<p style="color:var(--text-muted); padding:16px 0;">Hali tashriflar mavjud emas.</p>'

        pager_links = []
        if page > 1:
            pager_links.append(f'<a href="/clients/{int(client_id)}?{urlencode({"page": page - 1})}" class="btn secondary btn-sm">&larr; Oldingi</a>')
        if offset + _VISITS_PER_PAGE < visit_count:
            pager_links.append(f'<a href="/clients/{int(client_id)}?{urlencode({"page": page + 1})}" class="btn secondary btn-sm">Keyingi &rarr;</a>')
        pager_html = f'<div class="pager">{" ".join(pager_links)}</div>' if pager_links else ""

        body = (
            '<div class="card">'
            '<p style="margin-top:0; margin-bottom:18px;"><a href="/clients" class="btn secondary btn-sm">&larr; Mijozlar ro\'yxatiga qaytish</a></p>'
            f"<h1>{safe_name}</h1>"
            '<div class="meta-grid">'
            f'<div class="meta-box"><strong>Username</strong><span class="meta-val">{safe_user}</span></div>'
            f'<div class="meta-box"><strong>Telefon raqam</strong><span class="meta-val">{phone_html}</span></div>'
            f'<div class="meta-box"><strong>Tashriflar soni</strong><span class="meta-val">{int(visit_count)}</span></div>'
            f'<div class="meta-box"><strong>Jami to\'langan</strong><span class="meta-val">{safe_total_spent}</span></div>'
            "</div>"
            "<h2>Tashriflar tarixi</h2>"
            f"{visits_section}"
            f"{pager_html}"
            "</div>"
        )
        html_doc = _page_shell(f"Mijoz — {full_name}", body, logout_csrf=_make_csrf(session_token), active_tab="clients")
        return web.Response(text=html_doc, status=200, content_type="text/html", charset="utf-8")

    from app.site.webapp import handle_webapp_generate, handle_webapp_page

    global _current_site_app
    app = web.Application(middlewares=[security_headers_middleware])
    app[_PASSWORD_HASH_KEY] = password_hash
    _current_site_app = app
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_post("/logout", handle_logout_post)
    app.router.add_get("/", handle_root)
    app.router.add_get("/clients", handle_clients_list)
    app.router.add_get("/clients/{id}", handle_client_detail)
    app.router.add_get("/webapp", handle_webapp_page)
    app.router.add_post("/webapp/api/generate", handle_webapp_generate)
    return app

