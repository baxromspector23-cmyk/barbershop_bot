"""READ-ONLY reviewer tests, round 6. Do not edit, rename, move or delete this file.
Run: pytest tests/test_review_round6.py   (SQLite and PostgreSQL; the load tests need PostgreSQL and are skipped on SQLite)
"""
from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Contact, Message
from sqlalchemy import func, select

from app.config import Settings, settings
from app.handlers.common import handle_client_registration_phone, handle_start
from app.handlers.owner import handle_owner_info_menu
from app.models.enums import Language, OrderStatus, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.services.queue_service import QueueService

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
pg_only = pytest.mark.skipif("postgresql" not in TEST_DB_URL, reason="load tests need real PostgreSQL")
BARBER_TG = 111111  # sample_barber's telegram id


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    getattr(QueueService, "_barber_locks", {}).clear()
    monkeypatch.setattr(settings, "OWNER_TELEGRAM_IDS", [990001])


def _state():
    s = MagicMock(); s.set_state = AsyncMock(); s.clear = AsyncMock(); return s


def _cmd(args=""):
    c = MagicMock(); c.args = args; return c


async def _mk(session, role, first="Ali", username=None, phone=None, tg=5000, lang=Language.UZ.value):
    u = User(telegram_id=tg, username=username, first_name=first, last_name=None, language=lang, role=role, phone=phone)
    session.add(u); await session.commit(); await session.refresh(u); return u


def _texts(msg):
    out = []
    for c in msg.answer.call_args_list:
        out.append(c[0][0] if c[0] else c[1].get("text", ""))
    return "\n".join(out)


# ---------------------------------------------------------------- Z1 HTML escaping
@pytest.mark.asyncio
@pytest.mark.parametrize("evil", ["<b", "A&B<i>", "</a>x"])
async def test_Z1_start_profile_escapes_user_names(session_factory, evil):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first=evil, phone="+998901234567", tg=5001)
        msg = MagicMock(spec=Message); msg.answer = AsyncMock()
        await handle_start(msg, _cmd(), s, u, "uz", _state())
        import html
        assert html.escape(evil) in _texts(msg)
        assert evil not in _texts(msg).replace(html.escape(evil), "")


@pytest.mark.asyncio
async def test_Z2_owner_info_panel_escapes_names(session_factory):
    async with session_factory() as s:
        owner = await _mk(s, UserRole.OWNER.value, first="Own", phone="+998900000000", tg=5002)
        await _mk(s, UserRole.CLIENT.value, first="A<b", phone="+998901111111", tg=5003)
        msg = MagicMock(spec=Message); msg.answer = AsyncMock()
        await handle_owner_info_menu(msg, s, owner, "uz")
        txt = _texts(msg)
        assert "A&lt;b" in txt and "A<b" not in txt


# ---------------------------------------------------------------- Z3 staff are not forced to register as clients
@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.OWNER.value, UserRole.BARBER.value])
async def test_Z3_staff_without_phone_are_not_sent_to_client_registration(session_factory, role):
    async with session_factory() as s:
        u = await _mk(s, role, first="Staff", phone=None, tg=5004)
        msg = MagicMock(spec=Message); msg.answer = AsyncMock()
        st = _state()
        await handle_start(msg, _cmd(), s, u, "uz", st)
        assert not st.set_state.await_args_list


# ---------------------------------------------------------------- Z4/Z5 phone validation
@pytest.mark.asyncio
async def test_Z4_contact_of_another_person_is_rejected(session_factory):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first="Cli", phone=None, tg=5005)
        msg = MagicMock(spec=Message)
        msg.contact = Contact(phone_number="+998777777777", first_name="Other", user_id=999999)
        msg.text = None; msg.from_user = MagicMock(id=5005); msg.answer = AsyncMock()
        st = _state()
        await handle_client_registration_phone(msg, s, u, st, "uz")
        assert u.phone is None
        st.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_Z4b_own_contact_is_accepted(session_factory):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first="Cli", phone=None, tg=5006)
        msg = MagicMock(spec=Message)
        msg.contact = Contact(phone_number="998901234567", first_name="Cli", user_id=5006)
        msg.text = None; msg.from_user = MagicMock(id=5006); msg.answer = AsyncMock()
        await handle_client_registration_phone(msg, s, u, _state(), "uz")
        assert u.phone == "+998901234567"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["1234567", "0000000", "+++1234567", "abc", "12345678901234567890", "+998 12", "901234"])
