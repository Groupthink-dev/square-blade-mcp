"""Shared constants, types, and gates for Square Blade MCP server."""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 20
MAX_LIMIT = 100  # Square API max limit per page (varies by endpoint, 100 is safe upper bound)
MAX_BODY_CHARS = 50_000

# Square API version pinned for stability. Bump deliberately.
SQUARE_API_VERSION = "2024-12-18"

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

BASE_URLS: dict[str, str] = {
    "sandbox": "https://connect.squareupsandbox.com",
    "production": "https://connect.squareup.com",
}

# Currency symbols for human-readable money formatting
CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "JPY": "¥",
    "CNY": "¥",
    "CHF": "CHF ",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "INR": "₹",
    "BRL": "R$",
    "KRW": "₩",
    "MXN": "MX$",
    "PLN": "zł",
    "THB": "฿",
    "TRY": "₺",
}

# Zero-decimal currencies — Square also stores these in major units (no cents division).
ZERO_DECIMAL_CURRENCIES: set[str] = {"JPY", "KRW", "VND"}


# ---------------------------------------------------------------------------
# Environment validation (fail-closed)
# ---------------------------------------------------------------------------


def validate_environment() -> str:
    """Validate SQUARE_ENVIRONMENT and return the base URL.

    Raises:
        ValueError: If SQUARE_ENVIRONMENT is missing or invalid.
    """
    env = os.environ.get("SQUARE_ENVIRONMENT", "").strip().lower()
    if env not in BASE_URLS:
        raise ValueError(
            f"SQUARE_ENVIRONMENT must be 'sandbox' or 'production', got '{env or '(empty)'}'. "
            "This is required to prevent accidental operations against the wrong environment."
        )
    return BASE_URLS[env]


def get_environment_name() -> str:
    """Return the current environment name (sandbox/production)."""
    return os.environ.get("SQUARE_ENVIRONMENT", "").strip().lower()


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------


def is_write_enabled() -> bool:
    """Check if write operations are enabled via env var."""
    return os.environ.get("SQUARE_WRITE_ENABLED", "").lower() == "true"


def require_write() -> str | None:
    """Return an error message if writes are disabled, else None."""
    if not is_write_enabled():
        return "Error: Write operations are disabled. Set SQUARE_WRITE_ENABLED=true to enable."
    return None


# ---------------------------------------------------------------------------
# Confirm gate (for destructive operations)
# ---------------------------------------------------------------------------


def require_confirm(confirm: bool, action: str) -> str | None:
    """Return an error message if confirm is False for a destructive operation.

    This is a second gate beyond require_write() for operations that are
    difficult or impossible to reverse (cancel payment, delete customer/card,
    delete webhook subscription).
    """
    if not confirm:
        return f"Error: {action} requires confirm=true. This action may be difficult to reverse."
    return None


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------


def format_money(amount: int | str | None, currency_code: str | None) -> str:
    """Format a Square money amount for human-readable output.

    Square stores Money objects as ``{amount: int, currency: str}`` where
    amount is in the smallest unit (cents for USD, etc.). Zero-decimal
    currencies (JPY, KRW, VND) are already in major units.

    Examples:
        format_money(2900, "USD") -> "$29.00 USD"
        format_money(1000, "JPY") -> "¥1000 JPY"
        format_money(0, "USD")    -> "$0.00 USD"
    """
    if amount is None or currency_code is None:
        return "?"
    try:
        cents = int(amount)
    except (ValueError, TypeError):
        return f"{amount} {currency_code}"

    symbol = CURRENCY_SYMBOLS.get(currency_code, "")

    if currency_code in ZERO_DECIMAL_CURRENCIES:
        return f"{symbol}{cents} {currency_code}"

    major = cents / 100
    return f"{symbol}{major:.2f} {currency_code}"


def format_square_money(money: dict[str, object] | None) -> str:
    """Format a Square Money object ``{amount, currency}``."""
    if not money:
        return "?"
    amount = money.get("amount")
    currency = money.get("currency")
    if isinstance(amount, int | str | type(None)) and isinstance(currency, str | type(None)):
        return format_money(amount, currency)
    return "?"


# ---------------------------------------------------------------------------
# Token scrubbing
# ---------------------------------------------------------------------------

# Patterns that indicate Square API keys, tokens, or app secrets.
# Square access tokens (PATs and OAuth) start with "EAAA" followed by base64-ish.
# App IDs start with "sq0idp-"; app secrets start with "sq0csp-".
_SCRUB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"EAAA[A-Za-z0-9_\-]+"),  # Square access tokens (PAT and OAuth)
    re.compile(r"sq0idp-[A-Za-z0-9_\-]+"),  # Square application IDs
    re.compile(r"sq0csp-[A-Za-z0-9_\-]+"),  # Square application secrets
    re.compile(r"Bearer\s+[^\s]+", re.IGNORECASE),  # Bearer tokens
]


def scrub_secrets(text: str) -> str:
    """Remove API keys and tokens from text to prevent leakage."""
    result = text
    for pattern in _SCRUB_PATTERNS:
        result = pattern.sub("****", result)
    return result
