"""Configuration guard tests.

The single most important invariant of this project: it can never be pointed
at a live Razorpay account.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_live_razorpay_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="TEST-mode key"):
        Settings(razorpay_key_id="rzp_live_abc123")


def test_test_mode_razorpay_key_is_accepted() -> None:
    s = Settings(razorpay_key_id="rzp_test_abc123", razorpay_key_secret="shh")
    assert s.razorpay_configured is True


def test_blank_razorpay_key_is_allowed_but_not_configured() -> None:
    """A blank key must not crash startup — it degrades the health report."""
    s = Settings(razorpay_key_id="")
    assert s.razorpay_configured is False


def test_cors_origins_parse_into_a_list() -> None:
    s = Settings(cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origin_list == ["http://a.com", "http://b.com"]
