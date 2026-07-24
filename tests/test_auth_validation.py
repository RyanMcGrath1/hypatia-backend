"""Password validation tests."""

from __future__ import annotations

from hypatia.services.auth.validation import MIN_PASSWORD_LENGTH, validate_password


def test_password_shorter_than_minimum_rejected() -> None:
    result = validate_password("short")
    assert result.ok is False
    assert result.error is not None
    assert str(MIN_PASSWORD_LENGTH) in result.error


def test_password_with_minimum_length_accepted() -> None:
    result = validate_password("a" * MIN_PASSWORD_LENGTH)
    assert result.ok is True
    assert result.error is None


def test_password_with_spaces_accepted() -> None:
    result = validate_password(" twelve chars")
    assert result.ok is True


def test_password_is_not_silently_stripped() -> None:
    password = " 12345678901"
    assert len(password) == 12
    assert validate_password(password).ok is True
    assert validate_password(password.lstrip()).ok is False


def test_empty_password_rejected() -> None:
    result = validate_password("")
    assert result.ok is False
    assert result.error == "Password is required"
