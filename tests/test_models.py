"""Tests for models.py — gates, money formatting, env validation, scrubbing."""

from __future__ import annotations

import pytest

from square_blade_mcp.models import (
    format_money,
    format_square_money,
    get_environment_name,
    is_write_enabled,
    require_confirm,
    require_write,
    scrub_secrets,
    validate_environment,
)


class TestValidateEnvironment:
    def test_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "sandbox")
        assert validate_environment() == "https://connect.squareupsandbox.com"

    def test_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "production")
        assert validate_environment() == "https://connect.squareup.com"

    def test_missing_raises(self) -> None:
        with pytest.raises(ValueError, match="SQUARE_ENVIRONMENT must be"):
            validate_environment()

    def test_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "staging")
        with pytest.raises(ValueError, match="staging"):
            validate_environment()

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "Production")
        assert validate_environment() == "https://connect.squareup.com"

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "  sandbox  ")
        assert validate_environment() == "https://connect.squareupsandbox.com"


class TestGetEnvironmentName:
    def test_returns_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_ENVIRONMENT", "sandbox")
        assert get_environment_name() == "sandbox"

    def test_empty_when_unset(self) -> None:
        assert get_environment_name() == ""


class TestWriteGate:
    def test_disabled_by_default(self) -> None:
        assert not is_write_enabled()
        err = require_write()
        assert err is not None
        assert "disabled" in err

    def test_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_WRITE_ENABLED", "true")
        assert is_write_enabled()
        assert require_write() is None

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_WRITE_ENABLED", "True")
        assert is_write_enabled()

    def test_non_true_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQUARE_WRITE_ENABLED", "yes")
        assert not is_write_enabled()


class TestConfirmGate:
    def test_no_confirm_returns_error(self) -> None:
        err = require_confirm(False, "Cancel payment")
        assert err is not None
        assert "confirm=true" in err
        assert "Cancel payment" in err

    def test_confirm_true_returns_none(self) -> None:
        assert require_confirm(True, "Cancel payment") is None


class TestFormatMoney:
    def test_usd(self) -> None:
        assert format_money(2900, "USD") == "$29.00 USD"

    def test_zero(self) -> None:
        assert format_money(0, "USD") == "$0.00 USD"

    def test_gbp(self) -> None:
        assert format_money(1050, "GBP") == "£10.50 GBP"

    def test_jpy_zero_decimal(self) -> None:
        assert format_money(1000, "JPY") == "¥1000 JPY"

    def test_unknown_currency(self) -> None:
        result = format_money(500, "XYZ")
        assert "5.00" in result
        assert "XYZ" in result

    def test_invalid_amount(self) -> None:
        assert format_money("not a number", "USD") == "not a number USD"

    def test_eur(self) -> None:
        assert format_money(9900, "EUR") == "€99.00 EUR"

    def test_none(self) -> None:
        assert format_money(None, "USD") == "?"


class TestFormatSquareMoney:
    def test_dict(self) -> None:
        assert format_square_money({"amount": 2900, "currency": "USD"}) == "$29.00 USD"

    def test_none(self) -> None:
        assert format_square_money(None) == "?"

    def test_empty(self) -> None:
        assert format_square_money({}) == "?"


class TestScrubSecrets:
    def test_scrubs_access_token(self) -> None:
        text = "Bad request with token EAAAEXAMPLEtoken_abc"
        result = scrub_secrets(text)
        assert "EAAA" not in result
        assert "****" in result

    def test_scrubs_app_id(self) -> None:
        text = "App: sq0idp-abcdef-12345"
        result = scrub_secrets(text)
        assert "sq0idp-" not in result
        assert "****" in result

    def test_scrubs_app_secret(self) -> None:
        text = "Secret: sq0csp-supersecret_xyz"
        result = scrub_secrets(text)
        assert "sq0csp-" not in result
        assert "****" in result

    def test_scrubs_bearer_token(self) -> None:
        text = "Authorization: Bearer my_secret_token"
        result = scrub_secrets(text)
        assert "my_secret_token" not in result
        assert "****" in result

    def test_leaves_clean_text(self) -> None:
        text = "Everything is fine"
        assert scrub_secrets(text) == text
