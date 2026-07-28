"""Centralized TOTP verification with RFC 6238 replay prevention.

Uses standard PyOTP parameters (6 digits, 30-second period) and a
``valid_window`` of 1 (± one time-step) for clock drift.

Replay prevention tracks the matched time-step counter in
``totp_methods.last_used_timecode``. A successfully validated OTP must not
be accepted a second time.

SQLite concurrency note: under concurrent writers, two requests could both
read the same ``last_used_timecode`` before either commits. Stronger
serialization would require row-level locking / SELECT FOR UPDATE (or an
equivalent) on a database that supports it. Application-level verification
still enforces replay after each successful commit.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass

import pyotp

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_VALID_WINDOW = 1


@dataclass(frozen=True, slots=True)
class TotpVerificationResult:
    ok: bool
    matched_timecode: int | None = None


def build_totp(secret_base32: str) -> pyotp.TOTP:
    """Return a standard interoperable TOTP instance for ``secret_base32``."""
    return pyotp.TOTP(secret_base32, digits=TOTP_DIGITS, interval=TOTP_PERIOD_SECONDS)


def generate_totp_secret() -> str:
    """Generate a new Base32 TOTP secret via PyOTP."""
    return pyotp.random_base32()


def build_provisioning_uri(*, secret_base32: str, account_email: str, issuer: str) -> str:
    """Return a standard ``otpauth://`` provisioning URI (never log this)."""
    totp = build_totp(secret_base32)
    return totp.provisioning_uri(name=account_email, issuer_name=issuer)


def verify_totp_code(
    secret_base32: str,
    code: str,
    *,
    last_used_timecode: int | None = None,
    valid_window: int = TOTP_VALID_WINDOW,
    for_time: float | None = None,
) -> TotpVerificationResult:
    """Verify ``code`` and return the matched time-step when accepted.

    Rejects codes whose matched timecode is ``<= last_used_timecode`` so a
    previously consumed OTP cannot be replayed, including within the drift
    window.
    """
    if not isinstance(code, str):
        return TotpVerificationResult(ok=False)
    normalized = code.strip()
    if len(normalized) != TOTP_DIGITS or not normalized.isdigit():
        return TotpVerificationResult(ok=False)

    totp = build_totp(secret_base32)
    now = int(for_time if for_time is not None else time.time())
    current_timecode = now // totp.interval

    for offset in range(-valid_window, valid_window + 1):
        timecode = current_timecode + offset
        if last_used_timecode is not None and timecode <= last_used_timecode:
            continue
        expected = totp.generate_otp(timecode)
        if hmac.compare_digest(expected, normalized):
            return TotpVerificationResult(ok=True, matched_timecode=timecode)

    return TotpVerificationResult(ok=False)
