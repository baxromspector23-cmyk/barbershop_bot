from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Contact, Message

from app.handlers.common import ClientRegistrationSG, handle_client_registration_phone, handle_start
from app.handlers.owner import handle_owner_info_menu
from app.models.enums import Language, UserRole
from app.models.order import Order
from app.models.user import User


@pytest.mark.asyncio
async def test_client_registration_and_subsequent_start(session_factory):
    async with session_factory() as session:
        user = User(
            telegram_id=987654321,
            username="new_client",
            first_name="Jasur",
            last_name="Test",
            language=Language.UZ.value,
            role=UserRole.CLIENT.value,
            phone=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        state = MagicMock()
        state.set_state = AsyncMock()
        state.clear = AsyncMock()

        cmd = MagicMock()
        cmd.args = ""

        # 1. First /start without phone: prompts for phone registration
        msg1 = MagicMock(spec=Message)
        msg1.answer = AsyncMock()
        await handle_start(msg1, cmd, session, user, "uz", state)

        state.set_state.assert_awaited_with(ClientRegistrationSG.waiting_for_phone)
        assert msg1.answer.call_count == 1
        prompt_call = msg1.answer.call_args[0][0]
        assert "telefon raqam" in prompt_call.lower()

        # 2. User sends contact
        msg_contact = MagicMock(spec=Message)
        msg_contact.contact = Contact(phone_number="+998901234567", first_name="Jasur")
        msg_contact.text = None
        msg_contact.answer = AsyncMock()

        await handle_client_registration_phone(msg_contact, session, user, state, "uz")
        state.clear.assert_awaited()
        assert user.phone == "+998901234567"

        # 3. Subsequent /start with saved profile
        msg2 = MagicMock(spec=Message)
        msg2.answer = AsyncMock()
        await handle_start(msg2, cmd, session, user, "uz", state)

        assert msg2.answer.call_count == 2
        welcome_call = msg2.answer.call_args_list[0][0][0]
        assert "+998901234567" in welcome_call
        assert "ro'yxatdan o'tgansiz" in welcome_call.lower()


@pytest.mark.asyncio
async def test_order_display_name_phone_visibility():
    client = User(
        telegram_id=111,
        username="bot_client",
        first_name="Ali",
        last_name="Valiyev",
        phone="+998907778899",
        role=UserRole.CLIENT.value,
    )
    order = Order(
        ticket_no=1,
        service_name="Soch",
        price=50000,
        status="WAITING",
        client=client,
    )

    owner_user = User(telegram_id=999, first_name="Katta", role=UserRole.OWNER.value)
    barber_user = User(telegram_id=888, first_name="Oddiy", role=UserRole.BARBER.value)
    client_viewer = User(telegram_id=777, first_name="Mijoz", role=UserRole.CLIENT.value)

    # Phone is visible ONLY to owner (katta barber)
    owner_view = order.display_name_for(owner_user)
    assert "+998907778899" in owner_view
    assert "@bot_client" in owner_view

    # Ordinary barber sees only nick
    barber_view = order.display_name_for(barber_user)
    assert "+998907778899" not in barber_view
    assert barber_view == "@bot_client"

    # Client viewer sees only nick
    client_view = order.display_name_for(client_viewer)
    assert "+998907778899" not in client_view
    assert client_view == "@bot_client"

    # Anonymous viewer sees only nick
    anon_view = order.display_name_for(None)
    assert "+998907778899" not in anon_view
    assert anon_view == "@bot_client"


@pytest.mark.asyncio
async def test_owner_info_menu(session_factory):
    async with session_factory() as session:
        owner = User(telegram_id=1, first_name="Owner", role=UserRole.OWNER.value)
        barber = User(telegram_id=2, first_name="Barber", role=UserRole.BARBER.value)

        # Owner gets info
        cb_owner = MagicMock()
        cb_owner.message = MagicMock()
        cb_owner.message.answer = AsyncMock()
        cb_owner.message.edit_text = AsyncMock()
        cb_owner.answer = AsyncMock()

        await handle_owner_info_menu(cb_owner, session, owner, "uz")
        assert cb_owner.answer.awaited

        # Non-owner is denied
        cb_barber = MagicMock()
        cb_barber.message = MagicMock()
        cb_barber.answer = AsyncMock()
        await handle_owner_info_menu(cb_barber, session, barber, "uz")
        assert not cb_barber.message.answer.called
