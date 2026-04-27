"""Square Blade MCP Server — Square Payments API operations.

Token-efficient by default: pipe-delimited lists, field selection,
human-readable money, null-field omission. Write operations gated
behind ``SQUARE_WRITE_ENABLED=true``. Destructive operations require
``confirm=true``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from square_blade_mcp.client import SquareClient, SquareError
from square_blade_mcp.formatters import (
    format_card_detail,
    format_card_list,
    format_catalog_detail,
    format_catalog_list,
    format_customer_detail,
    format_customer_list,
    format_dispute_detail,
    format_dispute_list,
    format_event_type_list,
    format_info,
    format_inventory_counts,
    format_location_detail,
    format_location_list,
    format_order_detail,
    format_order_list,
    format_payment_detail,
    format_payment_list,
    format_refund_detail,
    format_refund_list,
    format_webhook_subscription_detail,
    format_webhook_subscription_list,
    format_webhook_verification,
)
from square_blade_mcp.models import (
    DEFAULT_LIMIT,
    is_write_enabled,
    require_confirm,
    require_write,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transport configuration
# ---------------------------------------------------------------------------

TRANSPORT = os.environ.get("SQUARE_MCP_TRANSPORT", "stdio")
HTTP_HOST = os.environ.get("SQUARE_MCP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("SQUARE_MCP_PORT", "8770"))

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "SquareBlade",
    instructions=(
        "Square Payments API operations. Manage payments, refunds, customers, "
        "cards-on-file, locations, orders, catalog, inventory, disputes, and "
        "webhooks. Token-efficient responses with pipe-delimited lists, field "
        "selection, and human-readable money. Write operations require "
        "SQUARE_WRITE_ENABLED=true. Destructive operations (cancel, delete) "
        "require confirm=true. Card data is PCI-safe (last_4/brand/exp only)."
    ),
)

_client: SquareClient | None = None


async def _get_client() -> SquareClient:
    """Get or create the SquareClient singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = SquareClient()
        logger.info("SquareClient: env=%s", _client.environment)
    return _client


def _error(e: SquareError) -> str:
    """Format a client error as a user-friendly string."""
    return f"Error: {e}"


def _parse_json(s: str | None, label: str) -> Any:
    """Parse a JSON string argument; return None if input is empty."""
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise SquareError(f"Invalid JSON for {label}: {e}") from e


# ===========================================================================
# Meta
# ===========================================================================


@mcp.tool
async def square_info() -> str:
    """Show Square environment, API version, and write-gate status."""
    try:
        client = await _get_client()
        return format_info(client.environment, client.api_version, is_write_enabled())
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Payments
# ===========================================================================


