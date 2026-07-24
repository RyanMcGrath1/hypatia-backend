"""SQLAlchemy models (import here so metadata registers all tables)."""

from hypatia.models.account_event import AccountEvent
from hypatia.models.email_change_request import EmailChangeRequest
from hypatia.models.mfa_login_challenge import MfaLoginChallenge
from hypatia.models.profile import Profile
from hypatia.models.session import Session
from hypatia.models.totp_method import TOTPMethod
from hypatia.models.user import User

__all__ = [
    "AccountEvent",
    "EmailChangeRequest",
    "MfaLoginChallenge",
    "Profile",
    "Session",
    "TOTPMethod",
    "User",
]
