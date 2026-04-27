"""Tests for formatters.py — token-efficient output formatting."""

from __future__ import annotations

from square_blade_mcp.formatters import (
    format_card_detail,
    format_card_list,
    format_catalog_detail,
    format_catalog_list,
    format_customer_detail,
    format_customer_list,
    format_date,
    format_datetime,
    format_dispute_detail,
    format_dispute_list,
    format_event_type_list,
    format_info,
    format_inventory_counts,
    format_invoice_detail,
    format_invoice_list,
    format_location_detail,
    format_location_list,
    format_order_detail,
    format_order_list,
    format_pagination,
    format_payment_detail,
    format_payment_list,
    format_refund_detail,
    format_refund_list,
    format_subscription_detail,
    format_subscription_list,
    format_subscription_plan_list,
    format_webhook_subscription_detail,
    format_webhook_subscription_list,
    format_webhook_verification,
    select_fields,
)
from tests.conftest import (
    SAMPLE_CARD,
    SAMPLE_CUSTOMER,
    SAMPLE_DISPUTE,
    SAMPLE_INVOICE,
    SAMPLE_LOCATION,
    SAMPLE_ORDER,
    SAMPLE_PAYMENT,
    SAMPLE_REFUND,
    SAMPLE_SUBSCRIPTION,
    SAMPLE_SUBSCRIPTION_PLAN,
    SAMPLE_WEBHOOK_SUB,
    make_list_response,
)


class TestDateHelpers:
    def test_format_datetime(self) -> None:
        assert format_datetime("2026-03-15T14:30:00Z") == "2026-03-15 14:30"

    def test_format_datetime_with_offset(self) -> None:
        assert format_datetime("2026-03-15T14:30:00+00:00") == "2026-03-15 14:30"

    def test_format_datetime_none(self) -> None:
        assert format_datetime(None) == "?"

    def test_format_date(self) -> None:
        assert format_date("2026-03-15T14:30:00Z") == "2026-03-15"

    def test_format_date_none(self) -> None:
        assert format_date(None) == "?"


class TestSelectFields:
    def test_returns_all_when_none(self) -> None:
        d = {"id": "x", "name": "y", "status": "z"}
        assert select_fields(d, None) == d

    def test_filters_to_requested(self) -> None:
        d = {"id": "x", "name": "y", "status": "z"}
        assert select_fields(d, "name") == {"id": "x", "name": "y"}

    def test_always_keeps_id(self) -> None:
        d = {"id": "x", "name": "y"}
        assert "id" in select_fields(d, "name")


class TestPagination:
    def test_no_cursor(self) -> None:
        assert format_pagination({"payments": []}, 0) == ""

    def test_with_cursor(self) -> None:
        out = format_pagination({"payments": [], "cursor": "next-cursor-xyz"}, 5)
        assert "next-cursor-xyz" in out
        assert "more" in out


class TestPaymentList:
    def test_empty(self) -> None:
        assert "No payments" in format_payment_list({"payments": []})

    def test_renders(self) -> None:
        out = format_payment_list(make_list_response([SAMPLE_PAYMENT], "payments"))
        assert "Aw4G5pkXn5pIE0OBWZ4yvNZK" in out
        assert "$29.00 USD" in out
        assert "COMPLETED" in out
        assert "loc=L1A2B3C4D5" in out

    def test_pagination_hint(self) -> None:
        out = format_payment_list(make_list_response([SAMPLE_PAYMENT], "payments", cursor="next-x"))
        assert "next-x" in out


class TestPaymentDetail:
    def test_renders(self) -> None:
        out = format_payment_detail(SAMPLE_PAYMENT)
        assert "ID: Aw4G5pkXn5pIE0OBWZ4yvNZK" in out
        assert "Status: COMPLETED" in out
        assert "$29.00 USD" in out
        assert "VISA ****4242" in out
        assert "exp 12/2028" in out