@mcp.tool
async def square_payments(
    begin_time: Annotated[str | None, Field(description="RFC 3339 timestamp lower bound")] = None,
    end_time: Annotated[str | None, Field(description="RFC 3339 timestamp upper bound")] = None,
    sort_order: Annotated[str | None, Field(description="ASC or DESC")] = None,
    location_id: Annotated[str | None, Field(description="Filter by location")] = None,
    total: Annotated[int | None, Field(description="Filter by exact amount in smallest unit")] = None,
    last_4: Annotated[str | None, Field(description="Filter by card last 4 digits")] = None,
    card_brand: Annotated[str | None, Field(description="Filter by card brand")] = None,
    limit: Annotated[int, Field(description="Max results (default 20, max 100)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """List payments. Cursor paginated."""
    try:
        client = await _get_client()
        result = await client.list_payments(
            begin_time=begin_time,
            end_time=end_time,
            sort_order=sort_order,
            location_id=location_id,
            total=total,
            last_4=last_4,
            card_brand=card_brand,
            limit=limit,
            cursor=cursor,
        )
        return format_payment_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_payment(
    payment_id: Annotated[str, Field(description="Payment ID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get payment detail."""
    try:
        client = await _get_client()
        result = await client.get_payment(payment_id)
        return format_payment_detail(result.get("payment", {}), fields)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_create_payment(
    source_id: Annotated[str, Field(description="Payment source token (nonce, card_id, gift card id)")],
    amount: Annotated[int, Field(description="Amount in smallest currency unit (cents)")],
    currency: Annotated[str, Field(description="ISO 4217 currency code (USD, EUR, ...)")],
    location_id: Annotated[str | None, Field(description="Location ID")] = None,
    customer_id: Annotated[str | None, Field(description="Customer ID")] = None,
    order_id: Annotated[str | None, Field(description="Order ID to attach")] = None,
    reference_id: Annotated[str | None, Field(description="Merchant reference (≤40 chars)")] = None,
    note: Annotated[str | None, Field(description="Internal note (≤500 chars)")] = None,
    autocomplete: Annotated[bool | None, Field(description="False = authorise only (delayed capture)")] = None,
    idempotency_key: Annotated[
        str | None, Field(description="Caller idempotency key (auto-generated if absent)")
    ] = None,
) -> str:
    """Charge a payment source. Requires SQUARE_WRITE_ENABLED=true."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {
            "source_id": source_id,
            "amount_money": {"amount": amount, "currency": currency},
        }
        if location_id:
            body["location_id"] = location_id
        if customer_id:
            body["customer_id"] = customer_id
        if order_id:
            body["order_id"] = order_id
        if reference_id:
            body["reference_id"] = reference_id
        if note:
            body["note"] = note
        if autocomplete is not None:
            body["autocomplete"] = autocomplete
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.create_payment(body)
        return format_payment_detail(result.get("payment", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_cancel_payment(
    payment_id: Annotated[str, Field(description="Payment ID")],
    confirm: Annotated[bool, Field(description="Must be true; cancellation is irreversible")] = False,
) -> str:
    """Cancel a delayed-capture or authorisation. Gated: confirm=true required."""
    if err := require_write():
        return err
    if err := require_confirm(confirm, "cancel_payment"):
        return err
    try:
        client = await _get_client()
        result = await client.cancel_payment(payment_id)
        return format_payment_detail(result.get("payment", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_complete_payment(
    payment_id: Annotated[str, Field(description="Payment ID")],
) -> str:
    """Capture a previously-authorised payment."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        result = await client.complete_payment(payment_id)
        return format_payment_detail(result.get("payment", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Refunds
# ===========================================================================


@mcp.tool
async def square_refunds(
    begin_time: Annotated[str | None, Field(description="RFC 3339 timestamp lower bound")] = None,
    end_time: Annotated[str | None, Field(description="RFC 3339 timestamp upper bound")] = None,
    sort_order: Annotated[str | None, Field(description="ASC or DESC")] = None,
    location_id: Annotated[str | None, Field(description="Filter by location")] = None,
    status: Annotated[str | None, Field(description="Filter: PENDING, COMPLETED, REJECTED, FAILED")] = None,
    source_type: Annotated[str | None, Field(description="Filter: CARD, CASH, EXTERNAL")] = None,
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """List refunds. Cursor paginated."""
    try:
        client = await _get_client()
        result = await client.list_refunds(
            begin_time=begin_time,
            end_time=end_time,
            sort_order=sort_order,
            location_id=location_id,
            status=status,
            source_type=source_type,
            limit=limit,
            cursor=cursor,
        )
        return format_refund_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_refund(
    refund_id: Annotated[str, Field(description="Refund ID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get refund detail."""
    try:
        client = await _get_client()
        result = await client.get_refund(refund_id)
        return format_refund_detail(result.get("refund", {}), fields)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_create_refund(
    payment_id: Annotated[str, Field(description="Payment to refund (linked refund)")],
    amount: Annotated[int, Field(description="Refund amount in smallest currency unit")],
    currency: Annotated[str, Field(description="ISO 4217 currency code (must match payment)")],
    reason: Annotated[str | None, Field(description="Refund reason (≤192 chars)")] = None,
    idempotency_key: Annotated[
        str | None, Field(description="Caller idempotency key (auto-generated if absent)")
    ] = None,
) -> str:
    """Create a linked refund against an existing payment. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {
            "payment_id": payment_id,
            "amount_money": {"amount": amount, "currency": currency},
        }
        if reason:
            body["reason"] = reason
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.create_refund(body)
        return format_refund_detail(result.get("refund", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Customers
# ===========================================================================


@mcp.tool
async def square_customers(
    sort_field: Annotated[str | None, Field(description="DEFAULT or CREATED_AT")] = None,
    sort_order: Annotated[str | None, Field(description="ASC or DESC")] = None,
    count: Annotated[bool | None, Field(description="Return total count")] = None,
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """List customers. Cursor paginated."""
    try:
        client = await _get_client()
        result = await client.list_customers(
            sort_field=sort_field,
            sort_order=sort_order,
            count=count,
            limit=limit,
            cursor=cursor,
        )
        return format_customer_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_search_customers(
    query: Annotated[str, Field(description="Square search query as JSON (filter, sort fields)")],
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """Search customers using Square's structured query.

    ``query`` is a JSON object matching Square's ``query`` body, e.g.::

        {"filter": {"email_address": {"exact": "alice@example.com"}}}
    """
    try:
        client = await _get_client()
        body: dict[str, Any] = {"limit": limit}
        if cursor:
            body["cursor"] = cursor
        parsed = _parse_json(query, "query")
        if parsed:
            body["query"] = parsed
        result = await client.search_customers(body)
        return format_customer_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_customer(
    customer_id: Annotated[str, Field(description="Customer ID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get customer detail."""
    try:
        client = await _get_client()
        result = await client.get_customer(customer_id)
        return format_customer_detail(result.get("customer", {}), fields)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_create_customer(
    given_name: Annotated[str | None, Field(description="First name")] = None,
    family_name: Annotated[str | None, Field(description="Last name")] = None,
    email_address: Annotated[str | None, Field(description="Email")] = None,
    phone_number: Annotated[str | None, Field(description="E.164 phone")] = None,
    company_name: Annotated[str | None, Field(description="Company name")] = None,
    nickname: Annotated[str | None, Field(description="Nickname")] = None,
    note: Annotated[str | None, Field(description="Internal note")] = None,
    reference_id: Annotated[str | None, Field(description="Merchant reference")] = None,
    address: Annotated[str | None, Field(description="Address as JSON object")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Create a customer. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {}
        for k, v in {
            "given_name": given_name,
            "family_name": family_name,
            "email_address": email_address,
            "phone_number": phone_number,
            "company_name": company_name,
            "nickname": nickname,
            "note": note,
            "reference_id": reference_id,
            "idempotency_key": idempotency_key,
        }.items():
            if v is not None:
                body[k] = v
        if address:
            body["address"] = _parse_json(address, "address")
        result = await client.create_customer(body)
        return format_customer_detail(result.get("customer", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_update_customer(
    customer_id: Annotated[str, Field(description="Customer ID")],
    given_name: Annotated[str | None, Field(description="First name (set to '' to clear)")] = None,
    family_name: Annotated[str | None, Field(description="Last name")] = None,
    email_address: Annotated[str | None, Field(description="Email")] = None,
    phone_number: Annotated[str | None, Field(description="E.164 phone")] = None,
    company_name: Annotated[str | None, Field(description="Company name")] = None,
    nickname: Annotated[str | None, Field(description="Nickname")] = None,
    note: Annotated[str | None, Field(description="Internal note")] = None,
    reference_id: Annotated[str | None, Field(description="Merchant reference")] = None,
    address: Annotated[str | None, Field(description="Address as JSON object")] = None,
    version: Annotated[int | None, Field(description="Optimistic concurrency version")] = None,
) -> str:
    """Update a customer (PUT — replaces fields you supply). Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {}
        for k, v in {
            "given_name": given_name,
            "family_name": family_name,
            "email_address": email_address,
            "phone_number": phone_number,
            "company_name": company_name,
            "nickname": nickname,
            "note": note,
            "reference_id": reference_id,
            "version": version,
        }.items():
            if v is not None:
                body[k] = v
        if address:
            body["address"] = _parse_json(address, "address")
        result = await client.update_customer(customer_id, body)
        return format_customer_detail(result.get("customer", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_delete_customer(
    customer_id: Annotated[str, Field(description="Customer ID")],
    confirm: Annotated[bool, Field(description="Must be true; deletion is permanent")] = False,
) -> str:
    """Delete a customer. Gated: confirm=true required."""
    if err := require_write():
        return err
    if err := require_confirm(confirm, "delete_customer"):
        return err
    try:
        client = await _get_client()
        await client.delete_customer(customer_id)
        return f"Deleted customer {customer_id}"
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Cards (cards-on-file)
# ===========================================================================


@mcp.tool
async def square_cards(
    customer_id: Annotated[str | None, Field(description="Filter by customer")] = None,
    include_disabled: Annotated[bool | None, Field(description="Include disabled cards")] = None,
    reference_id: Annotated[str | None, Field(description="Filter by merchant reference")] = None,
    sort_order: Annotated[str | None, Field(description="ASC or DESC")] = None,
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """List saved cards-on-file. PCI-safe: last_4/brand/exp only."""
    try:
        client = await _get_client()
        result = await client.list_cards(
            customer_id=customer_id,
            include_disabled=include_disabled,
            reference_id=reference_id,
            sort_order=sort_order,
            limit=limit,
            cursor=cursor,
        )
        return format_card_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_card(
    card_id: Annotated[str, Field(description="Card ID")],
) -> str:
    """Get saved-card detail (PCI-safe)."""
    try:
        client = await _get_client()
        result = await client.get_card(card_id)
        return format_card_detail(result.get("card", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_create_card(
    source_id: Annotated[str, Field(description="Payment source token (nonce or payment_id)")],
    customer_id: Annotated[str, Field(description="Customer to attach card to")],
    cardholder_name: Annotated[str | None, Field(description="Cardholder name")] = None,
    reference_id: Annotated[str | None, Field(description="Merchant reference")] = None,
    billing_address: Annotated[str | None, Field(description="Billing address as JSON object")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Save a card-on-file from a payment source. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        card: dict[str, Any] = {"customer_id": customer_id}
        if cardholder_name:
            card["cardholder_name"] = cardholder_name
        if reference_id:
            card["reference_id"] = reference_id
        if billing_address:
            card["billing_address"] = _parse_json(billing_address, "billing_address")
        body: dict[str, Any] = {"source_id": source_id, "card": card}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.create_card(body)
        return format_card_detail(result.get("card", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_disable_card(
    card_id: Annotated[str, Field(description="Card ID")],
    confirm: Annotated[bool, Field(description="Must be true; disable is irreversible")] = False,
) -> str:
    """Disable a saved card-on-file. Gated: confirm=true required."""
    if err := require_write():
        return err
    if err := require_confirm(confirm, "disable_card"):
        return err
    try:
        client = await _get_client()
        result = await client.disable_card(card_id)
        return format_card_detail(result.get("card", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Locations
# ===========================================================================


@mcp.tool
async def square_locations() -> str:
    """List all merchant locations."""
    try:
        client = await _get_client()
        result = await client.list_locations()
        return format_location_list(result)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_location(
    location_id: Annotated[str, Field(description="Location ID (or 'main')")],
) -> str:
    """Get location detail."""
    try:
        client = await _get_client()
        result = await client.get_location(location_id)
        return format_location_detail(result.get("location", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Orders
# ===========================================================================


@mcp.tool
async def square_create_order(
    location_id: Annotated[str, Field(description="Location ID")],
    line_items: Annotated[str, Field(description="Line items array as JSON")],
    customer_id: Annotated[str | None, Field(description="Customer ID")] = None,
    reference_id: Annotated[str | None, Field(description="Merchant reference")] = None,
    state: Annotated[str | None, Field(description="OPEN, COMPLETED, or DRAFT")] = None,
    taxes: Annotated[str | None, Field(description="Taxes array as JSON")] = None,
    discounts: Annotated[str | None, Field(description="Discounts array as JSON")] = None,
    fulfillments: Annotated[str | None, Field(description="Fulfillments array as JSON")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Create an order. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        order: dict[str, Any] = {
            "location_id": location_id,
            "line_items": _parse_json(line_items, "line_items"),
        }
        for k, v in {
            "customer_id": customer_id,
            "reference_id": reference_id,
            "state": state,
        }.items():
            if v is not None:
                order[k] = v
        for k, v in {"taxes": taxes, "discounts": discounts, "fulfillments": fulfillments}.items():
            if v:
                order[k] = _parse_json(v, k)
        body: dict[str, Any] = {"order": order}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.create_order(body)
        return format_order_detail(result.get("order", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_order(
    order_id: Annotated[str, Field(description="Order ID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get order detail."""
    try:
        client = await _get_client()
        result = await client.get_order(order_id)
        return format_order_detail(result.get("order", {}), fields)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_search_orders(
    location_ids: Annotated[str, Field(description="Comma-separated location IDs to search")],
    query: Annotated[str | None, Field(description="Search query as JSON (filter, sort)")] = None,
    return_entries: Annotated[
        bool | None, Field(description="Return order entries (lighter) instead of full orders")
    ] = None,
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """Search orders across one or more locations."""
    try:
        client = await _get_client()
        body: dict[str, Any] = {
            "location_ids": [s.strip() for s in location_ids.split(",") if s.strip()],
            "limit": limit,
        }
        if query:
            body["query"] = _parse_json(query, "query")
        if return_entries is not None:
            body["return_entries"] = return_entries
        if cursor:
            body["cursor"] = cursor
        result = await client.search_orders(body)
        return format_order_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_update_order(
    order_id: Annotated[str, Field(description="Order ID")],
    order: Annotated[str, Field(description="Order patch as JSON object")],
    fields_to_clear: Annotated[str | None, Field(description="Comma-separated dotted paths to clear")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Update an order (line items, fulfilment, metadata). Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {"order": _parse_json(order, "order")}
        if fields_to_clear:
            body["fields_to_clear"] = [s.strip() for s in fields_to_clear.split(",") if s.strip()]
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.update_order(order_id, body)
        return format_order_detail(result.get("order", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_pay_order(
    order_id: Annotated[str, Field(description="Order ID")],
    payment_ids: Annotated[str | None, Field(description="Comma-separated payment IDs to apply")] = None,
    order_version: Annotated[int | None, Field(description="Required if order has been modified")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Pay an existing order using one or more payment IDs. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        body: dict[str, Any] = {}
        if payment_ids:
            body["payment_ids"] = [s.strip() for s in payment_ids.split(",") if s.strip()]
        if order_version is not None:
            body["order_version"] = order_version
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.pay_order(order_id, body)
        return format_order_detail(result.get("order", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Catalog
# ===========================================================================


@mcp.tool
async def square_catalog(
    types: Annotated[str | None, Field(description="Comma-separated types: ITEM, CATEGORY, MODIFIER, ...")] = None,
    catalog_version: Annotated[int | None, Field(description="Specific catalog version")] = None,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
    limit: Annotated[int, Field(description="Display limit (Square paginates server-side)")] = DEFAULT_LIMIT,
) -> str:
    """List catalog objects (items, categories, modifiers, ...)."""
    try:
        client = await _get_client()
        result = await client.list_catalog(types=types, catalog_version=catalog_version, cursor=cursor)
        return format_catalog_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_catalog_object(
    object_id: Annotated[str, Field(description="Catalog object ID")],
    include_related_objects: Annotated[bool | None, Field(description="Include related objects in response")] = None,
    catalog_version: Annotated[int | None, Field(description="Specific catalog version")] = None,
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get a catalog object."""
    try:
        client = await _get_client()
        result = await client.get_catalog_object(
            object_id,
            include_related_objects=include_related_objects,
            catalog_version=catalog_version,
        )
        return format_catalog_detail(result, fields)
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Inventory
# ===========================================================================


@mcp.tool
async def square_inventory(
    catalog_object_ids: Annotated[str | None, Field(description="Comma-separated catalog object IDs")] = None,
    location_ids: Annotated[str | None, Field(description="Comma-separated location IDs")] = None,
    updated_after: Annotated[str | None, Field(description="RFC 3339 lower bound on updated_at")] = None,
    states: Annotated[
        str | None, Field(description="Comma-separated states: IN_STOCK, SOLD, RETURNED_BY_CUSTOMER, ...")
    ] = None,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
    limit: Annotated[int, Field(description="Display limit")] = DEFAULT_LIMIT,
) -> str:
    """Batch retrieve inventory counts."""
    try:
        client = await _get_client()
        body: dict[str, Any] = {}
        if catalog_object_ids:
            body["catalog_object_ids"] = [s.strip() for s in catalog_object_ids.split(",") if s.strip()]
        if location_ids:
            body["location_ids"] = [s.strip() for s in location_ids.split(",") if s.strip()]
        if updated_after:
            body["updated_after"] = updated_after
        if states:
            body["states"] = [s.strip() for s in states.split(",") if s.strip()]
        if cursor:
            body["cursor"] = cursor
        result = await client.batch_retrieve_inventory_counts(body)
        return format_inventory_counts(result, limit)
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Disputes
# ===========================================================================


@mcp.tool
async def square_disputes(
    states: Annotated[
        str | None, Field(description="Filter: INQUIRY_EVIDENCE_REQUIRED, EVIDENCE_REQUIRED, ...")
    ] = None,
    location_id: Annotated[str | None, Field(description="Filter by location")] = None,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
    limit: Annotated[int, Field(description="Display limit")] = DEFAULT_LIMIT,
) -> str:
    """List disputes (chargebacks)."""
    try:
        client = await _get_client()
        result = await client.list_disputes(states=states, location_id=location_id, cursor=cursor)
        return format_dispute_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_dispute(
    dispute_id: Annotated[str, Field(description="Dispute ID")],
) -> str:
    """Get dispute detail."""
    try:
        client = await _get_client()
        result = await client.get_dispute(dispute_id)
        return format_dispute_detail(result.get("dispute", {}))
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Webhooks
# ===========================================================================


@mcp.tool
async def square_webhook_subscriptions(
    include_disabled: Annotated[bool | None, Field(description="Include disabled subscriptions")] = None,
    sort_order: Annotated[str | None, Field(description="ASC or DESC")] = None,
    limit: Annotated[int, Field(description="Max results (default 20)")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
) -> str:
    """List webhook subscriptions."""
    try:
        client = await _get_client()
        result = await client.list_webhook_subscriptions(
            include_disabled=include_disabled,
            sort_order=sort_order,
            limit=limit,
            cursor=cursor,
        )
        return format_webhook_subscription_list(result, limit)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_create_webhook_subscription(
    name: Annotated[str, Field(description="Subscription name")],
    notification_url: Annotated[str, Field(description="HTTPS URL Square will POST events to")],
    event_types: Annotated[
        str, Field(description="Comma-separated event types (e.g., payment.created,refund.updated)")
    ],
    api_version: Annotated[str | None, Field(description="Square API version to use for the subscription")] = None,
    idempotency_key: Annotated[str | None, Field(description="Caller idempotency key")] = None,
) -> str:
    """Create a webhook subscription. Requires write enabled."""
    if err := require_write():
        return err
    try:
        client = await _get_client()
        subscription: dict[str, Any] = {
            "name": name,
            "notification_url": notification_url,
            "event_types": [s.strip() for s in event_types.split(",") if s.strip()],
        }
        if api_version:
            subscription["api_version"] = api_version
        body: dict[str, Any] = {"subscription": subscription}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        result = await client.create_webhook_subscription(body)
        return format_webhook_subscription_detail(result.get("subscription", {}))
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_delete_webhook_subscription(
    subscription_id: Annotated[str, Field(description="Webhook subscription ID")],
    confirm: Annotated[bool, Field(description="Must be true; deletion is permanent")] = False,
) -> str:
    """Delete a webhook subscription. Gated: confirm=true required."""
    if err := require_write():
        return err
    if err := require_confirm(confirm, "delete_webhook_subscription"):
        return err
    try:
        client = await _get_client()
        await client.delete_webhook_subscription(subscription_id)
        return f"Deleted webhook subscription {subscription_id}"
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_webhook_event_types(
    api_version: Annotated[str | None, Field(description="Square API version to enumerate types for")] = None,
) -> str:
    """List available webhook event types."""
    try:
        client = await _get_client()
        result = await client.list_webhook_event_types(api_version=api_version)
        return format_event_type_list(result)
    except SquareError as e:
        return _error(e)


@mcp.tool
async def square_verify_webhook(
    raw_body: Annotated[str, Field(description="Raw HTTP request body bytes-as-str")],
    signature: Annotated[str, Field(description="Value of x-square-hmacsha256-signature header")],
    signature_key: Annotated[str, Field(description="Subscription signature key")],
    notification_url: Annotated[str, Field(description="The URL Square posted to (must match exactly)")],
) -> str:
    """Verify and parse a Square webhook in one round-trip."""
    try:
        client = await _get_client()
        result = client.verify_webhook_signature(
            raw_body=raw_body,
            signature_header=signature,
            webhook_signature_key=signature_key,
            notification_url=notification_url,
        )
        return format_webhook_verification(result)
    except SquareError as e:
        return _error(e)


# ===========================================================================
# Entrypoint
# ===========================================================================


def main() -> None:
    """Start the FastMCP server in the configured transport."""
    logging.basicConfig(
        level=os.environ.get("SQUARE_MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    if TRANSPORT == "http":
        from starlette.middleware import Middleware

        from square_blade_mcp.auth import BearerAuthMiddleware, get_bearer_token

        bearer = get_bearer_token()
        logger.info("SquareBlade HTTP on %s:%s (auth=%s)", HTTP_HOST, HTTP_PORT, "on" if bearer else "off")
        mcp.run(
            transport="http",
            host=HTTP_HOST,
            port=HTTP_PORT,
            middleware=[Middleware(BearerAuthMiddleware)],
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
