#!/usr/bin/env python3
"""
scripts/make_site_password_hash.py
Prompts for the owner website password twice (minimum 12 characters) using getpass,
and prints the two .env lines:
  SITE_PASSWORD_HASH=...
  SITE_SESSION_SECRET=...
Never prints or stores the plain password.
"""
from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.site.security import hash_password  # noqa: E402


def main() -> int:
    try:
        pwd1 = getpass.getpass("Yangi sayt paroli (kamida 12 ta belgi): ")
    except (EOFError, KeyboardInterrupt):
        print("\nBekor qilindi.", file=sys.stderr)
        return 1

    if len(pwd1) < 12:
        print("Xatolik: Parol kamida 12 ta belgidan iborat bo'lishi shart.", file=sys.stderr)
        return 1

    try:
        pwd2 = getpass.getpass("Parolni qayta kiriting: ")
    except (EOFError, KeyboardInterrupt):
        print("\nBekor qilindi.", file=sys.stderr)
        return 1

    if pwd1 != pwd2:
        print("Xatolik: Kiritilgan parollar mos kelmadi.", file=sys.stderr)
        return 1

    pwd_hash = hash_password(pwd1)
    session_secret = secrets.token_urlsafe(48)

    print(f"SITE_PASSWORD_HASH={pwd_hash}")
    print(f"SITE_SESSION_SECRET={session_secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
