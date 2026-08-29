"""Seed the merchant catalog.

    python -m scripts.seed_catalog          # insert or update
    python -m scripts.seed_catalog --reset  # delete all products first

The price points are chosen deliberately so the Milestone 4 demo can hit every
guardrail band with real products, using the default caps in `.env.example`:

    band A   <= ₹500      auto-approves, no human in the loop
    band B   ₹500-₹2,000  crosses the approval gate, agent must pause and ask
    band C   >  ₹2,000    exceeds the per-transaction cap, refused outright

One item is intentionally out of stock so `in_stock_only` has something to filter.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from sqlalchemy import delete, select

from app.db.models import Product
from app.db.session import SessionLocal, engine
from app.services.money import format_money

# band A — under the ₹500 auto-approve limit
# band B — between the auto-approve limit and the ₹2,000 per-transaction cap
# band C — above the per-transaction cap
CATALOG: list[dict[str, Any]] = [
    {
        "id": "prd-usbc-cable-2m",
        "name": "Braided USB-C Cable (2m, 100W)",
        "description": (
            "Two-metre braided USB-C to USB-C cable rated for 100W power delivery "
            "and 480Mbps transfer. Nylon jacket, aluminium housing."
        ),
        "category": "accessories",
        "price_minor": 34_900,
        "stock": 240,
        "attributes": {"brand": "Volt", "length_m": 2, "wattage": 100, "warranty_months": 12},
    },
    {
        "id": "prd-steel-bottle-750",
        "name": "Insulated Steel Bottle (750ml)",
        "description": (
            "Double-walled vacuum-insulated stainless steel bottle. Keeps drinks "
            "cold 24 hours, hot 12. Leak-proof lid."
        ),
        "category": "home",
        "price_minor": 44_900,
        "stock": 88,
        "attributes": {"brand": "Terra", "capacity_ml": 750, "material": "18/8 steel"},
    },
    {
        "id": "prd-laptop-sleeve-14",
        "name": "Felt Laptop Sleeve (14 inch)",
        "description": (
            "Merino-wool felt sleeve for 14-inch laptops, with a magnetic closure "
            "and a front pocket for a charger."
        ),
        "category": "accessories",
        "price_minor": 49_900,
        "stock": 61,
        "attributes": {"brand": "Terra", "fits_inches": 14, "colour": "charcoal"},
    },
    {
        "id": "prd-daypack-22l",
        "name": "Water-Resistant Daypack (22L)",
        "description": (
            "Twenty-two litre commuter backpack with a padded laptop compartment, "
            "water-resistant shell, and a luggage pass-through."
        ),
        "category": "accessories",
        "price_minor": 89_900,
        "stock": 34,
        "attributes": {"brand": "Terra", "capacity_l": 22, "warranty_months": 24},
    },
    {
        "id": "prd-wireless-mouse",
        "name": "Silent Wireless Mouse",
        "description": (
            "Silent wireless mouse with a 4000 DPI optical sensor, USB-C "
            "recharging, and multi-device pairing across three machines."
        ),
        "category": "peripherals",
        "price_minor": 129_900,
        "stock": 52,
        "attributes": {"brand": "Volt", "dpi": 4000, "connectivity": "bluetooth", "warranty_months": 24},
    },
    {
        "id": "prd-bt-speaker",
        "name": "Portable Bluetooth Speaker",
        "description": (
            "Compact IPX7 waterproof Bluetooth speaker with 20 hours of playback "
            "and stereo pairing."
        ),
        "category": "audio",
        "price_minor": 179_900,
        "stock": 27,
        "attributes": {"brand": "Sonora", "battery_hours": 20, "waterproof": "IPX7"},
    },
    {
        "id": "prd-anc-headphones",
        "name": "Wireless Noise Cancelling Headphones",
        "description": (
            "Over-ear wireless headphones with hybrid active noise cancellation, "
            "40 hours of battery, and multipoint Bluetooth."
        ),
        "category": "audio",
        "price_minor": 249_900,
        "stock": 18,
        "attributes": {"brand": "Sonora", "battery_hours": 40, "anc": True, "warranty_months": 24},
    },
    {
        "id": "prd-smartwatch-amoled",
        "name": "AMOLED Fitness Smartwatch",
        "description": (
            "1.4-inch AMOLED smartwatch with built-in GPS, SpO2 and heart-rate "
            "tracking, and a seven-day battery."
        ),
        "category": "wearables",
        "price_minor": 499_900,
        "stock": 12,
        "attributes": {"brand": "Volt", "display": "AMOLED", "gps": True, "battery_days": 7},
    },
    {
        "id": "prd-espresso-machine",
        "name": "Semi-Automatic Espresso Machine",
        "description": (
            "Fifteen-bar semi-automatic espresso machine with a steam wand and a "
            "stainless steel portafilter. Currently out of stock."
        ),
        "category": "home",
        "price_minor": 899_900,
        "stock": 0,
        "attributes": {"brand": "Terra", "pressure_bar": 15, "warranty_months": 24},
    },
]


async def seed(*, reset: bool) -> None:
    """Insert or update every catalog entry."""
    # This is an operator-facing script: the SQL echo that `DEBUG=true` turns on
    # would bury the summary it prints. Assigning `echo` reconfigures SQLAlchemy's
    # own logger, which setting a level on the parent logger would not.
    engine.echo = False

    async with SessionLocal() as session:
        if reset:
            await session.execute(delete(Product))
            print("reset: removed all existing products")

        created = updated = 0
        for row in CATALOG:
            existing = await session.get(Product, row["id"])
            if existing is None:
                session.add(Product(**row))
                created += 1
            else:
                for key, value in row.items():
                    setattr(existing, key, value)
                updated += 1

        await session.commit()

        total = len((await session.execute(select(Product))).scalars().all())

    print(f"seeded: {created} created, {updated} updated, {total} products total\n")
    for row in sorted(CATALOG, key=lambda r: int(r["price_minor"])):
        stock = row["stock"]
        flag = "" if stock else "   (out of stock)"
        print(f"  {row['id']:<28} {format_money(int(row['price_minor'])):>12}{flag}")

    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the AutoBuy merchant catalog.")
    parser.add_argument(
        "--reset", action="store_true", help="delete all existing products first"
    )
    args = parser.parse_args()

    try:
        asyncio.run(seed(reset=args.reset))
    except Exception as exc:  # pragma: no cover — operator-facing script
        print(f"\nseed failed: {exc}", file=sys.stderr)
        print("Did you run `alembic upgrade head` first?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
