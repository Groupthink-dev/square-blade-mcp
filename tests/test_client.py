"""Tests for client.py — SquareClient, error hierarchy, webhook verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from square_blade_mcp.client import (
    AuthError,
    ConflictError,
    ConnectionError,
    NotFoundError,
    RateLimitError,
    SquareClient,
    SquareError,
    ValidationError,
    _classify_http_error,
)


class TestClientConstruction:
    def test_requires_access_token(self) -> None:
        with pytest.raises(AuthError, match="SQUARE_ACCESS_TOKEN"):
            SquareClient()

    def test_requires_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ACCESS_TOKEN", "EAAAtest")
        with pytest.raises(ValueError, match="SQUARE_ENVIRONMENT"):
            SquareClient()

    def test_creates_with_env(self, sandbox_env: None) -> None:
        client = SquareClient()
        assert client.environment == "sandbox"
        assert client.api_version  # pinned

    def test_creates_with_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "sandbox")
        client = SquareClient(access_token="EAAAtest")
        assert client.environment == "sandbox"


class TestErrorClassification:
    def test_401_is_auth(self) -> None:
        err = _classify_http_error(
            401, {"errors": [{"category": "AUTHENTICATION_ERROR", "code": "UNAUTHORIZED", "detail": "bad token"}]}
        )
        assert isinstance(err, AuthError)

    def test_404_is_not_found(self) -> None:
        err = _classify_http_error(404, {"errors": [{"category": "INVALID_REQUEST_ERROR", "code": "NOT_FOUND"}]})
        assert isinstance(err, NotFoundError)

    def test_409_is_conflict(self) -> None:
        err = _classify_http_error(409, {"errors": [{"code": "IDEMPOTENCY_KEY_REUSED"}]})
        assert isinstance(err, ConflictError)

    def test_422_is_validation(self) -> None:
        err = _classify_http_error(
            422, {"errors": [{"code": "INVALID_VALUE", "detail": "bad amount", "field": "amount_money.amount"}]}
        )
        assert isinstance(err, ValidationError)
        assert "field=amount_money.amount" in str(err)

    def test_429_is_rate_limit(self) -> None:
        err = _classify_http_error(429, {"errors": [{"code": "RATE_LIMITED"}]})
        assert isinstance(err, RateLimitError)

    def test_500_is_base(self) -> None:
        err = _classify_http_error(500, {"errors": [{"code": "INTERNAL_ERROR", "detail": "oops"}]})
        assert isinstance(err, SquareError)
        assert not isinstance(err, AuthError)

    def test_multiple_errors_summarised(self) -> None:
        err = _classify_http_error(
            422,
            {
                "errors": [
                    {"code": "INVALID_VALUE", "detail": "bad a"},
                    {"code": "INVALID_VALUE", "detail": "bad b"},
                    {"code": "INVALID_VALUE", "detail": "bad c"},
                ]
            },
        )
        assert "+2 more" in str(err)

    def test_scrubs_secrets_in_error(self) -> None:
        err = _classify_http_error(401, {"errors": [{"code": "UNAUTHORIZED", "detail": "token EAAAleak123 invalid"}]})
        assert "EAAA" not in str(err)


@pytest.fixture
def client(sandbox_env: None) -> SquareClient:
    return SquareClient()


class TestHttpMethods:
    @pytest.mark.asyncio
    async def test_get_success(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payments": [{"id": "p1"}]}, request=httpx.Request("GET", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client._get("/payments")
            assert result["payments"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_get_auto_prefixes_v2(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={}, request=httpx.Request("GET", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client._get("/payments")
            args, _ = mock_req.call_args
            assert args[1] == "/v2/payments"

    @pytest.mark.asyncio
    async def test_get_filters_none_params(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={}, request=httpx.Request("GET", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client._get("/payments", {"location_id": "L1", "total": None})
            _, kwargs = mock_req.call_args
            assert kwargs["params"] == {"location_id": "L1"}

    @pytest.mark.asyncio
    async def test_post_success(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payment": {"id": "p1"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client._post("/payments", {"amount_money": {"amount": 100, "currency": "USD"}})
            assert result["payment"]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_delete_204(self, client: SquareClient) -> None:
        mock_response = httpx.Response(204, request=httpx.Request("DELETE", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response):
            assert await client._delete("/customers/cust_x") == {}

    @pytest.mark.asyncio
    async def test_error_response(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            404,
            json={"errors": [{"code": "NOT_FOUND", "detail": "Payment not found"}]},
            request=httpx.Request("GET", "https://test"),
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(NotFoundError):
                await client._get("/payments/missing")

    @pytest.mark.asyncio
    async def test_connection_error(self, client: SquareClient) -> None:
        with patch.object(
            client._http,
            "request",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ConnectionError):
                await client._get("/payments")

    @pytest.mark.asyncio
    async def test_timeout_error(self, client: SquareClient) -> None:
        with patch.object(client._http, "request", new_callable=AsyncMock, side_effect=httpx.ReadTimeout("slow")):
            with pytest.raises(ConnectionError, match="timed out"):
                await client._get("/payments")


class TestResourceMethods:
    @pytest.mark.asyncio
    async def test_list_payments(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"payments": []}, request=httpx.Request("GET", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.list_payments(location_id="L1", limit=10)
            args, kwargs = mock_req.call_args
            assert args[0] == "GET"
            assert "/v2/payments" in args[1]
            assert kwargs["params"]["location_id"] == "L1"
            assert kwargs["params"]["limit"] == 10

    @pytest.mark.asyncio
    async def test_get_payment(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payment": {"id": "p1"}}, request=httpx.Request("GET", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.get_payment("p1")
            args, _ = mock_req.call_args
            assert "/v2/payments/p1" in args[1]

    @pytest.mark.asyncio
    async def test_create_payment_auto_idempotency(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payment": {"id": "p1"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.create_payment({"source_id": "cnon:test", "amount_money": {"amount": 100, "currency": "USD"}})
            _, kwargs = mock_req.call_args
            assert "idempotency_key" in kwargs["json"]
            assert len(kwargs["json"]["idempotency_key"]) >= 32

    @pytest.mark.asyncio
    async def test_create_payment_preserves_caller_idempotency(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payment": {"id": "p1"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.create_payment(
                {
                    "source_id": "cnon:test",
                    "amount_money": {"amount": 100, "currency": "USD"},
                    "idempotency_key": "caller-key-123",
                }
            )
            _, kwargs = mock_req.call_args
            assert kwargs["json"]["idempotency_key"] == "caller-key-123"

    @pytest.mark.asyncio
    async def test_cancel_payment(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"payment": {"id": "p1", "status": "CANCELED"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.cancel_payment("p1")
            args, _ = mock_req.call_args
            assert args[0] == "POST"
            assert "/v2/payments/p1/cancel" in args[1]

    @pytest.mark.asyncio
    async def test_search_orders(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"orders": []}, request=httpx.Request("POST", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.search_orders({"location_ids": ["L1"], "limit": 10})
            args, kwargs = mock_req.call_args
            assert args[0] == "POST"
            assert "/v2/orders/search" in args[1]
            assert kwargs["json"]["location_ids"] == ["L1"]

    @pytest.mark.asyncio
    async def test_update_customer_uses_put(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"customer": {"id": "c1"}}, request=httpx.Request("PUT", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.update_customer("c1", {"given_name": "Alice"})
            args, _ = mock_req.call_args
            assert args[0] == "PUT"
            assert "/v2/customers/c1" in args[1]

    @pytest.mark.asyncio
    async def test_delete_customer(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={}, request=httpx.Request("DELETE", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.delete_customer("c1")
            args, _ = mock_req.call_args
            assert args[0] == "DELETE"
            assert "/v2/customers/c1" in args[1]

    @pytest.mark.asyncio
    async def test_list_cards(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"cards": []}, request=httpx.Request("GET", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.list_cards(customer_id="c1", include_disabled=False)
            _, kwargs = mock_req.call_args
            assert kwargs["params"]["customer_id"] == "c1"
            assert kwargs["params"]["include_disabled"] == "false"


class TestSubscriptionsClient:
    @pytest.mark.asyncio
    async def test_search_subscriptions(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"subscriptions": []}, request=httpx.Request("POST", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.search_subscriptions({"limit": 5})
            args, _ = mock_req.call_args
            assert args[0] == "POST"
            assert "/v2/subscriptions/search" in args[1]

    @pytest.mark.asyncio
    async def test_get_subscription_with_include(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"subscription": {"id": "sub_xyz"}}, request=httpx.Request("GET", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.get_subscription("sub_xyz", include="actions")
            args, kwargs = mock_req.call_args
            assert "/v2/subscriptions/sub_xyz" in args[1]
            assert kwargs["params"]["include"] == "actions"

    @pytest.mark.asyncio
    async def test_create_subscription_auto_idempotency(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"subscription": {"id": "sub_x"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.create_subscription({"location_id": "L1", "customer_id": "c1", "plan_variation_id": "pv"})
            _, kwargs = mock_req.call_args
            assert "idempotency_key" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_update_subscription_uses_put(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"subscription": {"id": "sub_x"}}, request=httpx.Request("PUT", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.update_subscription("sub_x", {"subscription": {"price_override_money": None}})
            args, _ = mock_req.call_args
            assert args[0] == "PUT"
            assert "/v2/subscriptions/sub_x" in args[1]

    @pytest.mark.asyncio
    async def test_cancel_subscription(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"subscription": {"id": "sub_x"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.cancel_subscription("sub_x")
            args, _ = mock_req.call_args
            assert args[0] == "POST"
            assert "/v2/subscriptions/sub_x/cancel" in args[1]

    @pytest.mark.asyncio
    async def test_pause_subscription_action(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"actions": [{"type": "PAUSE"}]}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.pause_subscription("sub_x", {"effective_date": "2026-05-01"})
            args, kwargs = mock_req.call_args
            assert "/v2/subscriptions/sub_x/actions" in args[1]
            assert kwargs["json"]["action"]["type"] == "PAUSE"
            assert kwargs["json"]["action"]["effective_date"] == "2026-05-01"
            assert "idempotency_key" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_resume_subscription_action(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"actions": [{"type": "RESUME"}]}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.resume_subscription("sub_x")
            _, kwargs = mock_req.call_args
            assert kwargs["json"]["action"]["type"] == "RESUME"

    @pytest.mark.asyncio
    async def test_list_subscription_plans_uses_catalog(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"objects": []}, request=httpx.Request("GET", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.list_subscription_plans()
            args, kwargs = mock_req.call_args
            assert "/v2/catalog/list" in args[1]
            assert kwargs["params"]["types"] == "SUBSCRIPTION_PLAN"

    @pytest.mark.asyncio
    async def test_create_subscription_plan_auto_idempotency(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200,
            json={"catalog_object": {"id": "plan_x", "type": "SUBSCRIPTION_PLAN"}},
            request=httpx.Request("POST", "https://test"),
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.create_subscription_plan(
                {
                    "object": {
                        "type": "SUBSCRIPTION_PLAN",
                        "id": "#new",
                        "subscription_plan_data": {"name": "Pro", "phases": []},
                    }
                }
            )
            args, kwargs = mock_req.call_args
            assert "/v2/catalog/object" in args[1]
            assert "idempotency_key" in kwargs["json"]


class TestInvoicesClient:
    @pytest.mark.asyncio
    async def test_search_invoices(self, client: SquareClient) -> None:
        mock_response = httpx.Response(200, json={"invoices": []}, request=httpx.Request("POST", "https://test"))
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.search_invoices({"query": {"filter": {"location_ids": ["L1"]}}, "limit": 5})
            args, kwargs = mock_req.call_args
            assert args[0] == "POST"
            assert "/v2/invoices/search" in args[1]

    @pytest.mark.asyncio
    async def test_get_invoice(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"invoice": {"id": "inv_1"}}, request=httpx.Request("GET", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.get_invoice("inv_1")
            args, _ = mock_req.call_args
            assert "/v2/invoices/inv_1" in args[1]

    @pytest.mark.asyncio
    async def test_create_invoice_auto_idempotency(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"invoice": {"id": "inv_1"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.create_invoice({"invoice": {"order_id": "ord_x"}})
            _, kwargs = mock_req.call_args
            assert "idempotency_key" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_publish_invoice(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"invoice": {"id": "inv_1", "status": "UNPAID"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.publish_invoice("inv_1", {"version": 0})
            args, kwargs = mock_req.call_args
            assert "/v2/invoices/inv_1/publish" in args[1]
            assert kwargs["json"]["version"] == 0
            assert "idempotency_key" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_cancel_invoice(self, client: SquareClient) -> None:
        mock_response = httpx.Response(
            200, json={"invoice": {"id": "inv_1", "status": "CANCELED"}}, request=httpx.Request("POST", "https://test")
        )
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            await client.cancel_invoice("inv_1", {"version": 1})
            args, kwargs = mock_req.call_args
            assert "/v2/invoices/inv_1/cancel" in args[1]
            assert kwargs["json"]["version"] == 1


class TestWebhookVerification:
    def _sign(self, body: str, secret: str, url: str) -> str:
        digest = hmac.new((secret).encode(), (url + body).encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def test_valid_signature(self) -> None:
        url = "https://example.com/webhook"
        body = json.dumps(
            {
                "type": "payment.created",
                "event_id": "evt_123",
                "merchant_id": "MERCH_X",
                "created_at": "2026-03-15T14:30:00Z",
                "data": {"id": "p1"},
            }
        )
        secret = "wbhk_secret_xyz"
        sig = self._sign(body, secret, url)
        result = SquareClient.verify_webhook_signature(body, sig, secret, url)
        assert result["verified"] is True
        assert result["event"]["event_type"] == "payment.created"
        assert result["event"]["event_id"] == "evt_123"
        assert result["event"]["merchant_id"] == "MERCH_X"

    def test_invalid_signature(self) -> None:
        result = SquareClient.verify_webhook_signature("{}", "abc=", "secret", "https://example.com/webhook")
        assert result["verified"] is False
        assert "mismatch" in result.get("error", "").lower()

    def test_url_mismatch_fails(self) -> None:
        url_signed = "https://example.com/webhook"
        url_received = "https://attacker.com/webhook"
        body = '{"type":"payment.created"}'
        secret = "secret"
        sig = self._sign(body, secret, url_signed)
        result = SquareClient.verify_webhook_signature(body, sig, secret, url_received)
        assert result["verified"] is False

    def test_malformed_body_fails_after_verify(self) -> None:
        url = "https://example.com/webhook"
        secret = "secret"
        body = "not-json"
        sig = self._sign(body, secret, url)
        result = SquareClient.verify_webhook_signature(body, sig, secret, url)
        # Signature verifies, body parse fails
        assert result["verified"] is False
        assert result.get("error")
