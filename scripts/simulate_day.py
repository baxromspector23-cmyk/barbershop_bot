#!/usr/bin/env python3
"""
scripts/simulate_day.py
Simulates a full working day at the barbershop through the services layer without Telegram.
Demonstrates:
- Owner and 3 barbers working with separate queues
- Sequential arrival, instant call on empty queue, heads-up notifications
- Prepaid and pay-after flows (Click, Payme, Cash)
- Lateness handling (moves back, 3rd time no-show cancellation)
- Walk-in clients added manually
- Due work background tick execution
- Final owner report generation and barber ranking display
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import time, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.barber import Barber, BarberWorkingHours
from app.models.enums import Language, PaymentMethod, UserRole
from app.models.service import Service
from app.models.user import User
from app.services.due_work_service import process_due_work
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.services.report_service import ReportService
from app.utils.formatting import format_money


import tempfile
import uuid

async def main():
    print("=" * 70)
    print("💈 BARBERSHOP DAY SIMULATION (Tashkent Timezone: Asia/Tashkent) 💈")
    print("=" * 70)

    temp_db_path = None
    if "DATABASE_URL" in os.environ:
        db_url = os.environ["DATABASE_URL"]
    else:
        temp_dir = tempfile.gettempdir()
        temp_db_path = os.path.join(temp_dir, f"simulated_day_{uuid.uuid4().hex}.db")
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"

    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    notifier = NotificationService(bot=None)

    # 1. Setup Owner & 3 Small Barbers
    print("\n[1] Boshlang'ich ma'lumotlar yaratilmoqda: 1 Owner (Katta Barber) + 3 Barber...")
    barber_ids = []
    async with session_factory() as session:
        # Owner
        owner_user = User(
            telegram_id=10001,
            username="katta_barber",
            first_name="Rustam",
            last_name="Katta Barber",
            language=Language.UZ.value,
            role=UserRole.OWNER.value,
        )
        session.add(owner_user)
        await session.flush()

        owner_barber = Barber(user_id=owner_user.id, display_name="Rustam Aka (Owner)", is_active=True)
        session.add(owner_barber)
        await session.flush()
        barber_ids.append((owner_barber.id, "Rustam Aka (Owner)"))

        # 3 Small Barbers
        barber_names = [("Ali", "ali_barber"), ("Vali", "vali_barber"), ("Gani", "gani_barber")]
        for idx, (b_name, b_user) in enumerate(barber_names, 2):
            u = User(
                telegram_id=10000 + idx,
                username=b_user,
                first_name=b_name,
                language=Language.UZ.value,
                role=UserRole.BARBER.value,
            )
            session.add(u)
            await session.flush()
            b = Barber(user_id=u.id, display_name=f"{b_name} Barber", is_active=True)
            session.add(b)
            await session.flush()
            barber_ids.append((b.id, f"{b_name} Barber"))

        # Add working hours and services for each barber
        for b_id, _ in barber_ids:
            for w in range(7):
                session.add(
                    BarberWorkingHours(
                        barber_id=b_id,
                        weekday=w,
                        start_time=time(0, 0),
                        end_time=time(23, 59),
                        is_day_off=False,
                    )
                )
            session.add(
                Service(barber_id=b_id, name="Soch olish", price=60000, duration_minutes=30, is_active=True)
            )
            session.add(
                Service(barber_id=b_id, name="Soqol tekislash", price=30000, duration_minutes=20, is_active=True)
            )

        # Create clients
        clients = []
        for i in range(1, 15):
            c = User(
                telegram_id=20000 + i,
                username=f"client_{i}",
                first_name=f"Mijoz_{i}",
                language=Language.UZ.value,
                role=UserRole.CLIENT.value,
            )
            session.add(c)
            clients.append(c)

        await session.commit()

    print(f"✅ {len(barber_ids)} ta barber va {len(clients)} ta mijoz tayyorlandi.")

    # 2. Simulate client joins and activities
    print("\n[2] Kun davomida navbatlar va xizmatlar simulatsiya qilinmoqda...")

    # Barber 1 (Ali)
    ali_id = barber_ids[1][0]
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        ps = PaymentService(session, notifier=notifier)
        services = await qs.barber_repo.get_services(ali_id)
        s1 = services[0]

        # Client 1 joins Ali -> CALLED immediately
        o1 = await qs.join_queue(ali_id, s1.id, clients[0], pay_now=False)
        # Client 2 joins Ali -> WAITING, ahead=1 -> heads-up sent
        o2 = await qs.join_queue(ali_id, s1.id, clients[1], pay_now=False)
        # Client 3 joins Ali -> WAITING
        o3 = await qs.join_queue(ali_id, s1.id, clients[2], pay_now=False)
        await session.commit()

        # Ali accepts Client 1
        await qs.client_arrived(o1.id)
        # Ali finishes Client 1
        await qs.complete_service(o1.id)
        # Client 1 pays via Click
        await ps.handle_successful_payment(PaymentMethod.CLICK.value, "sim_click_1", o1.price, o1.id)
        await session.commit()

        # Client 2 was CALLED automatically. But Client 2 is late!
        await qs.handle_lateness(o2.id)  # moves back 1 place, o3 called!
        await session.commit()

        # Ali accepts Client 3
        await qs.client_arrived(o3.id)
        await qs.complete_service(o3.id)
        # Client 3 pays Cash
        await ps.confirm_cash_payment(o3.id, 10002)
        await session.commit()

        # Now Client 2 is CALLED again. Client 2 is late again (2nd time)
        await qs.handle_lateness(o2.id)
        # 3rd lateness -> CANCELLED_NO_SHOW!
        await qs.handle_lateness(o2.id)
        await session.commit()

    # Barber 2 (Vali)
    vali_id = barber_ids[2][0]
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        ps = PaymentService(session, notifier=notifier)
        services = await qs.barber_repo.get_services(vali_id)
        s1 = services[0]

        # Client 4 joins Vali with prepaid Payme
        o4 = await qs.join_queue(vali_id, s1.id, clients[3], pay_now=True)
        await ps.handle_successful_payment(PaymentMethod.PAYME.value, "sim_payme_4", o4.price, o4.id)
        await session.commit()

        # Vali accepts and finishes
        await qs.client_arrived(o4.id)
        await qs.complete_service(o4.id)
        await session.commit()

        # Vali adds a Walk-in client (no telegram)
        o_walkin = await qs.join_queue(
            vali_id,
            s1.id,
            client=None,
            walkin_name="Jasur (Walk-in)",
            walkin_phone="+998901234567",
            pay_now=False,
        )
        await qs.client_arrived(o_walkin.id)
        await qs.complete_service(o_walkin.id)
        await ps.confirm_cash_payment(o_walkin.id, 10003)
        await session.commit()

    # Barber 0 (Owner Rustam Aka)
    owner_id = barber_ids[0][0]
    async with session_factory() as session:
        qs = QueueService(session, notifier=notifier)
        ps = PaymentService(session, notifier=notifier)
        services = await qs.barber_repo.get_services(owner_id)
        s1 = services[0]

        # 3 clients served by Owner
        for c in [clients[4], clients[5], clients[6]]:
            o = await qs.join_queue(owner_id, s1.id, c, pay_now=False)
            await qs.client_arrived(o.id)
            await qs.complete_service(o.id)
            await ps.confirm_cash_payment(o.id, 10001)
            await session.commit()

    # 3. Run background tick
    print("\n[3] Background process_due_work() tekshiruv va tozalash ishga tushirildi...")
    tick_results = await process_due_work(session_factory, notifier=notifier)
    print(f"✅ Tick natijalari: {tick_results}")

    # 4. Generate & Display Owner Report
    print("\n[4] KUNLIK YAKUNIY HISOBOT (OWNER REPORT):")
    print("-" * 70)
    async with session_factory() as session:
        rs = ReportService(session)
        summary = await rs.generate_report(period_type="today", offset=0)

        print(f"Sana:                  {summary.period_title}")
        print(f"Jami tushum:           {format_money(summary.total_revenue)}")
        print(f"Bajarilgan xizmatlar:  {summary.total_services} ta")
        print("-" * 70)
        print("To'lov turlari bo'yicha:")
        print(f"  • Click:             {format_money(summary.click_sum)}")
        print(f"  • Payme:             {format_money(summary.payme_sum)}")
        print(f"  • Paynet:            {format_money(summary.paynet_sum)}")
        print(f"  • Naqd:              {format_money(summary.cash_sum)}")
        print("-" * 70)
        print("Barberlar reytingi (tushum bo'yicha):")
        for idx, r in enumerate(summary.rankings, 1):
            top_mark = "👑 TOP " if r.is_top else "     "
            print(f"  {top_mark}{idx}. {r.display_name:<25}: {format_money(r.revenue):<12} ({r.services_count} ta xizmat)")
        print("-" * 70)

        # Print CSV snippet
        csv_text = await rs.generate_csv(period_type="today", offset=0)
        print("\nCSV eksport namunasi:")
        for line in csv_text.strip().split("\n")[:5]:
            print(f"  {line}")
    finally:
        await engine.dispose()
        if temp_db_path and os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
