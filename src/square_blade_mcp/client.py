"""Square Payments API client.

Async wrapper over ``httpx.AsyncClient`` with typed exceptions, error
classification, and credential scrubbing. No SDK dependency — direct REST
API calls for full control over response shaping and dependency surface.

Square REST conventions:
- All endpoints prefixed ``/v2/``.
- Auth: ``Authorization: Bearer <PAT>`` (OAuth deferred to v0.2.0).
- Pinned ``Square-Version`` header (see models.SQUARE_API_VERSION).
- Pagination: cursor-based; pass ``cursor=...`` in query string for GETs and
  in body for search POSTs. Response body carries ``cursor`` for the next page.
- Errors: ``{"errors": [{category, code, detail, field?}, ...]}``.
- Money: ``{amount: int, currency: str}`` in smallest unit (cents for USD).
- Card data: ``last_4``, ``card_brand``, ``exp_month``, ``exp_year``,
  ``fingerprint`` only — never PAN.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any

import httpx

from square_blade_mcp.models import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SQUARE_API_VERSION,
    scrub_secrets,
    validate_environment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SquareError(Exception):
    """Base exception for Square client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthError(SquareError):
    """Authentication failed — invalid or expired PAT."""


class NotFoundError(SquareError):
    """Requested resource not found."""


class RateLimitError(SquareError):
    """Rate limit exceeded — back off and retry."""


class ValidationError(SquareError):
    """Request validation failed — invalid parameters."""


class ConflictError(SquareError):
    """Conflict — e.g., concurrent modification or duplicate operation."""


class ConnectionError(SquareError):  # noqa: A001
    """Cannot connect to Square API."""


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