async def test_Z5_garbage_is_not_saved_as_phone(session_factory, raw):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first="Cli", phone=None, tg=5007)
        msg = MagicMock(spec=Message); msg.contact = None; msg.text = raw; msg.from_user = MagicMock(id=5007); msg.answer = AsyncMock()
        st = _state()
        await handle_client_registration_phone(msg, s, u, st, "uz")
        assert u.phone is None
        st.clear.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["+998901234567", "998901234567", "901234567", "+998 90 123-45-67", "90 123 45 67", "(90) 123-45-67"])
async def test_Z5b_valid_uzbek_numbers_are_normalized(session_factory, raw):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first="Cli", phone=None, tg=5008)
        msg = MagicMock(spec=Message); msg.contact = None; msg.text = raw; msg.from_user = MagicMock(id=5008); msg.answer = AsyncMock()
        await handle_client_registration_phone(msg, s, u, _state(), "uz")
        assert u.phone == "+998901234567"


# ---------------------------------------------------------------- Z6 languages
@pytest.mark.asyncio
@pytest.mark.parametrize("lang,alphabet", [("ru", r"[А-Яа-яЁё]"), ("uz_cyrl", r"[А-Яа-яЎўҚқҒғҲҳ]")])
async def test_Z6_new_client_start_and_registration_are_in_own_language(session_factory, lang, alphabet):
    async with session_factory() as s:
        u = await _mk(s, UserRole.CLIENT.value, first="Ivan", phone=None, tg=5009, lang=lang)
        msg = MagicMock(spec=Message); msg.answer = AsyncMock()
        await handle_start(msg, _cmd(), s, u, lang, _state())
        txt = _texts(msg)
        assert "Assalomu" not in txt and "Telefon" not in txt and "ro'yxat" not in txt
        # contact-request keyboard text is translated too
        assert re.search(alphabet, txt)


# ---------------------------------------------------------------- Z7 config
def test_Z7_check_working_hours_default_matches_env_example():
    default = Settings.model_fields["CHECK_WORKING_HOURS"].default
    m = re.search(r"^CHECK_WORKING_HOURS=(\w+)", (ROOT / ".env.example").read_text(), re.M)
    assert m, ".env.example must set CHECK_WORKING_HOURS"
    assert (m.group(1).lower() == "true") == bool(default)


# ---------------------------------------------------------------- Z8 "arrived" must not skip the queue
@pytest.mark.asyncio
async def test_Z8_arrived_on_waiting_order_never_starts_service_out_of_order(session_factory, sample_barber, sample_clients, mock_notifier):
    from app.handlers.barber import handle_b_arrived
    sid = sample_barber.services[0].id
    ids = []
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        for c in sample_clients[:3]:
            o = await qs.join_queue(sample_barber.id, sid, c, pay_now=False)
            ids.append(o.id)
        await s.commit()
    # odd state: the first order vanished without promotion (e.g. a crash); #2 and #3 are WAITING
    async with session_factory() as s:
        o1 = await s.get(Order, ids[0]); o1.status = OrderStatus.CANCELLED_BY_STAFF.value; await s.commit()
    async with session_factory() as s:
        barber_user = await s.get(User, sample_barber.user_id)
        call = MagicMock(); call.data = f"b_arrived:{ids[2]}"; call.answer = AsyncMock(); call.message = MagicMock()
        call.message.edit_reply_markup = AsyncMock()
        await handle_b_arrived(call, s, barber_user, MagicMock(), "uz")
    async with session_factory() as s:
        o3 = await s.get(Order, ids[2])
        assert o3.status != OrderStatus.IN_SERVICE.value, "client #3 was served before client #2"


