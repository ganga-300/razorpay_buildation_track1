"""Money formatting helpers.

Every amount in this codebase is an integer count of the currency's **minor
unit** (paise for INR). These helpers exist only to render those integers for
humans and for agent-facing `display` fields — never to do arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

CURRENCY_SYMBOLS: dict[str, str] = {"INR": "₹", "USD": "$", "EUR": "€"}

# Currencies whose minor unit is not 1/100 of the major unit are not supported;
# Razorpay's INR flows are all 2-decimal, so this stays a constant.
MINOR_UNITS_PER_MAJOR = 100


def _group_indian(integer_part: str) -> str:
    """Group digits the Indian way: 1,00,000 rather than 100,000."""
    if len(integer_part) <= 3:
        return integer_part
    head, tail = integer_part[:-3], integer_part[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


def _group_western(integer_part: str) -> str:
    return f"{int(integer_part):,}"


def format_money(amount_minor: int, currency: str = "INR") -> str:
    """Render minor units as a display string, e.g. ``249900`` -> ``₹2,499.00``."""
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(amount_minor), MINOR_UNITS_PER_MAJOR)

    group = _group_indian if currency == "INR" else _group_western
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")

    return f"{sign}{symbol}{group(str(major))}.{minor:02d}"


def to_minor(amount_major: str | Decimal) -> int:
    """Convert a major-unit decimal string to minor units without float error."""
    return int((Decimal(str(amount_major)) * MINOR_UNITS_PER_MAJOR).to_integral_value())
