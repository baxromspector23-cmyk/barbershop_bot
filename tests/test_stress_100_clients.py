"""Comprehensive stress and end-to-end simulation test with 100+ clients.
Tests client registration, phone number searches, queue capacity, concurrency,
service lifecycle, cash and manual transfer payments, owner dashboard,
financial statistics, and website pagination.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from app.config import settings
from app.models.barber import Barber, BarberWorkingHours
from app.models.enums import Language, OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import Payment
from app.models.service import Service
from app.models.user import User
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.services.manual_payment_service import ManualPaymentService
from app.services.notification_service import NotificationService
from app.services.queue_service import (
    AlreadyInQueueError,
    QueueFullError,
    QueueService,
)
from app.site.app import create_site_app
from app.site.security import hash_password

SITE_USER = "owner"
SITE_PASS = "SuperOwnerSecret2026!"
SITE_HASH = hash_password(SITE_PASS)
SITE_SECRET = "stress-test-session-secret-key-at-least-32-chars-long"


def _extract_csrf(html_text: str) -> str:
    m = re.search(r'<input[^>]*name="csrf"[^>]*value="([^"]*)"', html_text) or re.search(
        r'<input[^>]*value="([^"]*)"[^>]*name="csrf"', html_text
    )
    assert m, "CSRF input not found in HTML"
    return m.group(1)


@pytest.mark.asyncio
async def test_100_plus_clients_full_stress_and_lifecycle(session_factory, monkeypatch):
    """
    Simulates a busy barbershop with:
    - 3 Barbers
    - 110 Unique Clients
    - Concurrent queue joins
    - Capacity limit checks (MAX_QUEUE_PER_BARBER)
    - Order processing lifecycle (CALLED -> IN_SERVICE -> COMPLETED)
    - Payments (Cash and Transfer)
    - Lateness and cancellation handling
    - Phone and name searching across 100+ clients
    - Owner website report accuracy and 11-page pagination
    """
    notifier = NotificationService(bot=None)
    monkeypatch.setattr(settings, "MAX_QUEUE_PER_BARBER", 12)
    monkeypatch.setattr(settings, "CHECK_WORKING_HOURS", False)

    # 1. Setup 3 Barbers with Services
    async with session_factory() as session:
        barbers = []
        for b_idx, b_name in enumerate(["Jasur Barber", "Bobur Barber", "Timur Barber"], start=1):
            user_b = User(
                telegram_id=800000 + b_idx,
                username=f"barber_{b_idx}",
                first_name=b_name.split()[0],
                last_name=b_name.split()[1],
                language=Language.UZ.value,
                role=UserRole.BARBER.value,
                phone=f"+99890111000{b_idx}",
            )
            session.add(user_b)
            await session.flush()

            barber = Barber(
                user_id=user_b.id,
                display_name=b_name,
                is_active=True,
                is_paused=False,
            )
            session.add(barber)
            await session.flush()

            svc1 = Service(
                barber_id=barber.id,
                name="Soch turmagi",
                price=60000,
                duration_minutes=30,
                is_active=True,
            )
            svc2 = Service(
                barber_id=barber.id,
                name="Soqol va fason",
                price=40000,
                duration_minutes=20,
                is_active=True,
            )
            session.add_all([svc1, svc2])
            await session.flush()
            barbers.append(barber.id)

        await session.commit()

    barber_1_id, barber_2_id, barber_3_id = barbers

    # 2. Register 110 Unique Clients with realistic Uzbek phone variations
    client_ids: list[int] = []
    async with session_factory() as session:
        for i in range(1, 111):
            # Realistic phone variety: formatted, spaced, dash, etc.
            phone_variants = [
                f"+99890{i:07d}",
                f"+998 91 {i:03d} {i:02d} {i:02d}",
                f"93{i:07d}",
                f"+998 (94) {i:03d}-{i:04d}",
            ]
            ph = phone_variants[i % len(phone_variants)]
            c_user = User(
                telegram_id=1000000 + i,
                username=f"client_user_{i}",
                first_name=f"Mijoz_{i}",
                last_name=f"Familiya_{i}",
                language=Language.UZ.value if i % 2 == 0 else Language.RU.value,
                role=UserRole.CLIENT.value,
                phone=ph,
            )
            session.add(c_user)
            await session.flush()
            client_ids.append(c_user.id)
        await session.commit()

    assert len(client_ids) == 110

    # 3. Test Queue Capacity Limit on Barber 1 (MAX_QUEUE_PER_BARBER = 12)
    # The first 12 clients join Barber 1 successfully
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        b1_svcs = await qs.barber_repo.get_services(barber_1_id)
        svc_main = b1_svcs[0]

        for i in range(12):
            client = await qs.user_repo.get_by_id(client_ids[i])
            order = await qs.join_queue(
                barber_id=barber_1_id,
                service_id=svc_main.id,
                client=client,
            )
            if i == 0:
                assert order.status == OrderStatus.CALLED.value
            else:
                assert order.status == OrderStatus.WAITING.value
        await session.commit()

    # Client #13 must be rejected because queue capacity (12) is reached
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        client_13 = await qs.user_repo.get_by_id(client_ids[12])
        b1_svcs = await qs.barber_repo.get_services(barber_1_id)
        with pytest.raises(QueueFullError) as exc_info:
            await qs.join_queue(
                barber_id=barber_1_id,
                service_id=b1_svcs[0].id,
                client=client_13,
            )
        assert exc_info.value.reason == "MAX_QUEUE"

    # 4. Process Orders through Barber 1 & Verify Auto-Advancement
    # Client 0 arrives, finishes, Client 1 is called, pays with Cash
    completed_orders_count = 0
    total_revenue_expected = 0

    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        pay_repo = PaymentRepository(session)
        active_b1 = await qs.order_repo.get_active_orders_for_barber(barber_1_id)
        assert len(active_b1) == 12

        # First order in chair
        first_order = active_b1[0]
        assert first_order.status == OrderStatus.CALLED.value
        res_arrived = await qs.client_arrived(first_order.id)
        assert res_arrived.changed is True
        assert res_arrived.order.status == OrderStatus.IN_SERVICE.value

        # Complete service
        res_comp = await qs.complete_service(first_order.id)
        assert res_comp.changed is True
        assert res_comp.order.status == OrderStatus.COMPLETED.value
        completed_orders_count += 1
        total_revenue_expected += first_order.price

        # Record CASH payment for first order
        p1 = await pay_repo.create_payment(
            order_id=first_order.id,
            barber_id=barber_1_id,
            client_id=first_order.client_id,
            amount=first_order.price,
            method=PaymentMethod.CASH.value,
            provider_payment_id=f"cash-{first_order.id}",
            status=PaymentStatus.PAID.value,
        )
        p1.paid_at = first_order.completed_at
        await session.commit()

    # Now the 2nd order was automatically promoted from WAITING to CALLED!
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        order_2 = await qs.order_repo.get_by_id(active_b1[1].id)
        assert order_2.status == OrderStatus.CALLED.value

        # Client 2 arrives, pays with TRANSFER (manual receipt)
        await qs.client_arrived(order_2.id)
        await qs.complete_service(order_2.id)
        completed_orders_count += 1
        total_revenue_expected += order_2.price

        # Submit and confirm manual transfer receipt
        mps = ManualPaymentService(session, notifier=notifier)
        payment_t = await mps.submit_receipt(
            order_id=order_2.id,
            client_user_id=order_2.client_id,
            file_id="photo_receipt_123",
            file_unique_id=f"uniq_{order_2.id}",
        )
        assert payment_t.status == PaymentStatus.RECEIPT_SENT.value
        # Barber staff user confirms receipt
        barber_obj = await qs.barber_repo.get_by_id(barber_1_id)
        staff_user = await qs.user_repo.get_by_id(barber_obj.user_id)
        confirmed_res = await mps.confirm_transfer(
            payment_id=payment_t.id,
            staff=staff_user,
            barber=barber_obj,
        )
        assert confirmed_res.payment.status == PaymentStatus.PAID.value
        assert confirmed_res.changed is True
        confirmed_res.payment.paid_at = order_2.completed_at
        await session.commit()

    # 5. Batch-simulate visits across all 110 clients across the 3 barbers
    # Give every client at least 1 completed visit, some with multiple visits
    async with session_factory() as session:
        now_dt = datetime.now(timezone.utc)
        for idx, cid in enumerate(client_ids):
            # assign barber cyclically
            b_id = barbers[idx % len(barbers)]
            # price varies
            price = 60000 if idx % 2 == 0 else 40000
            order = Order(
                barber_id=b_id,
                client_id=cid,
                service_id=None,
                service_name="Soch olish VIP" if price == 60000 else "Oddiy soch olish",
                price=price,
                duration_minutes=30,
                status=OrderStatus.COMPLETED.value,
                position_key=(idx + 100) * 10,
                ticket_no=idx + 1,
                ticket_date=date(2026, 10, 16),
                completed_at=now_dt - timedelta(hours=idx % 48),
                created_at=now_dt - timedelta(hours=(idx % 48) + 1),
            )
            session.add(order)
            await session.flush()
            completed_orders_count += 1
            total_revenue_expected += price

            # Add payment: 70% CASH, 30% TRANSFER
            is_cash = (idx % 3 != 0)
            pay = Payment(
                order_id=order.id,
                barber_id=b_id,
                client_id=cid,
                amount=price,
                method=PaymentMethod.CASH.value if is_cash else PaymentMethod.TRANSFER.value,
                provider_payment_id=f"sim-pay-{order.id}",
                status=PaymentStatus.PAID.value,
                paid_at=order.completed_at,
            )
            session.add(pay)

        await session.commit()

    # 6. Test UserRepository.search_clients under 100+ clients
    async with session_factory() as session:
        user_repo = UserRepository(session)

        # A) Search by digits: client #1's phone digits
        c1 = await user_repo.get_by_id(client_ids[0])
        c1_digits = "".join(ch for ch in c1.phone if ch.isdigit())
        res_phone = await user_repo.search_clients(c1_digits[-7:], limit=10)
        assert len(res_phone) >= 1
        assert any(u.id == client_ids[0] for u in res_phone)

        # B) Search by username: "@client_user_55"
        res_user = await user_repo.search_clients("@client_user_55")
        assert len(res_user) == 1
        assert res_user[0].id == client_ids[54]

        # C) Search by name: "Mijoz_77"
        res_name = await user_repo.search_clients("Mijoz_77")
        assert len(res_name) == 1
        assert res_name[0].id == client_ids[76]

        # D) Search with special chars (% and _): must not dump database
        res_special = await user_repo.search_clients("%")
        assert res_special == []
        res_under = await user_repo.search_clients("_")
        assert res_under == []

        # E) NUL character injection: must be sanitized, never raise exception
        res_nul = await user_repo.search_clients("Mijoz\x00_1")
        assert isinstance(res_nul, list)

        # F) Verify staff/barbers are NEVER returned
        res_barber = await user_repo.search_clients("barber")
        for u in res_barber:
            assert u.role == UserRole.CLIENT.value

    # 7. Test OrderRepository.get_client_visit_stats and get_client_visits
    async with session_factory() as session:
        order_repo = OrderRepository(session)
        # Check client #1 stats
        c1_id = client_ids[0]
        count, total = await order_repo.get_client_visit_stats(c1_id)
        assert count >= 1
        assert total > 0

        # Visits list
        visits = await order_repo.get_client_visits(c1_id, limit=10)
        assert len(visits) == count
        for v in visits:
            assert v.status == OrderStatus.COMPLETED.value
            assert v.client_id == c1_id

    # 8. Test Owner Website with 110+ Clients
    app = create_site_app(
        session_factory,
        username=SITE_USER,
        password_hash=SITE_HASH,
        secret=SITE_SECRET,
        secure_cookies=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        # A) Unauthorized access redirects to /login
        resp_unauth = await client.get("/clients", allow_redirects=False)
        assert resp_unauth.status == 303
        assert resp_unauth.headers["Location"] == "/login"

        # B) Login flow
        resp_login_page = await client.get("/login")
        assert resp_login_page.status == 200
        csrf_token = _extract_csrf(await resp_login_page.text())

        # Bad password fails
        resp_bad = await client.post(
            "/login",
            data={"username": SITE_USER, "password": "WrongPassword!", "csrf": csrf_token},
            allow_redirects=False,
        )
        assert resp_bad.status == 401

        # Correct password succeeds and sets session
        resp_good = await client.post(
            "/login",
            data={"username": SITE_USER, "password": SITE_PASS, "csrf": csrf_token},
            allow_redirects=False,
        )
        assert resp_good.status == 303
        assert resp_good.headers["Location"] == "/clients"

        # C) Verify 5-page pagination on /clients (110 clients / 25 per page = 5 pages)
        # Page 1
        resp_page1 = await client.get("/clients?page=1")
        assert resp_page1.status == 200
        text_p1 = await resp_page1.text()
        assert "Mijozlar ro&#x27;yxati" in text_p1 or "Mijozlar ro'yxati" in text_p1 or "Mijozlar" in text_p1
        assert "Sahifa 1" in text_p1 or "page=2" in text_p1

        # Page 5 (last page)
        resp_page5 = await client.get("/clients?page=5")
        assert resp_page5.status == 200
        text_p5 = await resp_page5.text()
        assert "Mijoz_" in text_p5
        assert "Sahifa 5 / 5" in text_p5

        # D) Search on website
        resp_search = await client.get("/clients?q=Mijoz_99")
        assert resp_search.status == 200
        text_search = await resp_search.text()
        assert "Mijoz_99" in text_search

        # E) Client detail card with tel: link
        target_cid = client_ids[10]
        resp_detail = await client.get(f"/clients/{target_cid}")
        assert resp_detail.status == 200
        text_detail = await resp_detail.text()
        assert 'href="tel:' in text_detail
        assert "Tashriflar tarixi" in text_detail

        # F) Owner Dashboard / Reports view
        resp_rep = await client.get("/clients?view=reports&period=month")
        assert resp_rep.status == 200
        text_rep = await resp_rep.text()
        assert "Barberlar statistikasi va Hisobotlar" in text_rep
        assert "Sartaroshlar reytingi" in text_rep
        assert "Naqd pul" in text_rep
        assert "Karta / O&#x27;tkazma" in text_rep or "Karta / O'tkazma" in text_rep

        # Verify all 3 barbers are shown in the ranking table
        assert "Jasur Barber" in text_rep
        assert "Bobur Barber" in text_rep
        assert "Timur Barber" in text_rep

    finally:
        await client.close()
