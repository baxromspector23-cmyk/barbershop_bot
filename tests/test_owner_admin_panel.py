from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.handlers.owner import (
    AdminSiteSG,
    get_admin_panel_content,
    handle_admin_command,
    handle_admin_generate_password,
    handle_admin_panel_close,
    handle_admin_panel_return,
    handle_admin_receive_new_password,
)
from app.models.enums import UserRole
from app.models.user import User
from app.services.site_admin_service import (
    apply_new_site_password,
    generate_secure_password,
    get_current_password_display,
    set_current_password_display,
)
from app.site.app import create_site_app, set_current_site_password_hash
from app.site.security import hash_password, verify_password


@pytest.mark.asyncio
async def test_admin_password_generation_and_hashing():
    pwd = generate_secure_password()
    assert len(pwd) >= 12
    assert pwd.startswith("Barber98_")

    # Test applying password
    ok, msg = await apply_new_site_password(pwd)
    assert ok is True
    assert msg == "OK"
    assert verify_password(pwd, settings.SITE_PASSWORD_HASH)
    assert get_current_password_display() == pwd


@pytest.mark.asyncio
async def test_admin_password_length_validation():
    ok, msg = await apply_new_site_password("short")
    assert ok is False
    assert "kamida 8 ta" in msg


@pytest.mark.asyncio
async def test_admin_command_access_denied_for_regular_user():
    user = User(id=10, telegram_id=99999999, role=UserRole.CLIENT.value, language="uz")
    msg = AsyncMock()
    msg.from_user = MagicMock(id=99999999)

    await handle_admin_command(msg, user=user, lang="uz")
    msg.answer.assert_called_once()
    assert "faqat katta barber" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_admin_command_access_granted_for_owner():
    user = User(id=1, telegram_id=settings.OWNER_TELEGRAM_IDS[0], role=UserRole.OWNER.value, language="uz")
    msg = AsyncMock()
    msg.from_user = MagicMock(id=settings.OWNER_TELEGRAM_IDS[0])

    await handle_admin_command(msg, user=user, lang="uz")
    msg.answer.assert_called_once()
    text = msg.answer.call_args[0][0]
    assert "KATTA BARBER — SAYT BOSHQARUV PANELI" in text
    assert settings.SITE_USERNAME in text
    assert "https://barbershop-bot-site.onrender.com/login" in text


@pytest.mark.asyncio
async def test_admin_generate_password_callback():
    user = User(id=1, telegram_id=settings.OWNER_TELEGRAM_IDS[0], role=UserRole.OWNER.value, language="uz")
    call = AsyncMock()
    call.from_user = MagicMock(id=settings.OWNER_TELEGRAM_IDS[0])

    await handle_admin_generate_password(call, user=user)
    call.answer.assert_called_once_with("Yangi parol o'rnatildi!", show_alert=True)
    call.message.edit_text.assert_called_once()
    reply_text = call.message.edit_text.call_args[0][0]
    assert "Yangi sayt paroli muvaffaqiyatli yaratildi va o'rnatildi!" in reply_text
    assert settings.SITE_USERNAME in reply_text


@pytest.mark.asyncio
async def test_admin_receive_new_password_deletes_message_for_security():
    user = User(id=1, telegram_id=settings.OWNER_TELEGRAM_IDS[0], role=UserRole.OWNER.value, language="uz")
    msg = AsyncMock()
    msg.from_user = MagicMock(id=settings.OWNER_TELEGRAM_IDS[0])
    msg.text = "MySecretPass2026!"
    state = AsyncMock()

    await handle_admin_receive_new_password(msg, state=state, user=user)
    # Ensure raw password message was immediately deleted
    msg.delete.assert_called_once()
    state.clear.assert_called_once()
    msg.answer.assert_called_once()
    assert "Yangi sayt paroli muvaffaqiyatli qabul qilindi" in msg.answer.call_args[0][0]
    assert verify_password("MySecretPass2026!", settings.SITE_PASSWORD_HASH)


@pytest.mark.asyncio
async def test_site_app_dynamic_password_update():
    session_factory = MagicMock()
    initial_pwd = "InitialPassword123!"
    initial_hash = hash_password(initial_pwd)
    app = create_site_app(
        session_factory,
        username="Jasur_barber",
        password_hash=initial_hash,
        secret="test_secret_32_characters_long_string!!",
        secure_cookies=False,
    )

    # Update password via site admin service
    new_pwd = "UpdatedPassword456!"
    ok, _ = await apply_new_site_password(new_pwd)
    assert ok is True

    # Check verify_password against updated app hash
    from app.site.app import _PASSWORD_HASH_KEY
    assert verify_password(new_pwd, app[_PASSWORD_HASH_KEY])
    assert not verify_password(initial_pwd, app[_PASSWORD_HASH_KEY])
