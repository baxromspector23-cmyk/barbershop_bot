"""tests/test_phone.py
Unit tests for phone normalization utility.
"""
from __future__ import annotations

import pytest

from app.utils.phone import normalize_uz_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+998901234567", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("901234567", "+998901234567"),
        ("+998 90 123-45-67", "+998901234567"),
        ("90 123 45 67", "+998901234567"),
        ("(90) 123-45-67", "+998901234567"),
        ("998 90 123-45-67", "+998901234567"),
        ("+998 (90) 123-45-67", "+998901234567"),
    ],
)
def test_valid_uzbek_phones_normalize(raw, expected):
    assert normalize_uz_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "1234567",
        "0000000",
        "+++1234567",
        "abc",
        "12345678901234567890",
        "+998 12",
        "901234",
        "+79991234567",
        "+14155552671",
        "99812",
    ],
)
def test_invalid_phones_return_none(raw):
    assert normalize_uz_phone(raw) is None
