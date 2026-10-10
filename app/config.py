from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot & Security
    BOT_TOKEN: str = "123456:TEST_BOT_TOKEN"
    OWNER_TELEGRAM_IDS: list[int] = Field(default_factory=lambda: [123456789])

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
    ENABLED_PAYMENT_METHODS: list[str] = Field(
        default_factory=lambda: ["CASH", "CLICK", "PAYME"]
    )

    @field_validator("OWNER_TELEGRAM_IDS", mode="before")
    @classmethod
    def parse_owner_ids(cls, v):
        if isinstance(v, str):
            ids = []
            for item in v.split(","):
                clean = item.strip()
                if clean:
                    ids.append(int(clean))
            return ids
        if isinstance(v, int):
            return [v]
        return v

    @field_validator("ENABLED_PAYMENT_METHODS", mode="before")
    @classmethod
    def parse_payment_methods(cls, v):
        if isinstance(v, str):
            return [m.strip().upper() for m in v.split(",") if m.strip()]
        return v

    def validate_runtime(self) -> None:
        """Validate critical production constraints."""
        if self.ENV == "production" and self.PAYMENTS_MODE == "test":
            raise ValueError(
                "CRITICAL SECURITY CHECK: PAYMENTS_MODE cannot be 'test' when ENV is 'production'!"
            )


settings = Settings()
