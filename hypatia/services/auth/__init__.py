"""Authentication services (password hashing, validation, credential checks)."""

from hypatia.services.auth.authentication import AuthenticationResult, authenticate_user
from hypatia.services.auth.emails import EmailValidationResult, normalize_email, validate_email
from hypatia.services.auth.passwords import hash_password, password_needs_rehash, verify_password
from hypatia.services.auth.registration import RegistrationResult, register_user
from hypatia.services.auth.validation import PasswordValidationResult, validate_password

__all__ = [
    "AuthenticationResult",
    "EmailValidationResult",
    "PasswordValidationResult",
    "RegistrationResult",
    "authenticate_user",
    "hash_password",
    "normalize_email",
    "password_needs_rehash",
    "register_user",
    "validate_email",
    "validate_password",
    "verify_password",
]