# ---------------------------------------------------------------- Z9 colors: exactly the agreed buttons
def test_Z9_only_agreed_buttons_have_a_style(monkeypatch):
    import app.keyboards.common as kc
    from app.keyboards import barber as kb_b, client as kb_c, owner as kb_o
    from app.models.order import Order as O
    from app.services.manual_payment_service import build_receipt_review_keyboard

    seen: list[tuple[str, str | None]] = []
    real = kc.InlineKeyboardButton

    def spy(**kw):
        seen.append((kw.get("callback_data") or kw.get("url") or "", kw.get("style")))
        return real(**kw)
    monkeypatch.setattr(kc, "InlineKeyboardButton", spy)

    def order(status):
        o = O(); o.id = 7; o.status = status; return o
    for lang in ("uz", "uz_cyrl", "ru"):
        kb_c.get_client_inline_menu(lang); kb_c.get_my_queue_keyboard(7, lang); kb_c.get_cancel_confirm_keyboard(7, lang)
        kb_c.get_payment_methods_keyboard(7, lang); kb_c.get_payment_timing_keyboard(1, 2, lang)
        kb_c.get_receipt_prompt_keyboard(7, lang); kb_c.get_receipt_cancel_keyboard(lang)
        for paused in (True, False):
            kb_b.get_barber_inline_menu(paused, lang); kb_o.get_owner_inline_menu(paused, lang)
        for st in (OrderStatus.CALLED.value, OrderStatus.IN_SERVICE.value, OrderStatus.WAITING.value):
            kb_b.get_barber_order_actions(order(st), lang)
        kb_o.get_reports_keyboard("today", 0, lang); kb_o.get_refund_action_keyboard(7, lang)
        build_receipt_review_keyboard(7, lang)

    allowed = {
        "c_menu:join": "success", "pay_timing:after": "success", "b_done": "success", "tr_ok": "success",
        "cancel_queue_prompt": "danger", "tr_no": "danger", "b_no_show": "danger",
        "pay_open": "primary", "tr_send": "primary",
    }
    got = {}
    for cb, style in seen:
        if style:
            key = ":".join(cb.split(":")[:2]) if cb.startswith(("c_menu", "pay_timing")) else cb.split(":")[0]
            got.setdefault(key, set()).add(style)
    unexpected = {k: v for k, v in got.items() if allowed.get(k) is None or v != {allowed[k]}}
    assert not unexpected, f"buttons with a style that were not agreed: {unexpected}"
    missing = set(allowed) - set(got)
    assert not missing, f"agreed buttons without a style: {missing}"


