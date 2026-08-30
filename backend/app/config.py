"""Central application configuration.

Every value is sourced from the environment (or a local `.env`). Secrets are
never hardcoded — see `.env.example` for the full list of required variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_name: str = "AutoBuy"
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Comma-separated list of allowed browser origins for CORS.
    cors_origins: str = "http://localhost:3000"

    # ---- Database ----
    # Defaults to file-backed SQLite so the app boots with zero local infra.
    # Render (and any Postgres deployment) overrides this with a postgres URL.
    database_url: str = "sqlite+aiosqlite:///./autobuy.db"

    # ---- Redis (idempotency + rate limiting) ----
    # Optional locally: when unset the app falls back to an in-process store.
    redis_url: str | None = None

    # ---- Razorpay (TEST MODE ONLY) ----
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_currency: str = "INR"

    # ---- Anthropic (agent reasoning) ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_max_tokens: int = 4096
    # Effort trades thinking depth against latency and cost. "medium" keeps a
    # chat turn responsive; the spend caps are enforced server-side regardless,
    # so model effort is never the thing keeping a purchase safe.
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # "model"    — Claude drives the conversation (needs a funded ANTHROPIC_API_KEY)
    # "scripted"  — a deterministic keyword planner drives it, with no model call.
    #
    # Scripted mode exists so the project is demonstrable without API credit. It
    # changes ONLY the conversational surface: guardrails, the approval gate, the
    # audit trail, retry, idempotency, and the live Razorpay calls are untouched.
    # The UI badges every scripted turn — it must never be mistaken for the model.
    agent_mode: Literal["model", "scripted"] = "model"

    # Upper bound on tool-calling rounds within a single chat turn. A model that
    # keeps calling tools without concluding must terminate, not spin.
    agent_max_iterations: int = 8

    # ---- Retry ----
    # A retryable provider failure is retried once. Deliberately once: a payment
    # gateway that is failing does not usually recover in milliseconds, and every
    # extra attempt widens the window in which a charge could land twice.
    provider_max_attempts: int = 2
    provider_retry_base_delay: float = 0.5

    # ---- Guardrails (wired up fully in Milestone 4) ----
    # Amounts are in the currency's minor unit (paise for INR).
    auto_approve_limit_minor: int = Field(default=50_000)      # ₹500.00
    per_transaction_cap_minor: int = Field(default=2_000_00)   # ₹2,000.00
    daily_cap_minor: int = Field(default=10_000_00)            # ₹10,000.00

    @field_validator("database_url")
    @classmethod
    def _normalise_async_driver(cls, v: str) -> str:
        """Rewrite a sync Postgres URL to the asyncpg driver.

        Managed platforms hand out `postgres://` or `postgresql://` URLs, but the
        async engine needs `postgresql+asyncpg://`. Without this the app boots
        locally on SQLite and dies on first deploy with an opaque
        `InvalidRequestError: The asyncio extension requires an async driver`.
        """
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("razorpay_key_id")
    @classmethod
    def _must_be_test_key(cls, v: str) -> str:
        """Hard guarantee: this project never talks to a live Razorpay account."""
        if v and not v.startswith("rzp_test_"):
            raise ValueError(
                "Refusing to start: RAZORPAY_KEY_ID must be a TEST-mode key "
                "(expected prefix 'rzp_test_'). This project is test-mode only."
            )
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
