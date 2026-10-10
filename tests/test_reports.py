from __future__ import annotations

import pytest

from app.models.enums import PaymentMethod
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.services.report_service import ReportService


@pytest.mark.asyncio
async def test_revenue_rule_and_reports(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    ps = PaymentService(db_session, notifier=mock_notifier)
    rs = ReportService(db_session)

    svc = sample_barber.services[0]  # 50,000 UZS

    # Case 1: COMPLETED + PAID -> counts as revenue!
    o1 = await qs.join_queue(sample_barber.id, svc.id, sample_clients[0])
    await qs.client_arrived(o1.id)
    await qs.complete_service(o1.id)
    await ps.confirm_cash_payment(o1.id, sample_barber.user_id)

    # Case 2: COMPLETED but UNPAID -> NOT revenue!
    o2 = await qs.join_queue(sample_barber.id, svc.id, sample_clients[1])
    await qs.client_arrived(o2.id)
    await qs.complete_service(o2.id)

    # Case 3: PAID but CANCELLED (never completed) -> NOT revenue!
    o3 = await qs.join_queue(sample_barber.id, svc.id, sample_clients[2], pay_now=True)
    await ps.handle_successful_payment(PaymentMethod.CLICK.value, "tx_o3", o3.price, o3.id)
    await qs.cancel_by_client(o3.id, sample_clients[2].id)

    # Case 4: COMPLETED + PAID via Payme
    o4 = await qs.join_queue(sample_barber.id, svc.id, sample_clients[3])
    await qs.client_arrived(o4.id)
    await qs.complete_service(o4.id)
    await ps.handle_successful_payment(PaymentMethod.PAYME.value, "tx_o4", o4.price, o4.id)

    await db_session.commit()

    # Generate today's report
    report = await rs.generate_report(period_type="today", offset=0)

    # Total revenue should be exactly 50,000 (Case 1) + 50,000 (Case 4) = 100,000
    assert report.total_revenue == 100000
    assert report.total_services == 2
    assert report.cash_sum == 50000
    assert report.payme_sum == 50000
    assert report.click_sum == 0
    assert report.paynet_sum == 0

    # Barber rankings
    assert len(report.rankings) >= 1
    top_barber = report.rankings[0]
    assert top_barber.barber_id == sample_barber.id
    assert top_barber.revenue == 100000
    assert top_barber.is_top is True

    # Test CSV export
    csv_text = await rs.generate_csv(period_type="today", offset=0)
    assert "Sana" in csv_text
    assert "100000" not in csv_text  # Each row is 50000
    assert "50000" in csv_text
    assert sample_barber.display_name in csv_text