_STATUS_TO_ERROR: dict[int, type[SquareError]] = {
    401: AuthError,
    403: AuthError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def _classify_http_error(status_code: int, body: dict[str, Any]) -> SquareError:
    """Map HTTP status code and Square error body to a typed exception."""
    errors = body.get("errors") or []
    if errors and isinstance(errors, list):
        first = errors[0] if isinstance(errors[0], dict) else {}
        category = first.get("category", "")
        code = first.get("code", "")
        detail = first.get("detail", "")
        field = first.get("field", "")
        parts = [p for p in (category, code, detail) if p]
        msg = " | ".join(parts) if parts else f"HTTP {status_code}"
        if field:
            msg += f" (field={field})"
        if len(errors) > 1:
            msg += f" (+{len(errors) - 1} more)"
    else:
        msg = f"HTTP {status_code}"

    message = scrub_secrets(msg)
    exc_cls = _STATUS_TO_ERROR.get(status_code, SquareError)
    return exc_cls(message, status_code=status_code)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SquareClient:
    """Async Square Payments API client.

    Uses ``httpx.AsyncClient`` for direct REST API access. All methods are
    async — no thread wrapping needed.

    Args:
        access_token: Square Personal Access Token. Defaults to ``SQUARE_ACCESS_TOKEN`` env var.
        environment: "sandbox" or "production". Defaults to ``SQUARE_ENVIRONMENT`` env var.
    """

    def __init__(
        self,
        access_token: str | None = None,
        environment: str | None = None,
    ) -> None:
        self._access_token = access_token or os.environ.get("SQUARE_ACCESS_TOKEN", "").strip()
        if not self._access_token:
            raise AuthError("SQUARE_ACCESS_TOKEN environment variable is required.")

        if environment:
            os.environ["SQUARE_ENVIRONMENT"] = environment
        self._base_url = validate_environment()
        self._env_name = os.environ.get("SQUARE_ENVIRONMENT", "").strip().lower()

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Square-Version": SQUARE_API_VERSION,
                "User-Agent": "square-blade-mcp/0.2.0",
            },
            timeout=30.0,
        )

    @property
    def environment(self) -> str:
        """Current environment name."""
        return self._env_name

    @property
    def api_version(self) -> str:
        """Pinned Square API version."""
        return SQUARE_API_VERSION

    # ------------------------------------------------------------------
    # Core HTTP methods
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an HTTP request with error handling and credential scrubbing."""
        if not path.startswith("/v2/"):
            path = f"/v2{path if path.startswith('/') else '/' + path}"
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise ConnectionError(scrub_secrets(str(e))) from e
        except httpx.TimeoutException as e:
            raise ConnectionError(f"Request timed out: {scrub_secrets(str(e))}") from e
        except httpx.HTTPError as e:
            raise SquareError(scrub_secrets(str(e))) from e

        if response.status_code == 204:
            return {}

        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            if response.is_success:
                return {"raw": response.text}
            raise SquareError(
                f"HTTP {response.status_code}: non-JSON response", status_code=response.status_code
            ) from None

        if not response.is_success:
            raise _classify_http_error(response.status_code, body)

        return body  # type: ignore[no-any-return]

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET request with optional query parameters."""
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        return await self._request("GET", path, params=clean_params)

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST request with optional JSON body."""
        clean_body = _clean(body)
        return await self._request("POST", path, json=clean_body)

    async def _put(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """PUT request with optional JSON body."""
        clean_body = _clean(body)
        return await self._request("PUT", path, json=clean_body)

    async def _delete(self, path: str) -> dict[str, Any]:
        """DELETE request."""
        return await self._request("DELETE", path)

    @staticmethod
    def _idempotency_key() -> str:
        """Generate a UUIDv4 idempotency key for write operations."""
        return str(uuid.uuid4())

    @staticmethod
    def _list_params(limit: int, cursor: str | None) -> dict[str, Any]:
        """Build pagination query parameters for GET-list endpoints."""
        params: dict[str, Any] = {"limit": min(limit, MAX_LIMIT)}
        if cursor:
            params["cursor"] = cursor
        return params

    # ==================================================================
    # Payments
    # ==================================================================

    async def list_payments(
        self,
        begin_time: str | None = None,
        end_time: str | None = None,
        sort_order: str | None = None,
        location_id: str | None = None,
        total: int | None = None,
        last_4: str | None = None,
        card_brand: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List payments (cursor paginated)."""
        params = self._list_params(limit, cursor)
        if begin_time:
            params["begin_time"] = begin_time
        if end_time:
            params["end_time"] = end_time
        if sort_order:
            params["sort_order"] = sort_order
        if location_id:
            params["location_id"] = location_id
        if total is not None:
            params["total"] = total
        if last_4:
            params["last_4"] = last_4
        if card_brand:
            params["card_brand"] = card_brand
        return await self._get("/payments", params)

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch a payment by id."""
        return await self._get(f"/payments/{payment_id}")

    async def create_payment(self, body: dict[str, Any]) -> dict[str, Any]:
        """Charge a payment source. ``idempotency_key`` injected if absent."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/payments", body)

    async def cancel_payment(self, payment_id: str) -> dict[str, Any]:
        """Cancel a delayed-capture or authorisation."""
        return await self._post(f"/payments/{payment_id}/cancel")

    async def complete_payment(self, payment_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Capture a previously-authorised payment."""
        return await self._post(f"/payments/{payment_id}/complete", body or {})

    # ==================================================================
    # Refunds
    # ==================================================================

    async def list_refunds(
        self,
        begin_time: str | None = None,
        end_time: str | None = None,
        sort_order: str | None = None,
        location_id: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List refunds (cursor paginated)."""
        params = self._list_params(limit, cursor)
        if begin_time:
            params["begin_time"] = begin_time
        if end_time:
            params["end_time"] = end_time
        if sort_order:
            params["sort_order"] = sort_order
        if location_id:
            params["location_id"] = location_id
        if status:
            params["status"] = status
        if source_type:
            params["source_type"] = source_type
        return await self._get("/refunds", params)

    async def get_refund(self, refund_id: str) -> dict[str, Any]:
        """Fetch a refund by id."""
        return await self._get(f"/refunds/{refund_id}")

    async def create_refund(self, body: dict[str, Any]) -> dict[str, Any]:
        """Refund a payment in full or part. Idempotency key injected if absent."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/refunds", body)

    # ==================================================================
    # Customers
    # ==================================================================

    async def list_customers(
        self,
        sort_field: str | None = None,
        sort_order: str | None = None,
        count: bool | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List customers (cursor paginated)."""
        params = self._list_params(limit, cursor)
        if sort_field:
            params["sort_field"] = sort_field
        if sort_order:
            params["sort_order"] = sort_order
        if count is not None:
            params["count"] = "true" if count else "false"
        return await self._get("/customers", params)

    async def search_customers(self, body: dict[str, Any]) -> dict[str, Any]:
        """Search customers by query (filter/sort in body)."""
        return await self._post("/customers/search", body)

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Fetch a customer by id."""
        return await self._get(f"/customers/{customer_id}")

    async def create_customer(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a customer record."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/customers", body)

    async def update_customer(self, customer_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Update customer fields."""
        return await self._put(f"/customers/{customer_id}", body)

    async def delete_customer(self, customer_id: str) -> dict[str, Any]:
        """Delete a customer (gated)."""
        return await self._delete(f"/customers/{customer_id}")

    # ==================================================================
    # Cards (cards-on-file)
    # ==================================================================

    async def list_cards(
        self,
        customer_id: str | None = None,
        include_disabled: bool | None = None,
        reference_id: str | None = None,
        sort_order: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List saved cards-on-file (no PAN; last_4/brand/exp/fingerprint only)."""
        params = self._list_params(limit, cursor)
        if customer_id:
            params["customer_id"] = customer_id
        if include_disabled is not None:
            params["include_disabled"] = "true" if include_disabled else "false"
        if reference_id:
            params["reference_id"] = reference_id
        if sort_order:
            params["sort_order"] = sort_order
        return await self._get("/cards", params)

    async def get_card(self, card_id: str) -> dict[str, Any]:
        """Fetch a saved card by id."""
        return await self._get(f"/cards/{card_id}")

    async def create_card(self, body: dict[str, Any]) -> dict[str, Any]:
        """Save a card-on-file from a payment source token."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/cards", body)

    async def disable_card(self, card_id: str) -> dict[str, Any]:
        """Disable a saved card (soft; reversible vs delete)."""
        return await self._post(f"/cards/{card_id}/disable")

    # ==================================================================
    # Locations
    # ==================================================================

    async def list_locations(self) -> dict[str, Any]:
        """List merchant locations."""
        return await self._get("/locations")

    async def get_location(self, location_id: str) -> dict[str, Any]:
        """Fetch a single location by id."""
        return await self._get(f"/locations/{location_id}")

    # ==================================================================
    # Orders
    # ==================================================================

    async def create_order(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create an order."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/orders", body)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Fetch an order by id."""
        return await self._get(f"/orders/{order_id}")

    async def search_orders(self, body: dict[str, Any]) -> dict[str, Any]:
        """Search orders with filter/sort/location_ids in body."""
        return await self._post("/orders/search", body)

    async def update_order(self, order_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Update an order (line items, fulfilment, metadata)."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._put(f"/orders/{order_id}", body)

    async def pay_order(self, order_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Pay an existing order using one or more payment sources."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post(f"/orders/{order_id}/pay", body)

    # ==================================================================
    # Catalog
    # ==================================================================

    async def list_catalog(
        self,
        types: str | None = None,
        catalog_version: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List catalog objects (optionally filter by comma-separated types)."""
        params: dict[str, Any] = {}
        if types:
            params["types"] = types
        if catalog_version is not None:
            params["catalog_version"] = catalog_version
        if cursor:
            params["cursor"] = cursor
        return await self._get("/catalog/list", params)

    async def get_catalog_object(
        self,
        object_id: str,
        include_related_objects: bool | None = None,
        catalog_version: int | None = None,
    ) -> dict[str, Any]:
        """Fetch a catalog object by id."""
        params: dict[str, Any] = {}
        if include_related_objects is not None:
            params["include_related_objects"] = "true" if include_related_objects else "false"
        if catalog_version is not None:
            params["catalog_version"] = catalog_version
        return await self._get(f"/catalog/object/{object_id}", params or None)

    # ==================================================================
    # Inventory
    # ==================================================================

    async def batch_retrieve_inventory_counts(self, body: dict[str, Any]) -> dict[str, Any]:
        """Batch-retrieve inventory counts for catalog objects/locations."""
        return await self._post("/inventory/counts/batch-retrieve", body)

    # ==================================================================
    # Disputes
    # ==================================================================

    async def list_disputes(
        self,
        states: str | None = None,
        location_id: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List disputes (chargebacks)."""
        params: dict[str, Any] = {}
        if states:
            params["states"] = states
        if location_id:
            params["location_id"] = location_id
        if cursor:
            params["cursor"] = cursor
        return await self._get("/disputes", params)

    async def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Fetch a dispute by id."""
        return await self._get(f"/disputes/{dispute_id}")

    # ==================================================================
    # Subscriptions (billing-v1)
    # ==================================================================

    async def search_subscriptions(self, body: dict[str, Any]) -> dict[str, Any]:
        """Search subscriptions (filter by location/customer/plan/status)."""
        return await self._post("/subscriptions/search", body)

    async def get_subscription(
        self,
        subscription_id: str,
        include: str | None = None,
    ) -> dict[str, Any]:
        """Get a subscription by id (optional include=actions)."""
        params: dict[str, Any] = {}
        if include:
            params["include"] = include
        return await self._get(f"/subscriptions/{subscription_id}", params or None)

    async def create_subscription(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a subscription. Idempotency key auto-injected."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/subscriptions", body)

    async def update_subscription(
        self,
        subscription_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a subscription (PUT)."""
        return await self._put(f"/subscriptions/{subscription_id}", body)

    async def cancel_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Cancel a subscription at the end of the current billing period."""
        return await self._post(f"/subscriptions/{subscription_id}/cancel")

    async def pause_subscription(
        self,
        subscription_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Schedule a PAUSE action on a subscription."""
        action: dict[str, Any] = {"type": "PAUSE"}
        if body:
            action.update(body)
        payload: dict[str, Any] = {
            "action": action,
            "idempotency_key": self._idempotency_key(),
        }
        return await self._post(f"/subscriptions/{subscription_id}/actions", payload)

    async def resume_subscription(
        self,
        subscription_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Schedule a RESUME action on a subscription."""
        action: dict[str, Any] = {"type": "RESUME"}
        if body:
            action.update(body)
        payload: dict[str, Any] = {
            "action": action,
            "idempotency_key": self._idempotency_key(),
        }
        return await self._post(f"/subscriptions/{subscription_id}/actions", payload)

    # ------------------------------------------------------------------
    # Subscription plans (Catalog API: SUBSCRIPTION_PLAN / SUBSCRIPTION_PLAN_VARIATION)
    # ------------------------------------------------------------------

    async def list_subscription_plans(
        self,
        cursor: str | None = None,
        catalog_version: int | None = None,
    ) -> dict[str, Any]:
        """List subscription plans via the Catalog API."""
        return await self.list_catalog(
            types="SUBSCRIPTION_PLAN",
            catalog_version=catalog_version,
            cursor=cursor,
        )

    async def get_subscription_plan(
        self,
        plan_id: str,
        include_related_objects: bool | None = None,
    ) -> dict[str, Any]:
        """Get a subscription plan via the Catalog API."""
        return await self.get_catalog_object(
            plan_id,
            include_related_objects=include_related_objects,
        )

    async def create_subscription_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a subscription plan via the Catalog upsert endpoint.

        Body shape::

            {
                "object": {
                    "type": "SUBSCRIPTION_PLAN",
                    "id": "#new-plan",
                    "subscription_plan_data": {
                        "name": "Pro Plan",
                        "phases": [...]
                    }
                }
            }
        """
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/catalog/object", body)

    # ==================================================================
    # Invoices (billing-v1)
    # ==================================================================

    async def search_invoices(self, body: dict[str, Any]) -> dict[str, Any]:
        """Search invoices (location_ids required in query.filter)."""
        return await self._post("/invoices/search", body)

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Get an invoice by id."""
        return await self._get(f"/invoices/{invoice_id}")

    async def create_invoice(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create an invoice in DRAFT state. Idempotency key auto-injected."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/invoices", body)

    async def publish_invoice(self, invoice_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Publish (send) an invoice. Body must carry ``version`` and
        ``idempotency_key``."""
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post(f"/invoices/{invoice_id}/publish", body)

    async def cancel_invoice(self, invoice_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Cancel an invoice. Body must carry ``version``."""
        return await self._post(f"/invoices/{invoice_id}/cancel", body)

    # ==================================================================
    # Webhook subscriptions + event types
    # ==================================================================

    async def list_webhook_subscriptions(
        self,
        include_disabled: bool | None = None,
        sort_order: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List webhook subscriptions."""
        params = self._list_params(limit, cursor)
        if include_disabled is not None:
            params["include_disabled"] = "true" if include_disabled else "false"
        if sort_order:
            params["sort_order"] = sort_order
        return await self._get("/webhooks/subscriptions", params)

    async def create_webhook_subscription(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a webhook subscription. Body shape::

        {"subscription": {"name": "...", "event_types": [...], "notification_url": "..."}}
        """
        if "idempotency_key" not in body:
            body = {**body, "idempotency_key": self._idempotency_key()}
        return await self._post("/webhooks/subscriptions", body)

    async def delete_webhook_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Delete a webhook subscription (gated)."""
        return await self._delete(f"/webhooks/subscriptions/{subscription_id}")

    async def list_webhook_event_types(self, api_version: str | None = None) -> dict[str, Any]:
        """List event types available for webhook subscriptions."""
        params: dict[str, Any] = {}
        if api_version:
            params["api_version"] = api_version
        return await self._get("/webhooks/event-types", params or None)

    # ==================================================================
    # Webhook signature verification
    # ==================================================================

    @staticmethod
    def verify_webhook_signature(
        raw_body: str,
        signature_header: str,
        webhook_signature_key: str,
        notification_url: str,
    ) -> dict[str, Any]:
        """Verify a Square webhook HMAC-SHA256 signature and parse the event.

        Square signs ``notification_url + raw_body`` with the subscription's
        ``signature_key`` and returns the result as base64. The signature
        arrives in the ``x-square-hmacsha256-signature`` header.

        Args:
            raw_body: The exact raw HTTP request body bytes-as-str.
            signature_header: Value of ``x-square-hmacsha256-signature``.
            webhook_signature_key: Subscription signature key.
            notification_url: The URL Square posted the webhook to. **Must match
                exactly what was registered**, including scheme, host, port, and path.

        Returns:
            ``{"verified": bool, "event": {...} | None, "error"?: str}``.
            On success, ``event`` carries ``{event_type, event_id, created_at, data}``.
        """
        try:
            payload = (notification_url + raw_body).encode("utf-8")
            digest = hmac.new(
                webhook_signature_key.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(digest).decode("ascii")

            if not hmac.compare_digest(expected, signature_header.strip()):
                return {"verified": False, "event": None, "error": "Signature mismatch"}

            event = json.loads(raw_body)
            parsed = {
                "event_type": event.get("type") or event.get("event_type"),
                "event_id": event.get("event_id"),
                "merchant_id": event.get("merchant_id"),
                "location_id": event.get("location_id"),
                "created_at": event.get("created_at"),
                "data": event.get("data"),
            }
            return {"verified": True, "event": parsed}
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return {"verified": False, "event": None, "error": scrub_secrets(str(e))}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean(body: dict[str, Any] | None) -> dict[str, Any]:
    """Drop top-level None values from a request body (Square is strict on nulls)."""
    if not body:
        return {}
    return {k: v for k, v in body.items() if v is not None}
