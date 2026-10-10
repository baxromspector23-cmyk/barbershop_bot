from __future__ import annotations


def format_money(amount: int) -> str:
    """Format an integer amount in UZS with space as thousands separator, e.g. 50 000 so'm."""
    formatted = f"{amount:,}".replace(",", " ")
    return f"{formatted} so'm"


def format_nick(
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    telegram_id: int | None = None,
    walkin_name: str | None = None,
    walkin_phone: str | None = None,
) -> str:
    """Format client nickname as @username if present, else First Last, walk-in name, or ID."""
    if username:
        clean = username.lstrip("@")
        return f"@{clean}"
    if walkin_name:
        if walkin_phone:
            return f"{walkin_name} ({walkin_phone})"
        return walkin_name
    names = [n for n in (first_name, last_name) if n]
    if names:
        return " ".join(names)
    if telegram_id:
        return f"ID:{telegram_id}"
    return "Mijoz"
