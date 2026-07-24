"""Password validation tests."""

from __future__ import annotations

from hypatia.services.auth.validation import MIN_PASSWORD_LENGTH, validate_password


def test_password_minimum_is_fifteen() -> None:
    assert MIN_PASSWORD_LENGTH == 15


def test_password_shorter_than_minimum_rejected() -> None:
    result = validate_password("short")
    assert result.ok is False
    assert result.error is not None
    assert str(MIN_PASSWORD_LENGTH) in result.error


def test_fourteen_character_password_rejected() -> None:
    password = "a" * 14
    assert len(password) == 14
    result = validate_password(password)
    assert result.ok is False
    assert result.error is not None
    assert "15" in result.error


def test_password_with_minimum_length_accepted() -> None:
    result = validate_password("a" * MIN_PASSWORD_LENGTH)
    assert result.ok is True
    assert result.error is None


def test_fifteen_character_password_accepted() -> None:
    password = "a" * 15
    assert len(password) == 15
    assert validate_password(password).ok is True


def test_password_with_spaces_accepted() -> None:
    password = " fifteen chars "
    assert len(password) == 15
    assert validate_password(password).ok is True


def test_password_is_not_silently_stripped() -> None:
    password = " 12345678901234"
    assert len(password) == 15
    assert validate_password(password).ok is True
    assert validate_password(password.lstrip()).ok is False


def test_empty_password_rejected() -> None:
    result = validate_password("")
    assert result.ok is False
    assert result.error == "Password is required"
