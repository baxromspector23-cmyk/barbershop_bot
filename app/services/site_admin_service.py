from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import string
import urllib.request
from pathlib import Path

from app.config import settings
from app.site.app import set_current_site_password_hash
from app.site.security import hash_password

logger = logging.getLogger(__name__)

_CRED_FILE = Path(__file__).resolve().parent.parent.parent / ".env_site_cred"
_DEFAULT_PASSWORD = "@barber_baza"


def get_current_password_display() -> str:
    """Return the last known plain password for owner convenience, defaulting to @barber_baza."""
    if _CRED_FILE.is_file():
        try:
            val = _CRED_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception as exc:
            logger.debug("Failed to read .env_site_cred: %s", exc)
    return _DEFAULT_PASSWORD


def set_current_password_display(val: str) -> None:
    """Persist the last known plain password."""
    try:
        _CRED_FILE.write_text(val.strip(), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to save .env_site_cred: %s", exc)


def generate_secure_password(prefix: str = "Barber98_") -> str:
    """Generate a clean, strong password (15 chars, alphanumeric + symbol)."""
    chars = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"{prefix}{suffix}"


def update_local_env_file(key: str, value: str) -> bool:
    """Update a key in the local .env file if it exists."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.is_file():
        return False
    try:
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        found = False
        new_lines: list[str] = []
        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith(f"{key}=") or trimmed.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Failed to update local .env file: %s", exc)
        return False


def _sync_render_env_var_sync(key: str, value: str) -> bool:
    api_key = settings.RENDER_API_KEY or os.environ.get("RENDER_API_KEY", "rnd_MDHgH6r3y5cfveR9PsrAp11pBUHQ")
    service_id = settings.RENDER_SERVICE_ID or os.environ.get("RENDER_SERVICE_ID", "srv-db9j706q1p3s738f2lo0")
    if not api_key or not service_id:
        logger.warning("Render API key or Service ID missing; skipping Render env var sync.")
        return False

    url = f"https://api.render.com/v1/services/{service_id}/env-vars/{key}"
    payload = json.dumps({"value": value}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            ok = resp.status == 200
            if ok:
                logger.info("Render env-var %s updated successfully.", key)
            return ok
    except Exception as exc:
        logger.warning("Render env-var sync failed for %s: %s", key, exc)
        return False


async def sync_render_env_var(key: str, value: str) -> bool:
    """Non-blocking async sync of environment variable to Render."""
    try:
        return await asyncio.to_thread(_sync_render_env_var_sync, key, value)
    except Exception as exc:
        logger.warning("async sync_render_env_var failed: %s", exc)
        return False


async def apply_new_site_password(new_password: str) -> tuple[bool, str]:
    """Validate, hash, and apply new site password across in-memory app, .env, and Render."""
    clean_pwd = (new_password or "").strip()
    if len(clean_pwd) < 8:
        return False, "Parol uzunligi kamida 8 ta belgidan iborat bo'lishi kerak!"

    try:
        new_hash = hash_password(clean_pwd)
    except Exception as exc:
        logger.exception("Failed to hash password: %s", exc)
        return False, f"Parolni shifrlashda xatolik: {exc}"

    # 1. Update in-memory settings
    settings.SITE_PASSWORD_HASH = new_hash

    # 2. Update active site web application
    set_current_site_password_hash(new_hash)

    # 3. Save plain display password for owner
    set_current_password_display(clean_pwd)

    # 4. Update local .env file
    update_local_env_file("SITE_PASSWORD_HASH", new_hash)

    # 5. Sync to Render in background
    try:
        asyncio.create_task(sync_render_env_var("SITE_PASSWORD_HASH", new_hash))
    except Exception as exc:
        logger.warning("Could not launch background Render sync task: %s", exc)

    return True, "OK"
