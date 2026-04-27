"""Shared fixtures for square-blade-mcp tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a clean env for every test — no real Square credentials leak."""
    monkeypatch.delenv("SQUARE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SQUARE_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SQUARE_WRITE_ENABLED", raising=False)
    monkeypatch.delenv("SQUARE_MCP_API_TOKEN", raising=False)
    monkeypatch.delenv("SQUARE_WEBHOOK_SIGNATURE_KEY", raising=False)


@pytest.fixture
def sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up sandbox env vars for client construction.

    Note: token is fake — real PATs start with EAAA. This shape is recognised
    by scrubbing tests but rejected by the live API, which is what we want.
    """
    monkeypatch.setenv("SQUARE_ACCESS_TOKEN", "EAAAtest_token_123_abc")
    monkeypatch.setenv("SQUARE_ENVIRONMENT", "sandbox")


@pytest.fixture
def write_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable write operations."""
    monkeypatch.setenv("SQUARE_WRITE_ENABLED", "true")


# ---------------------------------------------------------------------------
# Sample Square API responses
# ---------------------------------------------------------------------------


SAMPLE_PAYMENT: dict[str, Any] = {
    "id": "Aw4G5pkXn5pIE0OBWZ4yvNZK",
    "status": "COMPLETED",
    "amount_money": {"amount": 2900, "currency": "USD"},
    "total_money": {"amount": 2900, "currency": "USD"},
    "source_type": "CARD",
    "location_id": "L1A2B3C4D5",
    "order_id": "ord_xyz",
    "customer_id": "cust_abc",
    "card_details": {
        "status": "CAPTURED",
        "entry_method": "CONTACTLESS",
        "card": {
            "card_brand": "VISA",
            "last_4": "4242",
            "exp_month": 12,
            "exp_year": 2028,
        },
    },
    "created_at": "2026-03-15T10:00:00Z",
    "updated_at": "2026-03-15T10:00:00Z",
}

SAMPLE_REFUND: dict[str, Any] = {
    "id": "ref_xyz",
    "payment_id": "Aw4G5pkXn5pIE0OBWZ4yvNZK",
    "amount_money": {"amount": 1000, "currency": "USD"},
    "status": "COMPLETED",
    "reason": "Customer request",
    "location_id": "L1A2B3C4D5",
    "created_at": "2026-03-16T10:00:00Z",
}

SAMPLE_CUSTOMER: dict[str, Any] = {
    "id": "cust_abc",
    "given_name": "Alice",
    "family_name": "Smith",
    "email_address": "alice@example.com",
    "phone_number": "+15551234567",
    "reference_id": "internal_42",
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-15T10:00:00Z",
}

SAMPLE_CARD: dict[str, Any] = {
    "id": "card_xyz",
    "card_brand": "VISA",
    "last_4": "4242",
    "exp_month": 12,
    "exp_year": 2028,
    "cardholder_name": "Alice Smith",
    "customer_id": "cust_abc",
    "fingerprint": "sq-1-fingerprint",
    "enabled": True,
}

SAMPLE_LOCATION: dict[str, Any] = {
    "id": "L1A2B3C4D5",
    "name": "Main Store",
    "status": "ACTIVE",
    "type": "PHYSICAL",
    "currency": "USD",
    "country": "US",
    "address": {
        "address_line_1": "1 Market St",
        "locality": "San Francisco",
        "administrative_district_level_1": "CA",
        "postal_code": "94103",
        "country": "US",
    },
    "merchant_id": "MERCH_X",
}

SAMPLE_ORDER: dict[str, Any] = {
    "id": "ord_xyz",
    "location_id": "L1A2B3C4D5",
    "state": "OPEN",
    "total_money": {"amount": 2900, "currency": "USD"},
    "line_items": [{"name": "Pro Plan", "quantity": "1", "total_money": {"amount": 2900, "currency": "USD"}}],
    "created_at": "2026-03-15T10:00:00Z",
}

SAMPLE_DISPUTE: dict[str, Any] = {
    "id": "disp_xyz",
    "state": "EVIDENCE_REQUIRED",
    "reason": "NOT_AS_DESCRIBED",
    "amount_money": {"amount": 2900, "currency": "USD"},
    "disputed_payment": {"payment_id": "Aw4G5pkXn5pIE0OBWZ4yvNZK"},
    "location_id": "L1A2B3C4D5",
    "card_brand": "VISA",
    "due_at": "2026-04-01T00:00:00Z",
}

SAMPLE_WEBHOOK_SUB: dict[str, Any] = {
    "id": "wbhk_xyz",
    "name": "All payments",
    "notification_url": "https://example.com/webhook",
    "event_types": ["payment.created", "payment.updated", "refund.updated"],
    "api_version": "2024-12-18",
    "enabled": True,
    "signature_key": "secret_should_be_hidden",
    "created_at": "2026-03-01T00:00:00Z",
}


def make_list_response(items: list[dict[str, Any]], key: str, cursor: str | None = None) -> dict[str, Any]:
    """Build a Square typed-list response."""
    out: dict[str, Any] = {key: items}
    if cursor:
        out["cursor"] = cursor
    return out
