from __future__ import annotations

import re
from pathlib import Path

import pytest
from aiogram.types import InlineKeyboardButton, KeyboardButton

from app.config import settings
from app.i18n import t


def test_helper_style_validation():
    from app.keyboards.common import btn

    # valid styles
    b1 = btn("Test", "cb1", style="primary")
    assert b1.style == "primary"
    b2 = btn("Test", "cb2", style="success")
    assert b2.style == "success"
    b3 = btn("Test", "cb3", style="danger")
    assert b3.style == "danger"
    b4 = btn("Test", "cb4", style=None)
    assert b4.style is None

    # invalid style
    with pytest.raises(ValueError):
        btn("Test", "cb5", style="warning")
    with pytest.raises(ValueError):
        btn("Test", "cb6", style="blue")


def test_helper_icon_lookup():
    from app.keyboards.common import btn

    with pytest.raises(KeyError):
        btn("Test", "cb", icon="nonexistent_icon")


def test_helper_premium_emoji_toggle(monkeypatch):
    from app.keyboards.common import btn

    # When USE_PREMIUM_EMOJI is True
    monkeypatch.setattr(settings, "USE_PREMIUM_EMOJI", True)
    b_on = btn("✅ Tasdiqlash", "cb_ok", icon="check")
    assert b_on.text == "Tasdiqlash"
    assert b_on.icon_custom_emoji_id == "5224400190244401421"

    # Does not strip if text does not start with legacy emoji
    b_no_leg = btn("Tasdiqlash", "cb_ok", icon="check")
    assert b_no_leg.text == "Tasdiqlash"
    assert b_no_leg.icon_custom_emoji_id == "5224400190244401421"

    # When USE_PREMIUM_EMOJI is False
    monkeypatch.setattr(settings, "USE_PREMIUM_EMOJI", False)
    b_off = btn("✅ Tasdiqlash", "cb_ok", icon="check")
    assert b_off.text == "✅ Tasdiqlash"
    assert b_off.icon_custom_emoji_id is None


def test_kbtn_helper(monkeypatch):
    from app.keyboards.common import kbtn

    monkeypatch.setattr(settings, "USE_PREMIUM_EMOJI", True)
    kb = kbtn("📋 Navbat", icon="queue")
    assert kb.text == "Navbat"
    assert kb.icon_custom_emoji_id == "5303166093701959050"

    monkeypatch.setattr(settings, "USE_PREMIUM_EMOJI", False)
    kb_off = kbtn("📋 Navbat", icon="queue")
    assert kb_off.text == "📋 Navbat"
    assert kb_off.icon_custom_emoji_id is None


def test_all_icon_names_exist_and_ids_are_digits():
    from app.keyboards.icons import BUTTON_ICONS

    expected_names = [
        "check", "cross", "forbidden", "card", "play", "pause",
        "refresh", "lang", "money", "queue", "plus", "history",
        "barbershop", "ticket", "back", "home", "green", "red",
        "edit", "download", "user", "stats", "users", "chart",
        "attach", "instagram"
    ]
    assert len(BUTTON_ICONS) >= len(expected_names)
    for name in expected_names:
        assert name in BUTTON_ICONS, f"Missing icon: {name}"
        icon_id = BUTTON_ICONS[name]
        assert isinstance(icon_id, str)
        assert icon_id.isdigit(), f"Icon id for {name} is not a digit string: {icon_id}"


def test_no_direct_button_instantiations_in_app():
    root = Path(__file__).resolve().parent.parent / "app"
    pattern = re.compile(r"\b(InlineKeyboardButton|KeyboardButton)\(")
    violations = []
    for p in root.rglob("*.py"):
        # only app/keyboards/common.py may instantiate them
        if p.name == "common.py" and p.parent.name == "keyboards":
            continue
        text = p.read_text(encoding="utf-8")
        for idx, line in enumerate(text.splitlines(), 1):
            # ignore comments
            clean = line.strip()
            if clean.startswith("#"):
                continue
            if pattern.search(clean):
                violations.append(f"{p.relative_to(root.parent)}:{idx}: {clean}")

    assert not violations, "Direct button instantiations found in app/:\n" + "\n".join(violations)


def test_no_scissors_starting_button_texts():
    import yaml

    from app.keyboards.common import replace_scissors

    root = Path(__file__).resolve().parent.parent / "app" / "i18n"
    for lang in ["uz", "uz_cyrl", "ru"]:
        data = yaml.safe_load((root / f"{lang}.yaml").read_text(encoding="utf-8"))
        for section in ["client", "barber", "owner", "common", "payments"]:
            if section in data and isinstance(data[section], dict):
                for k, v in data[section].items():
                    if isinstance(v, str) and ("btn" in k or "menu" in k):
                        replaced = replace_scissors(v)
                        assert not replaced.startswith("✂️"), (
                            f"Button {lang}.{section}.{k} still starts with ✂️: {replaced}"
                        )
                        assert not replaced.startswith("\u2702"), (
                            f"Button {lang}.{section}.{k} still starts with scissors unicode: {replaced}"
                        )


