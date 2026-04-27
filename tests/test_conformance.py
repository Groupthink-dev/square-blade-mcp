"""Conformance harness — assert every contract operation is mapped.

Loads the canonical ``payments-v1.json`` and ``billing-v1.json`` from
``stallari-pack-spec`` and walks ``operations[]``. Every Required/Recommended
op must map to a tool that exists in :mod:`square_blade_mcp.server`. Optional
ops may be implemented or deferred. Gated ops that are deferred must be listed
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

# Operation → tool function name for billing-v1. ``None`` means not_supported in manifest.
BILLING_OPERATION_MAP: dict[str, str | None] = {
    # Required (6/6)
    "products": "square_catalog",
    "product": "square_catalog_object",
    "prices": "square_catalog",
    "customers": "square_customers",
    "subscriptions": "square_subscription_list",
    "transactions": "square_payments",
    # Recommended (6/8) — credit_balance + events not_supported
    "customer": "square_customer",
    "subscription": "square_subscription",
    "transaction": "square_payment",
    "invoice": "square_invoice",
    "adjustments": "square_refunds",
    "discounts": "square_catalog",
    "events": None,  # not_supported — use webhook_event_types via payments-v1
    "credit_balance": None,  # not_supported — Square has no equivalent
    # Optional (2/6) — notifications/reports/preview_transaction/ip_addresses not_supported
    "payment_methods": "square_cards",
    "verify_webhook": "square_verify_webhook",
    "notifications": None,
    "reports": None,
    "preview_transaction": None,
    "ip_addresses": None,
    # Gated (5/8) — create_discount/replay_notification/simulate not_supported
    "create_customer": "square_create_customer",
    "update_subscription": "square_update_subscription",
    "cancel_subscription": "square_cancel_subscription",
    "create_transaction": "square_create_payment",
    "create_adjustment": "square_create_refund",
    "create_discount": None,
    "replay_notification": None,
    "simulate": None,
}

# Ops declared not_supported in the manifest — must NOT have a tool mapped above.
BILLING_NOT_SUPPORTED = {
    "credit_balance",
    "events",
    "notifications",
    "reports",
    "preview_transaction",
    "ip_addresses",
    "create_discount",
    "replay_notification",
    "simulate",
}

# Tools whose underlying op is destructive — must accept a ``confirm`` parameter.
CONFIRM_GATED_TOOLS = {
    "square_cancel_payment",
    "square_delete_customer",
    "square_disable_card",
    "square_delete_webhook_subscription",
    "square_cancel_subscription",
    "square_pause_subscription",
    "square_resume_subscription",
    "square_send_invoice",
    "square_cancel_invoice",
}


def _load_contract(name: str, env_var: str) -> dict:
    """Load contract schema. Skips if pack-spec not on disk."""
    override = os.environ.get(env_var)
    candidates = [
        Path(override) if override else None,
        Path.home() / f"src/stallari-pack-spec/schema/contracts/{name}.json",
        Path.home() / f"src/stallari-pack-spec/dist/json/contracts/{name}.json",
    ]
    for path in candidates:
        if path and path.exists():
            return json.loads(path.read_text())
    pytest.skip(f"{name}.json not found — set {env_var}")


@pytest.fixture(scope="module")
def contract() -> dict:
    return _load_contract("payments-v1", "PAYMENTS_V1_SCHEMA")


@pytest.fixture(scope="module")
def operations(contract: dict) -> list[dict]:
    return contract["operations"]


@pytest.fixture(scope="module")
def billing_contract() -> dict:
    return _load_contract("billing-v1", "BILLING_V1_SCHEMA")


@pytest.fixture(scope="module")
def billing_operations(billing_contract: dict) -> list[dict]:
    return billing_contract["operations"]


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


class TestBillingContractCoverage:
    def test_every_op_appears_in_map(self, billing_operations: list[dict]) -> None:
        contract_ops = {op["name"] for op in billing_operations}
        mapped_ops = set(BILLING_OPERATION_MAP.keys())
        missing = contract_ops - mapped_ops
        assert not missing, f"billing-v1 ops not mapped: {sorted(missing)}"

    def test_no_extraneous_ops_in_map(self, billing_operations: list[dict]) -> None:
        contract_ops = {op["name"] for op in billing_operations}
        extra = set(BILLING_OPERATION_MAP.keys()) - contract_ops
        assert not extra, f"Mapped ops not in billing-v1 contract: {sorted(extra)}"

    def test_required_ops_implemented(self, billing_operations: list[dict]) -> None:
        for op in billing_operations:
            if op["classification"] == "required":
                tool = BILLING_OPERATION_MAP[op["name"]]
                assert tool is not None, (
                    f"Required billing-v1 op {op['name']!r} has no tool — must implement or move to not_supported"
                )

    def test_not_supported_has_no_tool(self) -> None:
        for op_name in BILLING_NOT_SUPPORTED:
            assert BILLING_OPERATION_MAP.get(op_name) is None, (
                f"Op {op_name!r} listed as not_supported but has a tool mapped"
            )


def _all_tool_names() -> list[str]:
    """Union of tool names from both contracts (de-duplicated, sorted)."""
    names: set[str] = set()
    for v in OPERATION_MAP.values():
        if v:
            names.add(v)
    for v in BILLING_OPERATION_MAP.values():
        if v:
            names.add(v)
    return sorted(names)


class TestToolImplementations:
    @pytest.mark.parametrize("tool_name", _all_tool_names())
    def test_tool_exists(self, tool_name: str) -> None:
        assert hasattr(server_module, tool_name), (
            f"Tool {tool_name!r} declared in an OPERATION_MAP but missing from server module"
        )

    @pytest.mark.parametrize("tool_name", _all_tool_names())
    def test_tool_is_async(self, tool_name: str) -> None:
        fn = getattr(server_module, tool_name)
        assert inspect.iscoroutinefunction(fn), f"{tool_name} must be async"

    @pytest.mark.parametrize("tool_name", sorted(CONFIRM_GATED_TOOLS))
    def test_destructive_tool_has_confirm(self, tool_name: str) -> None:
        fn = getattr(server_module, tool_name)
        sig = inspect.signature(fn)
        assert "confirm" in sig.parameters, f"Destructive tool {tool_name!r} must accept a confirm parameter"
