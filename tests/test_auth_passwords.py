"""Password hashing and verification tests."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.low_level import Type

from hypatia.services.auth.passwords import (
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_plaintext_password_hashes_successfully() -> None:
    stored = hash_password("validpassword12")
    assert stored
    assert isinstance(stored, str)


def test_resulting_hash_is_argon2id() -> None:
    stored = hash_password("validpassword12")
    assert stored.startswith("$argon2id$")


def test_correct_password_verifies() -> None:
    stored = hash_password("validpassword12")
    assert verify_password(stored, "validpassword12") is True


def test_incorrect_password_fails() -> None:
    stored = hash_password("validpassword12")
    assert verify_password(stored, "wrongpassword12") is False


def test_same_plaintext_produces_different_hashes() -> None:
    first = hash_password("validpassword12")
    second = hash_password("validpassword12")
    assert first != second
    assert verify_password(first, "validpassword12")
    assert verify_password(second, "validpassword12")


def test_rehash_check_false_for_current_parameters() -> None:
    stored = hash_password("validpassword12")
    assert password_needs_rehash(stored) is False


def test_rehash_check_true_for_outdated_parameters() -> None:
    legacy_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1, type=Type.ID)
    stored = legacy_hasher.hash("validpassword12")
    assert password_needs_rehash(stored) is True
