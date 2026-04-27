"""Conformance harness — assert every payments-v1 operation is mapped.

Loads the canonical ``payments-v1.json`` from ``stallari-pack-spec`` and
walks ``operations[]``. Every Required/Recommended op must map to a tool
that exists in :mod:`square_blade_mcp.server`. Optional ops may be
implemented or deferred. Gated ops that are deferred must be listed
explicitly so they appear in the README roadmap.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import square_blade_mcp.server as server_module

# Operation → tool function name. ``None`` means deferred for v0.1.0.
OPERATION_MAP: dict[str, str | None] = {
    # Payments — required
    "payment_create": "square_create_payment",
    "payment_get": "square_payment",
    "payment_list": "square_payments",
    "payment_cancel": "square_cancel_payment",
    "payment_complete": "square_complete_payment",
    # Refunds — required
    "refund_create": "square_create_refund",
    "refund_get": "square_refund",
    "refund_list": "square_refunds",
    # Customers — recommended
    "customer_create": "square_create_customer",
    "customer_get": "square_customer",
    "customer_list": "square_customers",
    "customer_update": "square_update_customer",
    # Cards — recommended
    "card_list": "square_cards",
    "card_create": "square_create_card",
    "card_disable": "square_disable_card",
    # Locations — recommended
    "location_list": "square_locations",
    # Orders — optional
    "order_create": "square_create_order",
    "order_get": "square_order",
    "order_list": "square_search_orders",
    "order_pay": "square_pay_order",
    "order_update": "square_update_order",
    # Catalog — optional
    "catalog_list": "square_catalog",
    "catalog_get": "square_catalog_object",
    # Inventory — optional
    "inventory_count": "square_inventory",
    # Disputes — optional
    "dispute_list": "square_disputes",
    "dispute_get": "square_dispute",
    # Webhooks — required
    "webhook_subscription_list": "square_webhook_subscriptions",
    "webhook_subscription_create": "square_create_webhook_subscription",
    "webhook_event_types": "square_webhook_event_types",
    "webhook_verify": "square_verify_webhook",
    # Gated — implemented
    "customer_delete": "square_delete_customer",
    "webhook_subscription_delete": "square_delete_webhook_subscription",
    # Gated — deferred for v0.1.0 (must appear in README roadmap)
    "card_delete": None,
    "payment_void": None,
    "refund_unlinked": None,
    "inventory_adjust": None,
}

# Tools whose underlying op is destructive — must accept a ``confirm`` parameter.
CONFIRM_GATED_TOOLS = {
    "square_cancel_payment",
    "square_delete_customer",
    "square_disable_card",
    "square_delete_webhook_subscription",
}


def _load_contract() -> dict:
    """Load payments-v1 schema. Skips if pack-spec not on disk."""
    override = os.environ.get("PAYMENTS_V1_SCHEMA")
    candidates = [
        Path(override) if override else None,
        Path.home() / "src/stallari-pack-spec/schema/contracts/payments-v1.json",
    ]
    for path in candidates:
        if path and path.exists():
            return json.loads(path.read_text())
    pytest.skip("payments-v1.json not found — set PAYMENTS_V1_SCHEMA")


@pytest.fixture(scope="module")
def contract() -> dict:
    return _load_contract()


@pytest.fixture(scope="module")
def operations(contract: dict) -> list[dict]:
    return contract["operations"]


class TestContractCoverage:
    def test_every_op_appears_in_map(self, operations: list[dict]) -> None:
        contract_ops = {op["name"] for op in operations}
        mapped_ops = set(OPERATION_MAP.keys())
        missing = contract_ops - mapped_ops
        assert not missing, f"Contract ops not mapped: {sorted(missing)}"

    def test_no_extraneous_ops_in_map(self, operations: list[dict]) -> None:
        contract_ops = {op["name"] for op in operations}
        extra = set(OPERATION_MAP.keys()) - contract_ops
        assert not extra, f"Mapped ops not in contract: {sorted(extra)}"

    def test_required_ops_implemented(self, operations: list[dict]) -> None:
        for op in operations:
            if op["classification"] == "required":
                tool = OPERATION_MAP[op["name"]]
                assert tool is not None, f"Required op {op['name']!r} has no tool implementation"

    def test_recommended_ops_implemented(self, operations: list[dict]) -> None:
        for op in operations:
            if op["classification"] == "recommended":
                tool = OPERATION_MAP[op["name"]]
                assert tool is not None, (
                    f"Recommended op {op['name']!r} has no tool implementation (downgrade to optional or implement)"
                )


class TestToolImplementations:
    @pytest.mark.parametrize("tool_name", sorted(t for t in OPERATION_MAP.values() if t))
    def test_tool_exists(self, tool_name: str) -> None:
        assert hasattr(server_module, tool_name), (
            f"Tool {tool_name!r} declared in OPERATION_MAP but missing from server module"
        )

    @pytest.mark.parametrize("tool_name", sorted(t for t in OPERATION_MAP.values() if t))
    def test_tool_is_async(self, tool_name: str) -> None:
        fn = getattr(server_module, tool_name)
        assert inspect.iscoroutinefunction(fn), f"{tool_name} must be async"

    @pytest.mark.parametrize("tool_name", sorted(CONFIRM_GATED_TOOLS))
    def test_destructive_tool_has_confirm(self, tool_name: str) -> None:
        fn = getattr(server_module, tool_name)
        sig = inspect.signature(fn)
        assert "confirm" in sig.parameters, f"Destructive tool {tool_name!r} must accept a confirm parameter"
