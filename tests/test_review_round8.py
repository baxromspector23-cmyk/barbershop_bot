"""READ-ONLY reviewer tests, round 8: owner-only client site (login + client list + visit history).
Do not edit, rename, move or delete this file.  Run: pytest tests/test_review_round8.py  (SQLite and PostgreSQL)

Fixed contract (names are on purpose):
  app/site/security.py : hash_password(password: str) -> str ; verify_password(password: str, stored: str) -> bool
  app/site/app.py      : create_site_app(session_factory, *, username: str, password_hash: str, secret: str,
                                         secure_cookies: bool = True, now: Callable[[], float] = time.time) -> aiohttp.web.Application
  Routes: GET /login, POST /login (form fields: username, password, csrf), POST /logout (field: csrf),
          GET / (redirect to /clients), GET /clients?q=&page=, GET /clients/{id}?page=     -- NOTHING else
  Settings: SITE_ENABLED (default False), SITE_USERNAME, SITE_PASSWORD_HASH, SITE_SESSION_SECRET, SITE_SECURE_COOKIES (default True), SITE_PORT
  UserRepository.search_clients(query, limit=10) ; OrderRepository.get_client_visits(client_id, limit=10, offset=0) ;
  OrderRepository.get_client_visit_stats(client_id) -> (count, total)       (same contract as before: COMPLETED orders only)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from app.config import Settings
from app.models.audit import AuditLog
from app.models.enums import Language, OrderStatus, UserRole
from app.models.order import Order
from app.models.user import User

USER, PWD = "owner", "Correct-Horse-Battery-9!"
SECRET = "s" * 40


class Clock:
    def __init__(self): self.t = 1_800_000_000.0
    def __call__(self): return self.t


async def _user(s, tg, first, role=UserRole.CLIENT.value, username=None, phone=None, last=None):
    u = User(telegram_id=tg, username=username, first_name=first, last_name=last,
             language=Language.UZ.value, role=role, phone=phone)
    s.add(u); await s.commit(); await s.refresh(u); return u


_n = [0]


async def _visit(s, barber, client, when_utc, name="Soch olish", price=50000, status=OrderStatus.COMPLETED.value):
    _n[0] += 1
    o = Order(barber_id=barber.id, client_id=client.id, service_id=None, service_name=name, price=price,
              duration_minutes=30, status=status, position_key=_n[0] * 1000, ticket_no=_n[0],
              ticket_date=date(2026, 7, 12), completed_at=when_utc if status == OrderStatus.COMPLETED.value else None)
    s.add(o); await s.commit(); return o


def _csrf(html: str) -> str:
    m = re.search(r'<input[^>]*name="csrf"[^>]*value="([^"]*)"', html) or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="csrf"', html)
    assert m, "login page must contain a hidden input named csrf"
    return m.group(1)


async def _client(session_factory, clock=None, secure=False):
    from app.site.app import create_site_app
    from app.site.security import hash_password
    app = create_site_app(session_factory, username=USER, password_hash=hash_password(PWD), secret=SECRET,
                          secure_cookies=secure, now=clock or Clock())
    c = TestClient(TestServer(app)); await c.start_server(); return c


async def _login(c, password=PWD, username=USER, csrf=None):
    if csrf is None:
        r = await c.get("/login"); csrf = _csrf(await r.text())
    return await c.post("/login", data={"username": username, "password": password, "csrf": csrf}, allow_redirects=False)


# ---------------------------------------------------------------- repositories (same contract as before)
@pytest.mark.asyncio
async def test_R1_search_clients(session_factory):
    from app.repositories.user_repo import UserRepository
    async with session_factory() as s:
        a = await _user(s, 9001, "Bobur", username="bobur_k", phone="+998901234567", last="Karimov")
        b = await _user(s, 9002, "Sardor", phone="+998931112233")
        await _user(s, 9003, "Bobur", role=UserRole.BARBER.value, phone="+998900000000")
        repo = UserRepository(s)
        for q in ("901234567", "+998901234567", "90 123 45 67", "1234567", "bobur", "BOB", "@bobur_k", "karim"):
            assert [u.id for u in await repo.search_clients(q)] == [a.id], q
        assert [u.id for u in await repo.search_clients("sard")] == [b.id]
        for q in ("zzzz", "", "   ", "%", "_", "' OR 1=1 --"):
            assert await repo.search_clients(q) == [], q
        for i in range(15):
            await _user(s, 9100 + i, f"Ali{i}", phone=f"+99890100{i:04d}")
        assert len(await repo.search_clients("ali", limit=10)) == 10


@pytest.mark.asyncio
async def test_R2_visits_and_stats(session_factory, sample_barber):
    from app.repositories.order_repo import OrderRepository
    async with session_factory() as s:
        c = await _user(s, 9201, "Bobur", phone="+998901234567")
        o = await _user(s, 9202, "Other", phone="+998911111111")
        t = lambda d: datetime(2026, 7, d, 8, 0, tzinfo=timezone.utc)  # noqa: E731
        await _visit(s, sample_barber, c, t(1), price=50000)
        await _visit(s, sample_barber, c, t(5), price=30000)
        await _visit(s, sample_barber, c, t(9), price=50000)
        await _visit(s, sample_barber, c, t(10), status=OrderStatus.CANCELLED_BY_CLIENT.value)
        await _visit(s, sample_barber, o, t(11), price=99999)
        repo = OrderRepository(s)
        assert [x.completed_at.day for x in await repo.get_client_visits(c.id)] == [9, 5, 1]
        assert [x.completed_at.day for x in await repo.get_client_visits(c.id, limit=2, offset=2)] == [1]
        assert await repo.get_client_visit_stats(c.id) == (3, 130000)


# ---------------------------------------------------------------- password hashing
def test_S1_password_hashing():
    from app.site.security import hash_password, verify_password
    h1, h2 = hash_password(PWD), hash_password(PWD)
    assert h1 != h2, "salted: two hashes of one password must differ"
    assert PWD not in h1 and verify_password(PWD, h1) and verify_password(PWD, h2)
    assert not verify_password("wrong", h1) and not verify_password("", h1) and not verify_password(PWD + " ", h1)
    for bad in ("", "x", "scrypt$", "$$$", "plain-password"):
        assert verify_password(PWD, bad) is False  # malformed stored value: False, never an exception


# ---------------------------------------------------------------- everything needs a login
@pytest.mark.asyncio
async def test_S2_anonymous_gets_no_data_and_site_is_read_only(session_factory, sample_barber):
    async with session_factory() as s:
        c1 = await _user(s, 9301, "Bobur", phone="+998901234567")
    c = await _client(session_factory)
    try:
        for path in ("/", "/clients", f"/clients/{c1.id}", "/clients?q=bobur", f"/clients/{c1.id}?page=2"):
            r = await c.get(path, allow_redirects=False)
            assert r.status in (302, 303) and r.headers["Location"].startswith("/login"), (path, r.status)
            assert "+998901234567" not in await r.text()
        for method in ("post", "put", "delete", "patch"):
            for path in ("/clients", f"/clients/{c1.id}", "/"):
                r = await getattr(c, method)(path, allow_redirects=False)
                assert r.status in (404, 405, 302, 303, 400, 403), (method, path, r.status)
                assert r.status != 200
        for path in ("/logout", "/api/clients", "/admin", "/static/../app/config.py", "/.env"):
            r = await c.get(path, allow_redirects=False)
            assert r.status in (404, 405, 302, 303), (path, r.status)
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S3_login_success_failure_and_cookie_flags(session_factory):
    c = await _client(session_factory, secure=True)  # Secure cookies: only the Set-Cookie headers are inspected here
    try:
        r = await c.get("/login")
        assert r.status == 200
        csrf = _csrf(await r.text())
        for h in r.headers.getall("Set-Cookie", []):
            assert "HttpOnly" in h and "Secure" in h and "SameSite=Strict" in h, h
        bad = await c.post("/login", data={"username": USER, "password": "nope", "csrf": csrf}, allow_redirects=False)
        assert bad.status == 401
        ok = await c.post("/login", data={"username": USER, "password": PWD, "csrf": csrf}, allow_redirects=False)
        assert ok.status in (302, 303) and ok.headers["Location"].startswith("/")
        cookies = ok.headers.getall("Set-Cookie", [])
        assert cookies, "a session cookie must be set on success"
        for h in cookies:
            assert "HttpOnly" in h and "Secure" in h and "SameSite=Strict" in h, h
            assert USER not in h.split(";")[0].split("=", 1)[1] and PWD not in h
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S4_csrf_is_required_on_login_and_logout(session_factory):
    c = await _client(session_factory)
    try:
        r = await c.post("/login", data={"username": USER, "password": PWD}, allow_redirects=False)
        assert r.status in (400, 403)
        r = await c.post("/login", data={"username": USER, "password": PWD, "csrf": "forged"}, allow_redirects=False)
        assert r.status in (400, 403)
        assert (await c.get("/clients", allow_redirects=False)).status in (302, 303)
        ok = await _login(c)
        assert ok.status in (302, 303)
        assert (await c.get("/clients", allow_redirects=False)).status == 200
        r = await c.post("/logout", data={}, allow_redirects=False)
        assert r.status in (400, 403)
        assert (await c.get("/clients", allow_redirects=False)).status == 200, "logout without csrf must not log out"
        assert (await c.get("/logout", allow_redirects=False)).status in (404, 405)
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S5_brute_force_lockout_then_recovery(session_factory):
    clock = Clock()
    c = await _client(session_factory, clock=clock)
    try:
        for _ in range(5):
            assert (await _login(c, password="wrong")).status == 401
        r = await _login(c, password=PWD)  # even the CORRECT password is refused while locked
        assert r.status == 429 and "Retry-After" in r.headers
        clock.t += 16 * 60
        assert (await _login(c, password=PWD)).status in (302, 303)
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S6_session_expires_and_logout_kills_it_server_side(session_factory):
    clock = Clock()
    c = await _client(session_factory, clock=clock)
    try:
        assert (await _login(c)).status in (302, 303)
        page = await c.get("/clients"); assert page.status == 200
        stolen = "; ".join(f"{k}={m.value}" for k, m in c.session.cookie_jar.filter_cookies(c.make_url("/")).items())
        csrf = re.search(r'name="csrf"[^>]*value="([^"]*)"', await page.text())
        assert csrf, "the page must carry a csrf token for the logout form"
        r = await c.post("/logout", data={"csrf": csrf.group(1)}, allow_redirects=False)
        assert r.status in (302, 303)
        c.session.cookie_jar.clear()
        r = await c.get("/clients", headers={"Cookie": stolen}, allow_redirects=False)
        assert r.status in (302, 303), "a copied session cookie must be useless after logout"
        # absolute expiry after 8 hours
        c.session.cookie_jar.clear()
        assert (await _login(c)).status in (302, 303)
        assert (await c.get("/clients", allow_redirects=False)).status == 200
        clock.t += 8 * 3600 + 1
        assert (await c.get("/clients", allow_redirects=False)).status in (302, 303)
    finally:
        await c.close()


# ---------------------------------------------------------------- pages
@pytest.mark.asyncio
async def test_S7_clients_page_content_escaping_search_and_headers(session_factory, sample_barber):
    async with session_factory() as s:
        for i in range(30):
            await _user(s, 9500 + i, f"Many{i:02d}", phone=f"+99897{i:07d}")
        await _user(s, 9401, "Bo<b", phone="+998901234567", username="bobur_k")   # newest clients are listed first
        await _user(s, 9402, "Sardor", phone="+998931112233")
        await _user(s, 9403, "StaffGuy", role=UserRole.BARBER.value, phone="+998900000000")
    c = await _client(session_factory)
    try:
        await _login(c)
        r = await c.get("/clients"); html = await r.text()
        assert r.status == 200
        assert "+998901234567" in html and "Bo&lt;b" in html and "Bo<b" not in html
        assert "StaffGuy" not in html and "+998900000000" not in html, "staff are never listed"
        assert len(re.findall(r"/clients/\d+", html)) >= 25 and len(set(re.findall(r"/clients/(\d+)", html))) <= 25 + 2
        h = r.headers
        assert "no-store" in h.get("Cache-Control", "")
        assert h.get("X-Frame-Options", "").upper() == "DENY" and h.get("X-Content-Type-Options", "").lower() == "nosniff"
        assert "default-src 'self'" in h.get("Content-Security-Policy", "")
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), "no inline scripts"
        for q, expect in (("901234567", "Bo&lt;b"), ("sard", "Sardor"), ("@bobur_k", "Bo&lt;b"), ("93 111", "Sardor")):
            body = await (await c.get("/clients", params={"q": q})).text()
            assert expect in body, q
        r = await c.get("/clients", params={"q": "<script>alert(1)</script>"})
        assert r.status == 200 and "<script>alert(1)</script>" not in await r.text()
        for q in ("' OR 1=1 --", "%", "_", "\\", "a" * 5000, "\x00"):
            r = await c.get("/clients", params={"q": q}); body = await r.text()
            assert r.status < 500, q
            assert "Sardor" not in body and "Bo&lt;b" not in body, q
        for p in ("0", "-1", "abc", "99999", "1e9"):
            assert (await c.get("/clients", params={"page": p})).status < 500, p
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S8_client_card_dates_prices_pagination_and_404(session_factory, sample_barber):
    async with session_factory() as s:
        cl = await _user(s, 9601, "Bobur", phone="+998901234567")
        staff = await _user(s, 9602, "StaffGuy", role=UserRole.BARBER.value, phone="+998900000000")
        # 2026-07-12 20:00 UTC == 13.07.2026 01:00 Tashkent
        await _visit(s, sample_barber, cl, datetime(2026, 7, 12, 20, 0, tzinfo=timezone.utc), "Svc00", 30000)
        for d in range(1, 12):
            await _visit(s, sample_barber, cl, datetime(2026, 7, d, 8, 0, tzinfo=timezone.utc), f"Svc{d:02d}", 10000)
    c = await _client(session_factory)
    try:
        await _login(c)
        r = await c.get(f"/clients/{cl.id}"); html = await r.text()
        assert r.status == 200 and "+998901234567" in html
        assert "13.07.2026" in html and "12.07.2026" not in html, "dates in Tashkent time, dd.mm.yyyy"
        assert "Svc00" in html and "Svc11" in html and "Svc01" not in html and "Svc02" not in html  # page 1 has 10 visits (newest first)
        assert re.search(r"30[  ,]?000", html)
        assert re.search(r"\b12\b", html) and re.search(r"140[  ,]?000", html)  # 12 visits, total 30000 + 11*10000
        p2 = await (await c.get(f"/clients/{cl.id}", params={"page": 2})).text()
        assert "Svc01" in p2 and "Svc02" in p2 and "Svc11" not in p2
        for bad in (f"/clients/{staff.id}", "/clients/999999", "/clients/abc", "/clients/0", "/clients/-1"):
            assert (await c.get(bad)).status == 404, bad
        for p in ("0", "-5", "zzz", "99999"):
            assert (await c.get(f"/clients/{cl.id}", params={"page": p})).status < 500, p
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_S9_audit_log_never_contains_secrets(session_factory, sample_barber):
    async with session_factory() as s:
        cl = await _user(s, 9701, "Bobur", phone="+998901234567")
    c = await _client(session_factory)
    try:
        await _login(c, password="wrongpass-123")
        await _login(c)
        await c.get(f"/clients/{cl.id}")
    finally:
        await c.close()
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    actions = [r.action for r in rows]
    assert "SITE_LOGIN_FAIL" in actions and "SITE_LOGIN_OK" in actions and "SITE_CLIENT_VIEW" in actions, actions
    view = next(r for r in rows if r.action == "SITE_CLIENT_VIEW")
    assert view.entity_id == str(cl.id)
    dump = " ".join(str(r.data) + str(r.entity_id) for r in rows)
    assert PWD not in dump and "wrongpass-123" not in dump


# ---------------------------------------------------------------- configuration
def _prod(**kw):
    base = dict(ENV="production", BOT_TOKEN="123456789:test_token_string_for_unit_tests", OWNER_TELEGRAM_IDS=[9990001],
                WEBHOOK_SECRET="a" * 32, WEBHOOK_PATH_SECRET="b" * 32, CRON_SECRET="c" * 32,
                DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/barbershop",
                ENABLED_PAYMENT_METHODS=["CASH"], PAYMENTS_MODE="live")
    base.update(kw)
    return Settings(**base)


def test_S10_site_settings_defaults_and_production_rules():
    from app.site.security import hash_password
    assert Settings.model_fields["SITE_ENABLED"].default is False
    assert Settings.model_fields["SITE_SECURE_COOKIES"].default is True
    _prod().validate_runtime()                                        # site off: nothing about the site is required
    good = dict(SITE_ENABLED=True, SITE_USERNAME="owner", SITE_PASSWORD_HASH=hash_password(PWD), SITE_SESSION_SECRET="k" * 40)
    _prod(**good).validate_runtime()
    for key, bad, word in (("SITE_PASSWORD_HASH", "", "SITE_PASSWORD_HASH"),
                           ("SITE_PASSWORD_HASH", "plain-text-password", "SITE_PASSWORD_HASH"),
                           ("SITE_SESSION_SECRET", "short", "SITE_SESSION_SECRET"),
                           ("SITE_SESSION_SECRET", "CHANGE_ME" + "x" * 40, "SITE_SESSION_SECRET"),
                           ("SITE_SECURE_COOKIES", False, "SITE_SECURE_COOKIES"),
                           ("SITE_USERNAME", "", "SITE_USERNAME")):
        with pytest.raises(ValueError) as exc:
            _prod(**{**good, key: bad}).validate_runtime()
        assert word in str(exc.value), (key, str(exc.value))