class TestRefundList:
    def test_empty(self) -> None:
        assert "No refunds" in format_refund_list({"refunds": []})

    def test_renders(self) -> None:
        out = format_refund_list(make_list_response([SAMPLE_REFUND], "refunds"))
        assert "ref_xyz" in out
        assert "$10.00 USD" in out
        assert "reason=Customer request" in out


class TestRefundDetail:
    def test_renders(self) -> None:
        out = format_refund_detail(SAMPLE_REFUND)
        assert "ID: ref_xyz" in out
        assert "Payment: Aw4G5pkXn5pIE0OBWZ4yvNZK" in out


class TestCustomerList:
    def test_empty(self) -> None:
        assert "No customers" in format_customer_list({"customers": []})

    def test_renders(self) -> None:
        out = format_customer_list(make_list_response([SAMPLE_CUSTOMER], "customers"))
        assert "cust_abc" in out
        assert "alice@example.com" in out
        assert "Alice Smith" in out


class TestCustomerDetail:
    def test_renders(self) -> None:
        out = format_customer_detail(SAMPLE_CUSTOMER)
        assert "Name: Alice Smith" in out
        assert "Email: alice@example.com" in out
        assert "Reference: internal_42" in out


class TestCardList:
    def test_renders(self) -> None:
        out = format_card_list(make_list_response([SAMPLE_CARD], "cards"))
        assert "VISA ****4242" in out
        assert "exp 12/2028" in out
        assert "cust=cust_abc" in out

    def test_disabled(self) -> None:
        disabled = {**SAMPLE_CARD, "enabled": False}
        out = format_card_list(make_list_response([disabled], "cards"))
        assert "disabled" in out


class TestCardDetail:
    def test_renders(self) -> None:
        out = format_card_detail(SAMPLE_CARD)
        assert "Brand: VISA" in out
        assert "Last 4: 4242" in out
        assert "Expiry: 12/2028" in out
        assert "Fingerprint: sq-1-fingerprint" in out


class TestLocationList:
    def test_renders(self) -> None:
        out = format_location_list({"locations": [SAMPLE_LOCATION]})
        assert "L1A2B3C4D5" in out
        assert "Main Store" in out


class TestLocationDetail:
    def test_renders(self) -> None:
        out = format_location_detail(SAMPLE_LOCATION)
        assert "Name: Main Store" in out
        assert "1 Market St" in out


class TestOrderList:
    def test_renders(self) -> None:
        out = format_order_list(make_list_response([SAMPLE_ORDER], "orders"))
        assert "ord_xyz" in out
        assert "$29.00 USD" in out
        assert "1 items" in out


class TestOrderDetail:
    def test_renders(self) -> None:
        out = format_order_detail(SAMPLE_ORDER)
        assert "ID: ord_xyz" in out
        assert "Total: $29.00 USD" in out
        assert "Pro Plan" in out


class TestCatalog:
    def test_list(self) -> None:
        objs = [
            {"id": "c1", "type": "ITEM", "item_data": {"name": "Coffee"}},
            {"id": "c2", "type": "CATEGORY", "category_data": {"name": "Drinks"}},
        ]
        out = format_catalog_list({"objects": objs})
        assert "Coffee" in out
        assert "Drinks" in out
        assert "ITEM" in out

    def test_detail(self) -> None:
        out = format_catalog_detail({"object": {"id": "c1", "type": "ITEM", "item_data": {"name": "Coffee"}}})
        assert "Coffee" in out


