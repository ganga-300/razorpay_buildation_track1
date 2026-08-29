"""Agent-readable catalog schema.

This is the contract an external AI agent consumes to make this merchant
transactable. Three design rules drive its shape:

1. **Self-describing.** Every payload carries `schema_version` and `spec` so an
   agent can detect a contract change instead of silently mis-parsing.
2. **Money is never ambiguous.** Prices are integer minor units plus an explicit
   currency; the human `display` string is decoration, never a parse target.
3. **Bounds are discoverable, not just enforced.** The `purchase_policy` block
   tells an agent the spend caps and the approval threshold up front, so a
   well-behaved agent can self-limit before it ever attempts a purchase — and a
   badly-behaved one still gets blocked server-side.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.models import Product
from app.services.money import format_money

CATALOG_SCHEMA_VERSION = "1.0"
CATALOG_SPEC = "autobuy.catalog/v1"


class Money(BaseModel):
    """An amount, unambiguously."""

    amount_minor: int = Field(description="Integer amount in the currency's minor unit (paise for INR)")
    currency: str = Field(description="ISO 4217 code")
    display: str = Field(description="Human-readable rendering. Never parse this — use amount_minor.")

    @classmethod
    def of(cls, amount_minor: int, currency: str) -> "Money":
        return cls(
            amount_minor=amount_minor,
            currency=currency,
            display=format_money(amount_minor, currency),
        )


class Availability(BaseModel):
    """Stock position for a product."""

    in_stock: bool
    quantity: int = Field(description="Units currently available")


class AgentProduct(BaseModel):
    """A single catalog item in agent-consumable form."""

    id: str
    name: str
    description: str
    category: str
    price: Money
    availability: Availability
    attributes: dict[str, Any] = Field(default_factory=dict)
    self_link: str = Field(description="Relative URL for this product's detail record")

    @classmethod
    def from_orm_product(cls, p: Product, *, prefix: str) -> "AgentProduct":
        return cls(
            id=p.id,
            name=p.name,
            description=p.description,
            category=p.category,
            price=Money.of(p.price_minor, p.currency),
            availability=Availability(in_stock=p.in_stock, quantity=p.stock),
            attributes=p.attributes or {},
            self_link=f"{prefix}/catalog/{p.id}",
        )


class PurchasePolicy(BaseModel):
    """The spend bounds this merchant enforces on agent-initiated purchases.

    Published so an agent can reason about affordability *before* attempting a
    purchase. These values are advisory to the agent and mandatory server-side —
    `services/guardrails.py` re-checks all of them.
    """

    currency: str
    auto_approve_limit: Money = Field(description="At or below this, an order executes without human approval")
    per_transaction_cap: Money = Field(description="Hard ceiling for any single order; above this is refused outright")
    daily_cap: Money = Field(description="Rolling 24-hour cumulative ceiling across all agent spend")
    approval_required_above: Money = Field(description="Orders above this need explicit human approval in the chat")
    enforcement: Literal["server-side"] = "server-side"


class MerchantInfo(BaseModel):
    """Who the agent is transacting with."""

    name: str
    currency: str
    payment_provider: Literal["razorpay"] = "razorpay"
    payment_mode: Literal["test", "live"] = Field(description="This deployment is test-only")


class CatalogCapabilities(BaseModel):
    """What an agent is allowed to do against this catalog."""

    search: bool = True
    filter_by_category: bool = True
    filter_by_price: bool = True
    purchase: bool = True
    supported_filters: list[str] = Field(
        default_factory=lambda: ["q", "category", "max_price_minor", "min_price_minor", "in_stock_only"]
    )
    purchase_policy: PurchasePolicy


class CatalogQuery(BaseModel):
    """Echo of the filters that produced this result set."""

    q: str | None = None
    category: str | None = None
    min_price_minor: int | None = None
    max_price_minor: int | None = None
    in_stock_only: bool = False
    limit: int = 50


class CatalogResponse(BaseModel):
    """`GET /catalog` — the machine-readable catalog document."""

    schema_version: str = CATALOG_SCHEMA_VERSION
    spec: str = CATALOG_SPEC
    generated_at: datetime
    merchant: MerchantInfo
    capabilities: CatalogCapabilities
    query: CatalogQuery
    count: int = Field(description="Number of products in this response")
    total_matching: int = Field(description="Total matches before the limit was applied")
    categories: list[str] = Field(description="All categories present in the catalog")
    products: list[AgentProduct]


class ProductResponse(BaseModel):
    """`GET /catalog/{id}` — a single product, same envelope conventions."""

    schema_version: str = CATALOG_SCHEMA_VERSION
    spec: str = CATALOG_SPEC
    generated_at: datetime
    merchant: MerchantInfo
    product: AgentProduct
