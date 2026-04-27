"""Token-efficient output formatters for Square Payments data.

Design principles:
- One line per item in lists
- Pipe-delimited fields
- Null fields omitted
- Money in human-readable format ($29.00 USD)
- Card data is PCI-safe — last_4/brand/exp only, never PAN
- Cursor pagination hint at end of list output

Square list responses use a typed key (``payments``, ``customers``, ``cards``,
``locations``, ``orders``, ``objects``, ``disputes``, ``subscriptions``,
``refunds``, ``related_objects``). Pagination is a top-level ``cursor`` field.
"""

from __future__ import annotations

from typing import Any

from square_blade_mcp.models import DEFAULT_LIMIT, format_square_money

# ---------------------------------------------------------------------------
# Date / response helpers
# ---------------------------------------------------------------------------


def format_datetime(iso_str: str | None) -> str:
    """Format ISO datetime to short form: '2026-03-15T14:30:00Z' -> '2026-03-15 14:30'."""
    if not iso_str:
        return "?"
    clean = iso_str.replace("Z", "").replace("+00:00", "")
    return clean[:16].replace("T", " ")


def format_date(iso_str: str | None) -> str:
    """Format ISO datetime to date only: '2026-03-15T14:30:00Z' -> '2026-03-15'."""
    if not iso_str:
        return "?"
    return iso_str[:10]


def select_fields(data: dict[str, Any], fields: str | None) -> dict[str, Any]:
    """Filter dict to only requested comma-separated fields. Always keeps ``id``."""
    if not fields:
        return data
    wanted = {f.strip() for f in fields.split(",")}
    if "id" in data:
        wanted.add("id")
    return {k: v for k, v in data.items() if k in wanted}


def format_pagination(response: dict[str, Any], shown: int) -> str:
    """Square cursor pagination hint."""
    cursor = response.get("cursor")
    if not cursor:
        return ""
    return f'… more (pass cursor="{cursor}" to continue)'


