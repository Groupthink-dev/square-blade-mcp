"""Tests for server.py — MCP tool integration tests with mocked client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import square_blade_mcp.server as server_module
from square_blade_mcp.server import (
    square_cancel_payment,
    square_card,
    square_cards,
    square_create_card,
    square_create_customer,
    square_create_payment,
    square_create_refund,
    square_create_webhook_subscription,
    square_customer,
    square_customers,
    square_delete_customer,
    square_delete_webhook_subscription,
    square_dispute,
    square_disputes,
    square_info,
    square_inventory,
    square_location,
    square_locations,
    square_order,
    square_payment,
    square_payments,
    square_refund,
    square_refunds,
    square_search_customers,
    square_search_orders,
    square_update_customer,
    square_verify_webhook,
    square_webhook_event_types,
    square_webhook_subscriptions,
)
from tests.conftest import (
    SAMPLE_CARD,
    SAMPLE_CUSTOMER,
    SAMPLE_DISPUTE,
    SAMPLE_LOCATION,
    SAMPLE_ORDER,
    SAMPLE_PAYMENT,
    SAMPLE_REFUND,
    SAMPLE_WEBHOOK_SUB,
    make_list_response,
)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """Reset the lazy client singleton between tests."""
    server_module._client = None


@pytest.fixture
def mock_client(sandbox_env: None) -> AsyncMock:
    """Provide a mocked SquareClient and patch _get_client to return it."""
    mock = AsyncMock()
    mock.environment = "sandbox"
    mock.api_version = "2024-12-18"

    # verify_webhook_signature is a static method, not async
    mock.verify_webhook_signature = lambda **kwargs: {
        "verified": True,
        "event": {
            "event_type": "payment.created",
            "event_id": "evt_x",
            "merchant_id": "M",
            "created_at": "2026-03-15T10:00:00Z",
            "data": {},
        },
    }

    async def fake_get_client() -> AsyncMock:
        return mock

    patcher = patch("square_blade_mcp.server._get_client", side_effect=fake_get_client)
    patcher.start()
    yield mock
    patcher.stop()


class TestMeta:
    @pytest.mark.asyncio
    async def test_info(self, mock_client: AsyncMock) -> None:
        result = await square_info()
        assert "sandbox" in result
        assert "2024-12-18" in result


class TestPayments:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_payments.return_value = make_list_response([SAMPLE_PAYMENT], "payments")
        result = await square_payments(location_id="L1")
        assert "Aw4G5pkXn5pIE0OBWZ4yvNZK" in result

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_payment.return_value = {"payment": SAMPLE_PAYMENT}
        result = await square_payment("Aw4G5pkXn5pIE0OBWZ4yvNZK")
        assert "$29.00 USD" in result

    @pytest.mark.asyncio
    async def test_create_blocked_without_write(self, mock_client: AsyncMock) -> None:
        result = await square_create_payment(source_id="cnon:test", amount=100, currency="USD")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_create(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.create_payment.return_value = {"payment": SAMPLE_PAYMENT}
        result = await square_create_payment(source_id="cnon:test", amount=2900, currency="USD")
        assert "Aw4G5pkXn5pIE0OBWZ4yvNZK" in result

    @pytest.mark.asyncio
    async def test_cancel_requires_confirm(self, mock_client: AsyncMock, write_env: None) -> None:
        result = await square_cancel_payment("p1", confirm=False)
        assert "confirm=true" in result

    @pytest.mark.asyncio
    async def test_cancel_with_confirm(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.cancel_payment.return_value = {"payment": SAMPLE_PAYMENT}
        result = await square_cancel_payment("p1", confirm=True)
        assert "ID: Aw4G5pkXn5pIE0OBWZ4yvNZK" in result


class TestRefunds:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_refunds.return_value = make_list_response([SAMPLE_REFUND], "refunds")
        assert "ref_xyz" in await square_refunds()

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_refund.return_value = {"refund": SAMPLE_REFUND}
        assert "ref_xyz" in await square_refund("ref_xyz")

    @pytest.mark.asyncio
    async def test_create_blocked_without_write(self, mock_client: AsyncMock) -> None:
        result = await square_create_refund(payment_id="p1", amount=100, currency="USD")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_create(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.create_refund.return_value = {"refund": SAMPLE_REFUND}
        result = await square_create_refund(payment_id="p1", amount=1000, currency="USD")
        assert "ref_xyz" in result


class TestCustomers:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_customers.return_value = make_list_response([SAMPLE_CUSTOMER], "customers")
        assert "cust_abc" in await square_customers()

    @pytest.mark.asyncio
    async def test_search(self, mock_client: AsyncMock) -> None:
        mock_client.search_customers.return_value = make_list_response([SAMPLE_CUSTOMER], "customers")
        result = await square_search_customers(query='{"filter":{"email_address":{"exact":"alice@example.com"}}}')
        assert "cust_abc" in result

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_customer.return_value = {"customer": SAMPLE_CUSTOMER}
        assert "Alice Smith" in await square_customer("cust_abc")

    @pytest.mark.asyncio
    async def test_create(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.create_customer.return_value = {"customer": SAMPLE_CUSTOMER}
        result = await square_create_customer(given_name="Alice", email_address="alice@example.com")
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_update(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.update_customer.return_value = {"customer": SAMPLE_CUSTOMER}
        result = await square_update_customer("cust_abc", given_name="Bob")
        assert "cust_abc" in result

    @pytest.mark.asyncio
    async def test_delete_requires_confirm(self, mock_client: AsyncMock, write_env: None) -> None:
        result = await square_delete_customer("cust_abc", confirm=False)
        assert "confirm=true" in result

    @pytest.mark.asyncio
    async def test_delete_with_confirm(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.delete_customer.return_value = {}
        result = await square_delete_customer("cust_abc", confirm=True)
        assert "Deleted customer" in result


class TestCards:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_cards.return_value = make_list_response([SAMPLE_CARD], "cards")
        assert "VISA" in await square_cards()

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_card.return_value = {"card": SAMPLE_CARD}
        assert "Last 4: 4242" in await square_card("card_xyz")

    @pytest.mark.asyncio
    async def test_create(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.create_card.return_value = {"card": SAMPLE_CARD}
        result = await square_create_card(source_id="cnon:test", customer_id="cust_abc")
        assert "card_xyz" in result


class TestLocations:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_locations.return_value = {"locations": [SAMPLE_LOCATION]}
        assert "Main Store" in await square_locations()

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_location.return_value = {"location": SAMPLE_LOCATION}
        assert "Main Store" in await square_location("L1A2B3C4D5")


class TestOrders:
    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_order.return_value = {"order": SAMPLE_ORDER}
        assert "ord_xyz" in await square_order("ord_xyz")

    @pytest.mark.asyncio
    async def test_search(self, mock_client: AsyncMock) -> None:
        mock_client.search_orders.return_value = make_list_response([SAMPLE_ORDER], "orders")
        result = await square_search_orders(location_ids="L1A2B3C4D5")
        assert "ord_xyz" in result


class TestInventory:
    @pytest.mark.asyncio
    async def test_renders(self, mock_client: AsyncMock) -> None:
        mock_client.batch_retrieve_inventory_counts.return_value = {
            "counts": [
                {
                    "catalog_object_id": "c1",
                    "location_id": "L1",
                    "state": "IN_STOCK",
                    "quantity": "10",
                    "calculated_at": "2026-03-15T10:00:00Z",
                }
            ]
        }
        result = await square_inventory(catalog_object_ids="c1", location_ids="L1")
        assert "IN_STOCK" in result


class TestDisputes:
    @pytest.mark.asyncio
    async def test_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_disputes.return_value = make_list_response([SAMPLE_DISPUTE], "disputes")
        assert "disp_xyz" in await square_disputes()

    @pytest.mark.asyncio
    async def test_get(self, mock_client: AsyncMock) -> None:
        mock_client.get_dispute.return_value = {"dispute": SAMPLE_DISPUTE}
        assert "EVIDENCE_REQUIRED" in await square_dispute("disp_xyz")


class TestWebhooks:
    @pytest.mark.asyncio
    async def test_list_subscriptions(self, mock_client: AsyncMock) -> None:
        mock_client.list_webhook_subscriptions.return_value = make_list_response([SAMPLE_WEBHOOK_SUB], "subscriptions")
        assert "wbhk_xyz" in await square_webhook_subscriptions()

    @pytest.mark.asyncio
    async def test_create_subscription(self, mock_client: AsyncMock, write_env: None) -> None:
        mock_client.create_webhook_subscription.return_value = {"subscription": SAMPLE_WEBHOOK_SUB}
        result = await square_create_webhook_subscription(
            name="All",
            notification_url="https://example.com/webhook",
            event_types="payment.created,payment.updated",
        )
        assert "wbhk_xyz" in result

    @pytest.mark.asyncio
    async def test_delete_requires_confirm(self, mock_client: AsyncMock, write_env: None) -> None:
        result = await square_delete_webhook_subscription("wbhk_xyz", confirm=False)
        assert "confirm=true" in result

    @pytest.mark.asyncio
    async def test_event_types(self, mock_client: AsyncMock) -> None:
        mock_client.list_webhook_event_types.return_value = {
            "event_types": ["payment.created"],
            "metadata": [],
        }
        assert "payment.created" in await square_webhook_event_types()

    @pytest.mark.asyncio
    async def test_verify(self, mock_client: AsyncMock) -> None:
        result = await square_verify_webhook(
            raw_body='{"type":"payment.created"}',
            signature="abc=",
            signature_key="secret",
            notification_url="https://example.com/webhook",
        )
        assert "Verified" in result
