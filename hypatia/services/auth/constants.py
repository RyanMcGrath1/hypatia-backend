"""Shared authentication constants."""

from __future__ import annotations

ACCOUNT_STATUS_ACTIVE = "active"

EVENT_ACCOUNT_CREATED = "ACCOUNT_CREATED"
EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
EVENT_LOGIN_FAILED = "LOGIN_FAILED"

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password"
EMAIL_ALREADY_REGISTERED_MESSAGE = "An account with this email already exists"
UNAUTHENTICATED_MESSAGE = "Authentication required"