class TestInventory:
    def test_renders(self) -> None:
        resp = {
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
        out = format_inventory_counts(resp)
        assert "IN_STOCK" in out
        assert "qty=10" in out


class TestDisputes:
    def test_list(self) -> None:
        out = format_dispute_list(make_list_response([SAMPLE_DISPUTE], "disputes"))
        assert "disp_xyz" in out
        assert "EVIDENCE_REQUIRED" in out
        assert "due 2026-04-01" in out

    def test_detail(self) -> None:
        out = format_dispute_detail(SAMPLE_DISPUTE)
        assert "Reason: NOT_AS_DESCRIBED" in out


class TestWebhookSubscription:
    def test_list(self) -> None:
        out = format_webhook_subscription_list(make_list_response([SAMPLE_WEBHOOK_SUB], "subscriptions"))
        assert "wbhk_xyz" in out
        assert "https://example.com/webhook" in out
        assert "3 events" in out

    def test_detail_hides_signature_key(self) -> None:
        out = format_webhook_subscription_detail(SAMPLE_WEBHOOK_SUB)
        assert "secret_should_be_hidden" not in out
        assert "**** (hidden)" in out


class TestEventTypes:
    def test_renders(self) -> None:
        resp = {"event_types": ["payment.created", "payment.updated"], "metadata": []}
        out = format_event_type_list(resp)
        assert "payment.created" in out
        assert "payment.updated" in out


class TestWebhookVerification:
    def test_valid(self) -> None:
        out = format_webhook_verification(
            {
                "verified": True,
                "event": {
                    "event_type": "payment.created",
                    "event_id": "evt_x",
                    "merchant_id": "M",
                    "created_at": "2026-03-15T10:00:00Z",
                },
            }
        )
        assert "Verified" in out
        assert "payment.created" in out

    def test_invalid(self) -> None:
        out = format_webhook_verification({"verified": False, "error": "Signature mismatch"})
        assert "Invalid" in out


class TestInfo:
    def test_renders(self) -> None:
        out = format_info("sandbox", "2024-12-18", False)
        assert "sandbox" in out
        assert "2024-12-18" in out
        assert "disabled" in out


class TestSubscriptionFormatters:
    def test_list_renders(self) -> None:
        response = {"subscriptions": [SAMPLE_SUBSCRIPTION], "cursor": "next"}
        out = format_subscription_list(response, limit=5)
        assert "sub_xyz" in out
        assert "ACTIVE" in out
        assert "plan=plan_var_pro" in out
        assert "more" in out  # pagination hint

    def test_list_empty(self) -> None:
        assert "No subscriptions" in format_subscription_list({"subscriptions": []})

    def test_detail_renders(self) -> None:
        out = format_subscription_detail(SAMPLE_SUBSCRIPTION)
        assert "ID: sub_xyz" in out
        assert "Status: ACTIVE" in out
        assert "Plan: plan_var_pro" in out
        assert "Customer: cust_abc" in out
        assert "Invoices: 2" in out
        assert "PAUSE" in out  # action listed

    def test_detail_field_select(self) -> None:
        out = format_subscription_detail(SAMPLE_SUBSCRIPTION, fields="status")
        assert "Status: ACTIVE" in out
        assert "Customer:" not in out

    def test_plan_list_renders(self) -> None:
        response = {"objects": [SAMPLE_SUBSCRIPTION_PLAN]}
        out = format_subscription_plan_list(response)
        assert "plan_pro" in out
        assert "Pro Plan" in out
        assert "1 phases" in out

    def test_plan_list_empty(self) -> None:
        assert "No subscription plans" in format_subscription_plan_list({"objects": []})


class TestInvoiceFormatters:
    def test_list_renders(self) -> None:
        response = {"invoices": [SAMPLE_INVOICE]}
        out = format_invoice_list(response)
        assert "inv_1" in out
        assert "DRAFT" in out
        assert "INV-001" in out
        assert "$29.00 USD" in out

    def test_list_empty(self) -> None:
        assert "No invoices" in format_invoice_list({"invoices": []})

    def test_detail_renders(self) -> None:
        out = format_invoice_detail(SAMPLE_INVOICE)
        assert "ID: inv_1" in out
        assert "Status: DRAFT" in out
        assert "Invoice Number: INV-001" in out
        assert "April Subscription" in out
        assert "Recipient: cust_abc <alice@example.com>" in out
        assert "BALANCE" in out
        assert "$29.00 USD" in out
        assert "Public URL:" in out

    def test_detail_field_select(self) -> None:
        out = format_invoice_detail(SAMPLE_INVOICE, fields="status")
        assert "Status: DRAFT" in out
        assert "Invoice Number" not in out
