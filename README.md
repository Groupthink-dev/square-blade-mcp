# square-blade-mcp

Square MCP server — payments, refunds, orders, catalog, customers, cards, disputes, webhooks (`payments-v1`) **and** subscriptions, subscription plans, invoices (`billing-v1`). Implements both [`payments-v1`](https://github.com/Groupthink-dev/stallari-pack-spec) and [`billing-v1`](https://github.com/Groupthink-dev/stallari-pack-spec) Stallari contracts.

Token-efficient by default: pipe-delimited list rows, field selection, human-readable money, null-field omission. Write operations gated behind `SQUARE_WRITE_ENABLED=true`. Destructive operations (cancel, delete, disable, pause, resume, send invoice) require `confirm=true`.

## Why not `square/square-mcp-server`?

Square's official server uses a "meta-tool" pattern: a single `make_request` tool that takes a method name and JSON args. That works for breadth but pushes parsing, output trimming, and error formatting onto the model — which burns tokens and removes any chance of structured guardrails.

| Concern | `square/square-mcp-server` | `square-blade-mcp` |
|---|---|---|
| Tool surface | 1 meta-tool | 45 typed tools |
| Output | Raw JSON | Pipe-delim lists, formatted money, null-omitted |
| Write gates | None | `SQUARE_WRITE_ENABLED` env + `confirm=true` on destructive |
| PCI safety | Caller's problem | Card output limited to last_4/brand/exp/fingerprint |
| Credential scrubbing | None | Access tokens, app IDs, app secrets, bearer tokens scrubbed from errors |
| Webhook verification | Multi-step | Single `square_verify_webhook` tool |
| Idempotency | Caller-supplied | Auto-injected UUIDv4 if omitted, caller key preserved |
| Contract compliance | N/A | `payments-v1` + `billing-v1` (Stallari) |

The two can coexist in the same Stallari catalog — `square-mcp-server` for breadth/escape-hatch, `square-blade-mcp` for the typical operator-driven flows.

## Install

```bash
uv sync --group dev --group test
```

## Configure

```bash
export SQUARE_ACCESS_TOKEN=EAAA...           # PAT from Square Developer Dashboard
export SQUARE_ENVIRONMENT=sandbox            # or "production"
export SQUARE_WRITE_ENABLED=true             # opt-in to writes (default: read-only)
export SQUARE_WEBHOOK_SIGNATURE_KEY=...      # optional, for webhook verification
```

## Run

```bash
uv run square-blade-mcp                      # stdio (default)
SQUARE_MCP_TRANSPORT=http uv run square-blade-mcp   # HTTP on 127.0.0.1:8770
```

For HTTP transport, set `SQUARE_MCP_API_TOKEN` to require bearer auth.

## Scope

**`payments-v1`** (Required + Recommended + Optional + most Gated):
- Payments: list / get / create / cancel / complete
- Refunds: list / get / create
- Customers: list / search / get / create / update / delete
- Cards (on file): list / get / create / disable
- Locations: list / get
- Orders: get / search / create / update / pay
- Catalog: list / get / inventory query
- Disputes: list / get
- Webhooks: list subs / create sub / delete sub / event types / **single-call verify**

**`billing-v1`** (v0.2.0 — Square Subscriptions + Invoices APIs):
- Subscriptions: list / get / create / update / cancel / pause / resume
- Subscription plans: list / get / create (via Catalog `SUBSCRIPTION_PLAN`)
- Invoices: list / get / create / send / cancel
- Adjustments: refunds (re-used from `payments-v1`)
- Discounts: catalog discount objects (re-used from `payments-v1`)

**Honest gaps** (declared via `not_supported:` in the manifest):
- `credit_balance`, `events`, `notifications`, `reports`, `preview_transaction`, `ip_addresses` — Square has no equivalent
- `create_discount`, `replay_notification`, `simulate` — gated ops outside this server's scope
- payments-v1 gated extras still deferred: `card_delete` (use `card_disable`), `payment_void`, `refund_unlinked`, `inventory_adjust`

**Deferred** (roadmap):
- v0.3.0 — OAuth (token exchange + refresh, scope mapping per [DD-154])
- v0.4.0 — Bookings, Loyalty, Gift Cards

## Development

```bash
make test         # unit tests
make check        # lint + format + type-check
make test-e2e     # requires SQUARE_E2E=1 + live sandbox creds
```

## License

MIT