# ---------------------------------------------------------------- Z10 Telegram flood control
@pytest.mark.asyncio
async def test_Z10_retry_after_is_honoured_not_lost(monkeypatch):
    from app.services import notification_service as ns
    slept = []

    async def fake_sleep(x):
        slept.append(x)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    bot = MagicMock()
    calls = {"n": 0}

    async def send_message(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TelegramRetryAfter(method=MagicMock(), message="Flood", retry_after=2)
        return MagicMock()
    bot.send_message = send_message
    ok = await ns.NotificationService(bot=bot).send_message(1, "hi")
    assert ok is True and calls["n"] == 2 and slept, "TelegramRetryAfter must cause a wait and ONE retry"


# ---------------------------------------------------------------- Load tests: 50 clients at the same moment (PostgreSQL)
async def _make_clients(sf, n=50):
    async with sf() as s:
        us = [User(telegram_id=700000 + i, username=f"load_{i}", first_name=f"L{i}", language=Language.UZ.value,
                   role=UserRole.CLIENT.value, phone=f"+99890{1000000+i}") for i in range(n)]
        s.add_all(us); await s.commit()
        return [u.id for u in us]


async def _join_all(sf, barber, uids, notifier):
    sid = barber.services[0].id

    async def one(uid):
        async with sf() as s:
            u = await s.get(User, uid)
            try:
                o = await QueueService(s, notifier=notifier).join_queue(barber.id, sid, u, pay_now=False)
                await s.commit(); return ("ok", o.id)
            except Exception as e:  # noqa: BLE001
                await s.rollback(); return ("err", type(e).__name__)
    return await asyncio.gather(*[one(u) for u in uids])


@pg_only
@pytest.mark.asyncio
async def test_L1_50_simultaneous_joins_respect_capacity_without_duplicates(session_factory, sample_barber, mock_notifier):
    uids = await _make_clients(session_factory)
    res = await _join_all(session_factory, sample_barber, uids, mock_notifier)
    c = Counter(r[1] if r[0] == "err" else "ok" for r in res)
    assert c["ok"] == settings.MAX_QUEUE_PER_BARBER and set(c) <= {"ok", "QueueFullError"}, c
    async with session_factory() as s:
        orders = (await s.execute(select(Order))).scalars().all()
    assert len({o.ticket_no for o in orders}) == len(orders) and len({o.position_key for o in orders}) == len(orders)
    assert Counter(o.status for o in orders)[OrderStatus.CALLED.value] == 1


@pg_only
@pytest.mark.asyncio
async def test_L2_50_joins_receipts_and_double_confirmations(session_factory, sample_barber, mock_notifier, monkeypatch):
    from app.repositories.barber_repo import BarberRepository
    from app.services.manual_payment_service import DuplicateReceiptError, ManualPaymentService
    monkeypatch.setattr(settings, "MAX_QUEUE_PER_BARBER", 100)
    uids = await _make_clients(session_factory)
    res = await _join_all(session_factory, sample_barber, uids, mock_notifier)
    oids = {u: r[1] for u, r in zip(uids, res) if r[0] == "ok"}
    assert len(oids) == 50

    async def send(i, uid):
        async with session_factory() as s:
            p = await ManualPaymentService(s, notifier=mock_notifier).submit_receipt(oids[uid], uid, f"f{i}", f"u{i}")
            await s.commit(); return p.id
    pids = await asyncio.gather(*[send(i, u) for i, u in enumerate(uids)])

    async def confirm(pid):
        async with session_factory() as s:
            staff = await s.get(User, sample_barber.user_id)
            b = await BarberRepository(s).get_by_user_id(staff.id)
            await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=b)
            await s.commit()
    await asyncio.gather(*[confirm(p) for p in pids for _ in range(2)])
    async with session_factory() as s:
        paid = (await s.execute(select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PAID.value))).scalar()
        total = (await s.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == PaymentStatus.PAID.value))).scalar()
        allp = (await s.execute(select(func.count(Payment.id)))).scalar()
    assert paid == 50 and allp == 50 and total == 50 * 50000


@pg_only
@pytest.mark.asyncio
async def test_L3_reminder_burst_is_capped_per_tick_and_per_payment(session_factory, sample_barber, mock_notifier, monkeypatch):
    from app.repositories.payment_repo import PaymentRepository
    from app.services.due_work_service import process_due_work
    from app.services.manual_payment_service import ManualPaymentService
    from app.utils.time_utils import now_utc
    monkeypatch.setattr(settings, "MAX_QUEUE_PER_BARBER", 100)
    uids = await _make_clients(session_factory)
    res = await _join_all(session_factory, sample_barber, uids, mock_notifier)
    oids = {u: r[1] for u, r in zip(uids, res)}
    pids = []
    for i, u in enumerate(uids):
        async with session_factory() as s:
            p = await ManualPaymentService(s, notifier=mock_notifier).submit_receipt(oids[u], u, f"f{i}", f"u{i}")
            await s.commit(); pids.append(p.id)

    async def age(minutes):
        async with session_factory() as s:
            for pid in pids:
                p = await PaymentRepository(s).get_by_id(pid)
                p.receipt_sent_at = now_utc() - timedelta(minutes=minutes)
            await s.commit()
    await age(6)
    mock_notifier.sent_events.clear()
    await process_due_work(session_factory, notifier=mock_notifier)
    first = [e for e in mock_notifier.sent_events if e.get("telegram_id") == BARBER_TG]
    assert 0 < len(first) <= 10, f"{len(first)} reminder messages to one barber in a single tick (Telegram flood limit)"
    # repeating ticks must eventually remind everybody but never more than 3 times per payment
    per_payment = Counter()
    for _ in range(40):
        await age(60)
        mock_notifier.sent_events.clear()
        await process_due_work(session_factory, notifier=mock_notifier)
        for e in mock_notifier.sent_events:
            if e.get("telegram_id") == BARBER_TG and e.get("reply_markup"):
                for row in e["reply_markup"].inline_keyboard:
                    for b in row:
                        if b.callback_data and b.callback_data.startswith("tr_ok:"):
                            per_payment[b.callback_data] += 1
    assert per_payment and max(per_payment.values()) <= 3
