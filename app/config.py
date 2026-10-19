from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def get_env_example_data() -> dict[str, str]:
    env_ex = Path(__file__).resolve().parent.parent / ".env.example"
    if not env_ex.is_file():
        return {}
    res = {}
    for line in env_ex.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, val = line.split("=", 1)
            res[k.strip()] = val.strip()
    return res


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot & Security
    BOT_TOKEN: str = "123456:TEST_BOT_TOKEN"
    OWNER_TELEGRAM_IDS: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [123456789])

    # Database & Cache
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/barbershop"
    DATABASE_DIRECT_URL: str | None = None
    REDIS_URL: str | None = None

    # Server & Webhook
    RUN_MODE: str = "polling"  # polling | webhook
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    WEBHOOK_BASE_URL: str | None = None
    WEBHOOK_SECRET: str = "webhook_secret_telegram_token"
    WEBHOOK_PATH_SECRET: str = "webhook_path_secret"

    # Cron / Scheduler
    CRON_SECRET: str = "cron_secret_key"
    INTERNAL_SCHEDULER: bool = True

    # Environment & Rules
    ENV: str = "development"  # development | production | test
    TIMEZONE: str = "Asia/Tashkent"
    LATE_MINUTES: int = 10
    MAX_LATE_MOVES: int = 2
    HEADS_UP_AHEAD: int = 1
    ALLOW_BARBER_EDIT_OWN_SERVICES: bool = True

    # Payments
    PAYMENTS_MODE: str = "test"  # test | live
    PAYME_PROVIDER_TOKEN: str | None = ""
    CLICK_PROVIDER_TOKEN: str | None = ""
    PAYNET_ENABLED: bool = False
    PAYNET_SERVICE_ID: str | None = ""
    PAYNET_SECRET_KEY: str | None = ""
    ENABLED_PAYMENT_METHODS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["CASH", "TRANSFER"]
    )

    # Manual card transfer (TRANSFER): the client pays to this card and sends a photo of the receipt
    PAYMENT_CARD_NUMBER: str = ""
    PAYMENT_CARD_HOLDER: str = ""

    # Queue capacity protection
    MAX_QUEUE_PER_BARBER: int = 12

    # Working hours enforcement (when False, barbers operate 24/7 without schedule restrictions)
    CHECK_WORKING_HOURS: bool = False

    # Flood control: max unconfirmed receipt reminders processed per scheduler tick
    RECEIPT_REMINDER_MAX_PER_TICK: int = 10

    # UI Customizations: premium emojis & social links
    USE_PREMIUM_EMOJI: bool = True
    INSTAGRAM_URL: str = "https://www.instagram.com/jasur_barber_98"

    # Owner-only client website (read-only)
    SITE_ENABLED: bool = False
    SITE_USERNAME: str = "owner"
    SITE_PASSWORD_HASH: str = ""
    SITE_SESSION_SECRET: str = ""
    SITE_SECURE_COOKIES: bool = True
    SITE_TRUST_PROXY: bool = False
    SITE_PORT: int = 8081
    SITE_BASE_URL: str = "https://barbershop-bot-site.onrender.com"
    RENDER_API_KEY: str | None = None
    RENDER_SERVICE_ID: str | None = None
    GEMINI_API_KEY: str | None = None
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"

    @field_validator("INSTAGRAM_URL")
    @classmethod
    def validate_instagram_url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.startswith("https://"):
            raise ValueError("INSTAGRAM_URL must start with https://")
        return v

    @field_validator("OWNER_TELEGRAM_IDS", mode="before")
    @classmethod
    def parse_owner_ids(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    return [int(x) for x in parsed]
                except Exception:
                    pass
            ids = []
            for item in v.split(","):
                clean = item.strip()
                if clean:
                    ids.append(int(clean))
            return ids
        if isinstance(v, int):
            return [v]
        if isinstance(v, (list, tuple, set)):
            return [int(x) for x in v]
        return v

    @field_validator("ENABLED_PAYMENT_METHODS", mode="before")
    @classmethod
    def parse_payment_methods(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    return [str(x).strip().upper() for x in parsed]
                except Exception:
                    pass
            methods = []
            for item in v.split(","):
                clean = item.strip().upper()
                if clean:
                    methods.append(clean)
            return methods
        if isinstance(v, (list, tuple, set)):
            return [str(x).strip().upper() for x in v]
        return v

    def validate_runtime(self) -> None:
        """Validate critical production and owner-site constraints."""
        from app.site.security import is_valid_hash_format

        violations: list[str] = []

        if self.SITE_ENABLED:
            if not (self.SITE_USERNAME or "").strip():
                violations.append("SITE_USERNAME: must not be empty when SITE_ENABLED is true")
            if not is_valid_hash_format(self.SITE_PASSWORD_HASH):
                violations.append(
                    "SITE_PASSWORD_HASH: must be a valid scrypt hash generated by scripts/make_site_password_hash.py"
                )
            if (
                not self.SITE_SESSION_SECRET
                or len(self.SITE_SESSION_SECRET) < 32
                or "CHANGE_ME" in self.SITE_SESSION_SECRET
            ):
                violations.append(
                    "SITE_SESSION_SECRET: must be at least 32 characters and not contain CHANGE_ME"
                )
            if self.ENV == "production" and not self.SITE_SECURE_COOKIES:
                violations.append(
                    "SITE_SECURE_COOKIES: cannot be false in production when SITE_ENABLED is true"
                )

        if self.ENV == "production":
            ex = get_env_example_data()
            example_oids = {123456789, 987654321}
            if ex.get("OWNER_TELEGRAM_IDS"):
                for x in ex["OWNER_TELEGRAM_IDS"].split(","):
                    if x.strip().isdigit():
                        example_oids.add(int(x.strip()))

            # 1. OWNER_TELEGRAM_IDS
            if not self.OWNER_TELEGRAM_IDS:
                violations.append("OWNER_TELEGRAM_IDS: empty list is forbidden in production")
            elif any(oid in example_oids for oid in self.OWNER_TELEGRAM_IDS):
                violations.append("OWNER_TELEGRAM_IDS: contains default example placeholder ID forbidden in production")

            # 2. Secret tokens length and example checks
            for sec_name, sec_val in [
                ("WEBHOOK_SECRET", self.WEBHOOK_SECRET),
                ("WEBHOOK_PATH_SECRET", self.WEBHOOK_PATH_SECRET),
                ("CRON_SECRET", self.CRON_SECRET),
            ]:
                if len(sec_val) < 32:
                    violations.append(f"{sec_name}: must be at least 32 characters in production")
                if "CHANGE_ME" in sec_val or (sec_name in ex and sec_val == ex[sec_name]):
                    violations.append(f"{sec_name}: cannot use public placeholder/example secret in production")

            # 3. DATABASE_URL
            if not self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                violations.append("DATABASE_URL: production requires PostgreSQL asyncpg (must start with postgresql+asyncpg://)")

            # 4. FAKE in ENABLED_PAYMENT_METHODS
            if "FAKE" in self.ENABLED_PAYMENT_METHODS:
                violations.append("ENABLED_PAYMENT_METHODS: FAKE payment method is forbidden in production")

            # 5. PAYNET_ENABLED
            if self.PAYNET_ENABLED:
                violations.append("PAYNET_ENABLED: Paynet is not integrated yet and cannot be enabled in production")

            # 6. PAYMENTS_MODE
            if self.PAYMENTS_MODE == "test":
                violations.append("PAYMENTS_MODE: cannot be 'test' when ENV is 'production'")

            # 7. BOT_TOKEN check
            if (
                not self.BOT_TOKEN
                or self.BOT_TOKEN == "123456:TEST_BOT_TOKEN"
                or "CHANGE_ME" in self.BOT_TOKEN
                or self.BOT_TOKEN == ex.get("BOT_TOKEN")
            ):
                violations.append("BOT_TOKEN: cannot use placeholder/example bot token in production")

            # 8. Live mode payment provider tokens
            if self.PAYMENTS_MODE == "live":
                if "CLICK" in self.ENABLED_PAYMENT_METHODS:
                    if not self.CLICK_PROVIDER_TOKEN or ":TEST:" in self.CLICK_PROVIDER_TOKEN:
                        violations.append("CLICK_PROVIDER_TOKEN: live mode requires a non-empty live provider token without :TEST:")
                if "PAYME" in self.ENABLED_PAYMENT_METHODS:
                    if not self.PAYME_PROVIDER_TOKEN or ":TEST:" in self.PAYME_PROVIDER_TOKEN:
                        violations.append("PAYME_PROVIDER_TOKEN: live mode requires a non-empty live provider token without :TEST:")

        if self.ENV == "production" and "TRANSFER" in self.ENABLED_PAYMENT_METHODS:
            digits = "".join(ch for ch in self.PAYMENT_CARD_NUMBER if ch.isdigit())
            if len(digits) != 16 or len(set(digits)) == 1:
                violations.append(
                    "PAYMENT_CARD_NUMBER: TRANSFER is enabled, a real 16-digit card number is required in production"
                )
            if not self.PAYMENT_CARD_HOLDER.strip() or "CHANGE_ME" in self.PAYMENT_CARD_HOLDER:
                violations.append("PAYMENT_CARD_HOLDER: TRANSFER is enabled, the card holder name is required in production")

        if violations:
            raise ValueError(
                "CRITICAL SECURITY CHECK - Production configuration violations:\n"
                + "\n".join(f"- {v}" for v in violations)
            )


settings = Settings()
