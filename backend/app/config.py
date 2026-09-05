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

    # Force the PgBouncer-safe connection settings even when the host does not
    # advertise itself with "-pooler". Supabase's pooler, for instance, does not.
    pgbouncer_mode: bool = False

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

    # Intent classification is a 5-way label, not a purchasing decision — it
    # never gates money (guardrails.py does that), it only feeds the audit
    # trail and the UI's intent badge. Opus 5 is the wrong tool for it: a
    # cheap, fast model with no extended thinking gets the same label for a
    # fraction of the cost. Kept separately configurable so it can be pointed
    # at whatever the cheapest capable model is without touching the model the
    # buyer actually talks to.
    anthropic_intent_model: str = "claude-haiku-4-5"

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

    # ---- Consent lifecycle ----
    # Require an explicit, unexpired grant before the agent may spend at all.
    # On by default: purchasing authority a buyer never gave is not something
    # anyone should have to opt out of.
    require_agent_grant: bool = True
    default_grant_cap_minor: int = 500_000        # ₹5,000.00
    default_grant_hours: int = 24

    # ---- Guardrails (wired up fully in Milestone 4) ----
    # Amounts are in the currency's minor unit (paise for INR).
    auto_approve_limit_minor: int = Field(default=50_000)      # ₹500.00
    per_transaction_cap_minor: int = Field(default=2_000_00)   # ₹2,000.00
    daily_cap_minor: int = Field(default=10_000_00)            # ₹10,000.00

    @field_validator("database_url")
    @classmethod
    def _normalise_async_driver(cls, v: str) -> str:
        """Make any managed Postgres URL usable by asyncpg.

        Two independent problems, both of which only surface on deploy:

        1. **Driver.** Platforms hand out `postgres://` or `postgresql://`, but
           the async engine needs `postgresql+asyncpg://`. Otherwise the app
           boots locally on SQLite and dies in production with
           `InvalidRequestError: The asyncio extension requires an async driver`.

        2. **libpq-only query parameters.** Neon, Supabase and friends append
           `?sslmode=require&channel_binding=require`. Those are libpq options;
           asyncpg has never accepted them and fails with
           `TypeError: connect() got an unexpected keyword argument 'sslmode'`.
           asyncpg spells it `ssl`, taking the same values, so `sslmode` is
           translated and `channel_binding` dropped.
        """
        if not v.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
            return v

        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(v)
        scheme = "postgresql+asyncpg"

        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        # asyncpg's equivalent of libpq's sslmode, same accepted values.
        if "sslmode" in params:
            params.setdefault("ssl", params.pop("sslmode"))
        else:
            params.pop("sslmode", None)
        # Negotiated by asyncpg itself; passing it through is a TypeError.
        params.pop("channel_binding", None)

        return urlunsplit(
            (scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
        )

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