def test_real_keyboards_agreed_colored_buttons():
    from app.keyboards.barber import get_order_action_keyboard
    from app.keyboards.client import (
        get_client_inline_menu,
        get_order_paid_menu,
        get_pay_timing_keyboard,
        get_pending_receipt_keyboard,
    )
    from app.services.manual_payment_service import build_receipt_review_keyboard

    # 1. client.menu_join (c_menu:join) -> success
    c_menu = get_client_inline_menu(lang="uz")
    join_menu_btns = [b for row in c_menu.inline_keyboard for b in row if b.callback_data == "c_menu:join"]
    assert len(join_menu_btns) == 1
    assert join_menu_btns[0].style == "success"

    # 2. client.btn_join (pay_timing:after) -> success
    kb = get_pay_timing_keyboard(1, 1, lang="uz")
    join_btns = [b for row in kb.inline_keyboard for b in row if b.callback_data == "pay_timing:after:1:1"]
    assert len(join_btns) == 1
    assert join_btns[0].style == "success"

    # 3. barber.btn_done -> success
    # 4. barber.btn_no_show -> danger
    class DummyOrder:
        id = 999
        status = "IN_PROGRESS"
    order_kb = get_order_action_keyboard(DummyOrder(), lang="uz")
    done_btns = [b for row in order_kb.inline_keyboard for b in row if b.callback_data == "b_done:999"]
    assert len(done_btns) == 1
    assert done_btns[0].style == "success"

    noshow_order = DummyOrder()
    noshow_order.status = "CALLED"
    noshow_kb = get_order_action_keyboard(noshow_order, lang="uz")
    noshow_btns = [b for row in noshow_kb.inline_keyboard for b in row if b.callback_data == "b_no_show:999"]
    assert len(noshow_btns) == 1
    assert noshow_btns[0].style == "danger"

    # 5. payments.btn_transfer_ok -> success
    # 6. payments.btn_transfer_no -> danger
    review_kb = build_receipt_review_keyboard(42, lang="uz")
    ok_btns = [b for row in review_kb.inline_keyboard for b in row if b.callback_data == "tr_ok:42"]
    no_btns = [b for row in review_kb.inline_keyboard for b in row if b.callback_data == "tr_no:42"]
    assert len(ok_btns) == 1
    assert ok_btns[0].style == "success"
    assert len(no_btns) == 1
    assert no_btns[0].style == "danger"

    # 7. client.cancel_queue_btn -> danger
    # 8. client.btn_pay -> primary
    my_q_menu = get_order_paid_menu(999, lang="uz")
    cancel_btns = [b for row in my_q_menu.inline_keyboard for b in row if b.callback_data == "cancel_queue_prompt:999"]
    assert len(cancel_btns) == 1
    assert cancel_btns[0].style == "danger"

    pay_btns = [b for row in my_q_menu.inline_keyboard for b in row if b.callback_data == "pay_open:999"]
    assert len(pay_btns) == 1
    assert pay_btns[0].style == "primary"

    # 9. payments.btn_send_receipt -> primary
    rec_kb = get_pending_receipt_keyboard(100, lang="uz")
    send_btns = [b for row in rec_kb.inline_keyboard for b in row if b.callback_data == "tr_send:100"]
    assert len(send_btns) == 1
    assert send_btns[0].style == "primary"


def test_instagram_button(monkeypatch):
    from app.keyboards.client import get_client_inline_menu

    monkeypatch.setattr(settings, "INSTAGRAM_URL", "https://www.instagram.com/jasur_barber_98")
    kb = get_client_inline_menu(lang="uz")
    insta_btns = [b for row in kb.inline_keyboard for b in row if b.url == "https://www.instagram.com/jasur_barber_98"]
    assert len(insta_btns) == 1
    assert insta_btns[0].text == "Bizning Instagram sahifamiz"

    # empty url -> absent
    monkeypatch.setattr(settings, "INSTAGRAM_URL", "")
    kb_empty = get_client_inline_menu(lang="uz")
    insta_empty = [b for row in kb_empty.inline_keyboard for b in row if b.url]
    assert len(insta_empty) == 0


def test_reply_menu_labels_match_handler_filters(monkeypatch):
    from app.keyboards.barber import get_barber_main_keyboard
    from app.keyboards.client import get_client_main_keyboard
    from app.keyboards.common import menu_label
    from app.keyboards.owner import get_owner_main_keyboard

    for use_prem in [True, False]:
        monkeypatch.setattr(settings, "USE_PREMIUM_EMOJI", use_prem)
        for lang in ["uz", "uz_cyrl", "ru"]:
            client_kb = get_client_main_keyboard(lang)
            client_texts = [b.text for row in client_kb.keyboard for b in row]
            for key in ["client.menu_join", "client.menu_my_queue", "client.menu_history", "client.menu_lang"]:
                expected = menu_label(key, lang)
                assert expected in client_texts, f"Client {key} ({expected}) not in reply keyboard for {lang}"

            barber_kb = get_barber_main_keyboard(lang)
            barber_texts = [b.text for row in barber_kb.keyboard for b in row]
            for key in ["barber.menu_queue", "barber.menu_payments", "barber.menu_walkin", "barber.menu_toggle_status", "barber.menu_lang"]:
                expected = menu_label(key, lang)
                assert expected in barber_texts, f"Barber {key} ({expected}) not in reply keyboard for {lang}"

            owner_kb = get_owner_main_keyboard(lang)
            owner_texts = [b.text for row in owner_kb.keyboard for b in row]
            for key in ["owner.menu_all_queues", "owner.menu_reports", "owner.menu_barbers", "owner.menu_refunds", "owner.menu_block"]:
                expected = menu_label(key, lang)
                assert expected in owner_texts, f"Owner {key} ({expected}) not in reply keyboard for {lang}"

