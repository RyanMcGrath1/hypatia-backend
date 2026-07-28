"""Shared email normalization tests."""

from __future__ import annotations

from hypatia.services.auth.emails import normalize_email, validate_email


def test_normalize_email_strips_and_casefolds() -> None:
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_normalize_email_does_not_alter_local_part_beyond_casefold() -> None:
    assert normalize_email("a.b+tag@Example.com") == "a.b+tag@example.com"


def test_validate_email_rejects_empty_and_whitespace() -> None:
    assert validate_email("").ok is False
    assert validate_email("   ").ok is False


def test_validate_email_rejects_invalid_format() -> None:
    assert validate_email("not-an-email").ok is False
    assert validate_email("missing-domain@").ok is False
    assert validate_email("@example.com").ok is False


def test_validate_email_accepts_reasonable_address() -> None:
    result = validate_email("  User@Example.COM ")
    assert result.ok is True
    assert result.normalized == "user@example.com"
