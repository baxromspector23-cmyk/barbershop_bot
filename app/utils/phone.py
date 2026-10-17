"""app/utils/phone.py
Phone number validation and normalization utilities for Uzbek numbers.
"""
from __future__ import annotations

import re


def normalize_uz_phone(raw: str | None) -> str | None:
    """Normalize Uzbek phone numbers to +998XXXXXXXXX format.

    Accepts:
      - +998XXXXXXXXX
      - 998XXXXXXXXX
      - XXXXXXXXX (9 digits)

    Strips spaces, dashes, parentheses and brackets.
    Returns normalized '+998XXXXXXXXX' string or None if invalid.
    """
    if not raw:
        return None

    cleaned = re.sub(r"[\s\-\(\)\[\]\.]+", "", raw.strip())
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not digits.isdigit():
            return None
        if len(digits) == 12 and digits.startswith("998"):
            return f"+{digits}"
        return None

    if not cleaned.isdigit():
        return None

    if len(cleaned) == 12 and cleaned.startswith("998"):
        return f"+{cleaned}"
    elif len(cleaned) == 9:
        return f"+998{cleaned}"

    return None