def _items(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Pull the typed list out of a Square list response."""
    items = response.get(key, [])
    return items if isinstance(items, list) else []


# ---------------------------------------------------------------------------
# List formatters
# ---------------------------------------------------------------------------


def format_payment_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format payment list.

    Example::

        Aw4G... | $29.00 USD | COMPLETED | CARD | 2026-03-15 14:30 | loc=L1A2B3
    """
    items = _items(response, "payments")
    if not items:
        return "No payments found."
    shown = items[:limit]
    lines: list[str] = []
    for p in shown:
        parts = [
            p.get("id", "?"),
            format_square_money(p.get("amount_money")),
            p.get("status", "?"),
            p.get("source_type", "?"),
            format_datetime(p.get("created_at")),
        ]
        if loc := p.get("location_id"):
            parts.append(f"loc={loc}")
        if order := p.get("order_id"):
            parts.append(f"order={order}")
        if cust := p.get("customer_id"):
            parts.append(f"cust={cust}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_refund_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format refund list."""
    items = _items(response, "refunds")
    if not items:
        return "No refunds found."
    shown = items[:limit]
    lines: list[str] = []
    for r in shown:
        parts = [
            r.get("id", "?"),
            r.get("payment_id", "?"),
            format_square_money(r.get("amount_money")),
            r.get("status", "?"),
            format_datetime(r.get("created_at")),
        ]
        if reason := r.get("reason"):
            parts.append(f"reason={reason}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_customer_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format customer list."""
    items = _items(response, "customers")
    if not items:
        return "No customers found."
    shown = items[:limit]
    lines: list[str] = []
    for c in shown:
        name = " ".join(filter(None, [c.get("given_name"), c.get("family_name")])) or "(unnamed)"
        parts = [
            c.get("id", "?"),
            c.get("email_address") or "(no email)",
            name,
        ]
        if phone := c.get("phone_number"):
            parts.append(phone)
        if ref := c.get("reference_id"):
            parts.append(f"ref={ref}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_card_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format saved-card list (PCI-safe: last_4/brand/exp only)."""
    items = _items(response, "cards")
    if not items:
        return "No cards found."
    shown = items[:limit]
    lines: list[str] = []
    for c in shown:
        brand = c.get("card_brand", "?")
        last4 = c.get("last_4", "????")
        exp_m = c.get("exp_month")
        exp_y = c.get("exp_year")
        parts = [
            c.get("id", "?"),
            f"{brand} ****{last4}",
        ]
        if exp_m and exp_y:
            parts.append(f"exp {int(exp_m):02d}/{exp_y}")
        if cust := c.get("customer_id"):
            parts.append(f"cust={cust}")
        if c.get("enabled") is False:
            parts.append("disabled")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_location_list(response: dict[str, Any]) -> str:
    """Format location list (no pagination — Square returns all)."""
    items = _items(response, "locations")
    if not items:
        return "No locations found."
    lines: list[str] = []
    for loc in items:
        parts = [
            loc.get("id", "?"),
            loc.get("name", "(unnamed)"),
            loc.get("status", "?"),
            loc.get("type", "?"),
            loc.get("currency", "?"),
        ]
        if country := loc.get("country"):
            parts.append(country)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_order_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format order list (used by search_orders)."""
    items = _items(response, "orders")
    if not items:
        return "No orders found."
    shown = items[:limit]
    lines: list[str] = []
    for o in shown:
        parts = [
            o.get("id", "?"),
            o.get("location_id", "?"),
            o.get("state", "?"),
            format_square_money(o.get("total_money")),
            format_datetime(o.get("created_at")),
        ]
        if cust := o.get("customer_id"):
            parts.append(f"cust={cust}")
        line_items = o.get("line_items", []) or []
        if line_items:
            parts.append(f"{len(line_items)} items")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_catalog_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format catalog object list."""
    items = _items(response, "objects")
    if not items:
        return "No catalog objects found."
    shown = items[:limit]
    lines: list[str] = []
    for obj in shown:
        otype = obj.get("type", "?")
        parts = [obj.get("id", "?"), otype]
        # Each type stores its data under a `_data` key
        type_key = f"{otype.lower()}_data"
        data = obj.get(type_key, {}) or {}
        if name := data.get("name"):
            parts.append(name)
        if obj.get("is_deleted"):
            parts.append("deleted")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_dispute_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format dispute list."""
    items = _items(response, "disputes")
    if not items:
        return "No disputes found."
    shown = items[:limit]
    lines: list[str] = []
    for d in shown:
        parts = [
            d.get("id", "?"),
            d.get("disputed_payment", {}).get("payment_id", "?") if d.get("disputed_payment") else "?",
            format_square_money(d.get("amount_money")),
            d.get("state", "?"),
            d.get("reason", "?"),
        ]
        if due := d.get("due_at"):
            parts.append(f"due {format_date(due)}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_webhook_subscription_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format webhook subscription list."""
    items = _items(response, "subscriptions")
    if not items:
        return "No webhook subscriptions found."
    shown = items[:limit]
    lines: list[str] = []
    for s in shown:
        events = s.get("event_types", []) or []
        parts = [
            s.get("id", "?"),
            s.get("name", "(unnamed)"),
            s.get("notification_url", "?"),
            "enabled" if s.get("enabled") else "disabled",
            f"{len(events)} events",
        ]
        if api_v := s.get("api_version"):
            parts.append(f"api={api_v}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_event_type_list(response: dict[str, Any]) -> str:
    """Format webhook event types (a flat string array under ``event_types``)."""
    types = response.get("event_types", []) or []
    if not types:
        return "No event types found."
    metadata = response.get("metadata", []) or []
    by_event = {m.get("event_type"): m for m in metadata if isinstance(m, dict)}
    lines: list[str] = []
    for t in types:
        meta = by_event.get(t, {})
        if release := meta.get("release_status"):
            lines.append(f"{t} | {release}")
        else:
            lines.append(t)
    return "\n".join(lines)


def format_inventory_counts(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format batch inventory count response."""
    counts = response.get("counts", []) or []
    if not counts:
        return "No inventory counts found."
    shown = counts[:limit]
    lines: list[str] = []
    for c in shown:
        parts = [
            c.get("catalog_object_id", "?"),
            c.get("location_id", "?"),
            c.get("state", "?"),
            f"qty={c.get('quantity', '?')}",
            format_datetime(c.get("calculated_at")),
        ]
        lines.append(" | ".join(parts))
    if len(counts) > limit:
        lines.append(f"… +{len(counts) - limit} more (raise limit to see)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detail formatters
# ---------------------------------------------------------------------------


def format_payment_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format payment detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    lines.append(f"Status: {d.get('status', '?')}")
    lines.append(f"Amount: {format_square_money(d.get('amount_money'))}")
    if tip := d.get("tip_money"):
        lines.append(f"Tip: {format_square_money(tip)}")
    if total := d.get("total_money"):
        lines.append(f"Total: {format_square_money(total)}")
    if processing := d.get("processing_fee"):
        if isinstance(processing, list) and processing:
            fee = processing[0].get("amount_money")
            lines.append(f"Processing Fee: {format_square_money(fee)}")
    if refunded := d.get("refunded_money"):
        lines.append(f"Refunded: {format_square_money(refunded)}")
    lines.append(f"Source: {d.get('source_type', '?')}")
    if loc := d.get("location_id"):
        lines.append(f"Location: {loc}")
    if order := d.get("order_id"):
        lines.append(f"Order: {order}")
    if cust := d.get("customer_id"):
        lines.append(f"Customer: {cust}")
    if rcpt := d.get("receipt_url"):
        lines.append(f"Receipt: {rcpt}")
    if card := d.get("card_details"):
        cd = card.get("card", {}) or {}
        brand = cd.get("card_brand", "?")
        last4 = cd.get("last_4", "????")
        exp_m = cd.get("exp_month")
        exp_y = cd.get("exp_year")
        card_line = f"Card: {brand} ****{last4}"
        if exp_m and exp_y:
            card_line += f" exp {int(exp_m):02d}/{exp_y}"
        lines.append(card_line)
        if entry := card.get("entry_method"):
            lines.append(f"Entry: {entry}")
        if status := card.get("status"):
            lines.append(f"Card Status: {status}")
    if note := d.get("note"):
        lines.append(f"Note: {note}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    if updated := d.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    return "\n".join(lines)


def format_refund_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format refund detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    lines.append(f"Payment: {d.get('payment_id', '?')}")
    lines.append(f"Amount: {format_square_money(d.get('amount_money'))}")
    lines.append(f"Status: {d.get('status', '?')}")
    if reason := d.get("reason"):
        lines.append(f"Reason: {reason}")
    if loc := d.get("location_id"):
        lines.append(f"Location: {loc}")
    if order := d.get("order_id"):
        lines.append(f"Order: {order}")
    if processing := d.get("processing_fee"):
        if isinstance(processing, list) and processing:
            fee = processing[0].get("amount_money")
            lines.append(f"Processing Fee: {format_square_money(fee)}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    return "\n".join(lines)


def format_customer_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format customer detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    name = " ".join(filter(None, [d.get("given_name"), d.get("family_name")])) or "(unnamed)"
    lines.append(f"Name: {name}")
    if d.get("nickname"):
        lines.append(f"Nickname: {d['nickname']}")
    if d.get("company_name"):
        lines.append(f"Company: {d['company_name']}")
    if d.get("email_address"):
        lines.append(f"Email: {d['email_address']}")
    if d.get("phone_number"):
        lines.append(f"Phone: {d['phone_number']}")
    if d.get("reference_id"):
        lines.append(f"Reference: {d['reference_id']}")
    if d.get("note"):
        lines.append(f"Note: {d['note']}")
    if addr := d.get("address"):
        addr_parts = [
            addr.get("address_line_1"),
            addr.get("address_line_2"),
            addr.get("locality"),
            addr.get("administrative_district_level_1"),
            addr.get("postal_code"),
            addr.get("country"),
        ]
        lines.append("Address: " + ", ".join(p for p in addr_parts if p))
    if prefs := d.get("preferences"):
        if "email_unsubscribed" in prefs:
            lines.append(f"Email Unsubscribed: {prefs['email_unsubscribed']}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    if updated := d.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    return "\n".join(lines)


def format_card_detail(data: dict[str, Any]) -> str:
    """Format saved-card detail (PCI-safe)."""
    lines: list[str] = []
    lines.append(f"ID: {data.get('id', '?')}")
    lines.append(f"Brand: {data.get('card_brand', '?')}")
    lines.append(f"Last 4: {data.get('last_4', '????')}")
    exp_m = data.get("exp_month")
    exp_y = data.get("exp_year")
    if exp_m and exp_y:
        lines.append(f"Expiry: {int(exp_m):02d}/{exp_y}")
    if data.get("cardholder_name"):
        lines.append(f"Cardholder: {data['cardholder_name']}")
    if data.get("customer_id"):
        lines.append(f"Customer: {data['customer_id']}")
    if data.get("reference_id"):
        lines.append(f"Reference: {data['reference_id']}")
    if data.get("card_type"):
        lines.append(f"Type: {data['card_type']}")
    if data.get("prepaid_type"):
        lines.append(f"Prepaid: {data['prepaid_type']}")
    if data.get("bin"):
        lines.append(f"BIN: {data['bin']}")
    if data.get("fingerprint"):
        lines.append(f"Fingerprint: {data['fingerprint']}")
    lines.append(f"Enabled: {data.get('enabled', True)}")
    if data.get("merchant_id"):
        lines.append(f"Merchant: {data['merchant_id']}")
    return "\n".join(lines)


def format_location_detail(data: dict[str, Any]) -> str:
    """Format location detail."""
    lines: list[str] = []
    lines.append(f"ID: {data.get('id', '?')}")
    lines.append(f"Name: {data.get('name', '(unnamed)')}")
    lines.append(f"Status: {data.get('status', '?')}")
    lines.append(f"Type: {data.get('type', '?')}")
    lines.append(f"Currency: {data.get('currency', '?')}")
    if data.get("country"):
        lines.append(f"Country: {data['country']}")
    if data.get("language_code"):
        lines.append(f"Language: {data['language_code']}")
    if data.get("timezone"):
        lines.append(f"Timezone: {data['timezone']}")
    if addr := data.get("address"):
        addr_parts = [
            addr.get("address_line_1"),
            addr.get("address_line_2"),
            addr.get("locality"),
            addr.get("administrative_district_level_1"),
            addr.get("postal_code"),
            addr.get("country"),
        ]
        lines.append("Address: " + ", ".join(p for p in addr_parts if p))
    if data.get("phone_number"):
        lines.append(f"Phone: {data['phone_number']}")
    if data.get("business_name"):
        lines.append(f"Business: {data['business_name']}")
    if data.get("business_email"):
        lines.append(f"Business Email: {data['business_email']}")
    if data.get("website_url"):
        lines.append(f"Website: {data['website_url']}")
    if data.get("merchant_id"):
        lines.append(f"Merchant: {data['merchant_id']}")
    return "\n".join(lines)


def format_order_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format order detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    lines.append(f"Location: {d.get('location_id', '?')}")
    lines.append(f"State: {d.get('state', '?')}")
    if d.get("customer_id"):
        lines.append(f"Customer: {d['customer_id']}")
    if d.get("reference_id"):
        lines.append(f"Reference: {d['reference_id']}")
    if total := d.get("total_money"):
        lines.append(f"Total: {format_square_money(total)}")
    if tax := d.get("total_tax_money"):
        lines.append(f"Tax: {format_square_money(tax)}")
    if disc := d.get("total_discount_money"):
        lines.append(f"Discount: {format_square_money(disc)}")
    if tip := d.get("total_tip_money"):
        lines.append(f"Tip: {format_square_money(tip)}")
    if svc := d.get("total_service_charge_money"):
        lines.append(f"Service Charge: {format_square_money(svc)}")
    line_items = d.get("line_items", []) or []
    if line_items:
        lines.append(f"Line Items ({len(line_items)}):")
        for li in line_items[:10]:
            qty = li.get("quantity", "1")
            name = li.get("name", "?")
            total_li = format_square_money(li.get("total_money"))
            lines.append(f"  {name} | qty={qty} | {total_li}")
        if len(line_items) > 10:
            lines.append(f"  … +{len(line_items) - 10} more")
    fulfillments = d.get("fulfillments", []) or []
    if fulfillments:
        for f in fulfillments:
            lines.append(f"Fulfillment: {f.get('type', '?')} | {f.get('state', '?')}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    if updated := d.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    if closed := d.get("closed_at"):
        lines.append(f"Closed: {format_datetime(closed)}")
    return "\n".join(lines)


def format_catalog_detail(response: dict[str, Any], fields: str | None = None) -> str:
    """Format a catalog object detail.

    Square returns ``{"object": {...}, "related_objects": [...]}`` for retrieve.
    """
    obj = response.get("object", response)
    if not isinstance(obj, dict):
        return "(no catalog object)"
    d = select_fields(obj, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    otype = d.get("type", "?")
    lines.append(f"Type: {otype}")
    type_key = f"{otype.lower()}_data"
    inner = d.get(type_key, {}) or {}
    if name := inner.get("name"):
        lines.append(f"Name: {name}")
    if desc := inner.get("description"):
        lines.append(f"Description: {desc}")
    if abbr := inner.get("abbreviation"):
        lines.append(f"Abbreviation: {abbr}")
    if d.get("is_deleted"):
        lines.append("Deleted: True")
    if updated := d.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    related = response.get("related_objects", []) or []
    if related:
        lines.append(f"Related: {len(related)} objects")
    return "\n".join(lines)


def format_dispute_detail(data: dict[str, Any]) -> str:
    """Format dispute detail."""
    lines: list[str] = []
    lines.append(f"ID: {data.get('id', '?')}")
    lines.append(f"State: {data.get('state', '?')}")
    lines.append(f"Reason: {data.get('reason', '?')}")
    lines.append(f"Amount: {format_square_money(data.get('amount_money'))}")
    if dp := data.get("disputed_payment"):
        lines.append(f"Payment: {dp.get('payment_id', '?')}")
    if loc := data.get("location_id"):
        lines.append(f"Location: {loc}")
    if card := data.get("card_brand"):
        lines.append(f"Card Brand: {card}")
    if reported := data.get("reported_date"):
        lines.append(f"Reported: {reported}")
    if due := data.get("due_at"):
        lines.append(f"Due: {format_datetime(due)}")
    if version := data.get("version"):
        lines.append(f"Version: {version}")
    if brand := data.get("brand_dispute_id"):
        lines.append(f"Brand Dispute ID: {brand}")
    return "\n".join(lines)


def format_webhook_subscription_detail(data: dict[str, Any]) -> str:
    """Format webhook subscription detail."""
    lines: list[str] = []
    lines.append(f"ID: {data.get('id', '?')}")
    lines.append(f"Name: {data.get('name', '(unnamed)')}")
    lines.append(f"URL: {data.get('notification_url', '?')}")
    lines.append(f"Enabled: {data.get('enabled', True)}")
    if api_v := data.get("api_version"):
        lines.append(f"API Version: {api_v}")
    events = data.get("event_types", []) or []
    if events:
        lines.append(f"Event Types ({len(events)}):")
        for e in events[:20]:
            lines.append(f"  {e}")
        if len(events) > 20:
            lines.append(f"  … +{len(events) - 20} more")
    if data.get("signature_key"):
        lines.append("Signature Key: **** (hidden)")
    if created := data.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    if updated := data.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    return "\n".join(lines)


def format_webhook_verification(result: dict[str, Any]) -> str:
    """Format webhook verification result."""
    if result.get("verified"):
        event = result.get("event") or {}
        event_type = event.get("event_type", "?")
        event_id = event.get("event_id", "?")
        created = format_datetime(event.get("created_at"))
        merchant = event.get("merchant_id", "?")
        return f"Verified: {event_type} | {event_id} | {created} | merchant={merchant}"
    return f"Invalid webhook: {result.get('error', 'verification failed')}"


def format_subscription_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format subscription list (search response)."""
    items = _items(response, "subscriptions")
    if not items:
        return "No subscriptions found."
    shown = items[:limit]
    lines: list[str] = []
    for s in shown:
        parts = [
            s.get("id", "?"),
            s.get("status", "?"),
            f"plan={s.get('plan_variation_id') or s.get('plan_id') or '?'}",
        ]
        if cust := s.get("customer_id"):
            parts.append(f"cust={cust}")
        if loc := s.get("location_id"):
            parts.append(f"loc={loc}")
        if start := s.get("start_date"):
            parts.append(f"start={start}")
        if charged := s.get("charged_through_date"):
            parts.append(f"thru={charged}")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_subscription_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format subscription detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    lines.append(f"Status: {d.get('status', '?')}")
    if plan := d.get("plan_variation_id") or d.get("plan_id"):
        lines.append(f"Plan: {plan}")
    if cust := d.get("customer_id"):
        lines.append(f"Customer: {cust}")
    if loc := d.get("location_id"):
        lines.append(f"Location: {loc}")
    if start := d.get("start_date"):
        lines.append(f"Start: {start}")
    if charged := d.get("charged_through_date"):
        lines.append(f"Charged Through: {charged}")
    if canceled := d.get("canceled_date"):
        lines.append(f"Canceled: {canceled}")
    if invoice := d.get("invoice_ids"):
        lines.append(f"Invoices: {len(invoice)}")
    if version := d.get("version"):
        lines.append(f"Version: {version}")
    if d.get("timezone"):
        lines.append(f"Timezone: {d['timezone']}")
    actions = d.get("actions", []) or []
    if actions:
        lines.append(f"Pending Actions ({len(actions)}):")
        for a in actions[:5]:
            atype = a.get("type", "?")
            eff = a.get("effective_date") or a.get("effective_time") or "?"
            lines.append(f"  {atype} | {eff}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    return "\n".join(lines)


def format_subscription_plan_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format subscription plan list (Catalog list filtered by SUBSCRIPTION_PLAN)."""
    items = _items(response, "objects")
    if not items:
        return "No subscription plans found."
    shown = items[:limit]
    lines: list[str] = []
    for obj in shown:
        otype = obj.get("type", "?")
        data = obj.get("subscription_plan_data") or obj.get("subscription_plan_variation_data") or {}
        parts = [obj.get("id", "?"), otype]
        if name := data.get("name"):
            parts.append(name)
        phases = data.get("phases") or data.get("subscription_phases") or []
        if phases:
            parts.append(f"{len(phases)} phases")
        if obj.get("is_deleted"):
            parts.append("deleted")
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_invoice_list(response: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Format invoice list."""
    items = _items(response, "invoices")
    if not items:
        return "No invoices found."
    shown = items[:limit]
    lines: list[str] = []
    for inv in shown:
        parts = [
            inv.get("id", "?"),
            inv.get("status", "?"),
            inv.get("invoice_number") or "(no number)",
        ]
        if cust_req := inv.get("primary_recipient", {}).get("customer_id") if inv.get("primary_recipient") else None:
            parts.append(f"cust={cust_req}")
        if order := inv.get("order_id"):
            parts.append(f"order={order}")
        order_request = inv.get("payment_requests") or []
        if order_request:
            first_amount = order_request[0].get("computed_amount_money") or order_request[0].get(
                "fixed_amount_requested_money"
            )
            if first_amount:
                parts.append(format_square_money(first_amount))
        if created := inv.get("created_at"):
            parts.append(format_datetime(created))
        lines.append(" | ".join(parts))
    if hint := format_pagination(response, len(shown)):
        lines.append(hint)
    return "\n".join(lines)


def format_invoice_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format invoice detail."""
    d = select_fields(data, fields)
    lines: list[str] = []
    lines.append(f"ID: {d.get('id', '?')}")
    lines.append(f"Status: {d.get('status', '?')}")
    if num := d.get("invoice_number"):
        lines.append(f"Invoice Number: {num}")
    if title := d.get("title"):
        lines.append(f"Title: {title}")
    if order := d.get("order_id"):
        lines.append(f"Order: {order}")
    if loc := d.get("location_id"):
        lines.append(f"Location: {loc}")
    if recipient := d.get("primary_recipient"):
        cust = recipient.get("customer_id") or "?"
        email = recipient.get("email_address")
        line = f"Recipient: {cust}"
        if email:
            line += f" <{email}>"
        lines.append(line)
    pay_reqs = d.get("payment_requests") or []
    if pay_reqs:
        lines.append(f"Payment Requests ({len(pay_reqs)}):")
        for pr in pay_reqs[:5]:
            req_type = pr.get("request_type", "?")
            amt = pr.get("computed_amount_money") or pr.get("fixed_amount_requested_money")
            money = format_square_money(amt) if amt else "?"
            due = pr.get("due_date") or "?"
            lines.append(f"  {req_type} | {money} | due {due}")
    if d.get("public_url"):
        lines.append(f"Public URL: {d['public_url']}")
    if d.get("delivery_method"):
        lines.append(f"Delivery: {d['delivery_method']}")
    if version := d.get("version"):
        lines.append(f"Version: {version}")
    if created := d.get("created_at"):
        lines.append(f"Created: {format_datetime(created)}")
    if updated := d.get("updated_at"):
        lines.append(f"Updated: {format_datetime(updated)}")
    return "\n".join(lines)


def format_info(env: str, api_version: str, write_enabled: bool) -> str:
    """Format the ``square_info`` tool output."""
    lines = [
        f"Environment: {env or '(unset)'}",
        f"API Version: {api_version}",
        f"Write Operations: {'enabled' if write_enabled else 'disabled'}",
    ]
    return "\n".join(lines)
