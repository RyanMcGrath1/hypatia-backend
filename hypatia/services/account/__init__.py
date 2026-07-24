"""Account services for the authenticated current user."""

from hypatia.services.account.email_change import (
    EMAIL_CHANGE_COMPLETE_MESSAGE,
    EMAIL_CHANGE_CONFIRMATION_MESSAGE,
    EMAIL_DELIVERY_FAILED_MESSAGE,
    INVALID_VERIFICATION_TOKEN_MESSAGE,
    NEW_EMAIL_SAME_AS_CURRENT_MESSAGE,
    RequestEmailChangeResult,
    VerifyEmailChangeResult,
    build_email_change_verify_url,
    generate_email_change_token,
    hash_email_change_token,
    request_email_change,
    verify_email_change,
)
from hypatia.services.account.password import (
    CURRENT_PASSWORD_INCORRECT_MESSAGE,
    NEW_PASSWORDS_DO_NOT_MATCH_MESSAGE,
    ChangePasswordResult,
    change_user_password,
)

__all__ = [
    "CURRENT_PASSWORD_INCORRECT_MESSAGE",
    "EMAIL_CHANGE_COMPLETE_MESSAGE",
    "EMAIL_CHANGE_CONFIRMATION_MESSAGE",
    "EMAIL_DELIVERY_FAILED_MESSAGE",
    "INVALID_VERIFICATION_TOKEN_MESSAGE",
    "NEW_EMAIL_SAME_AS_CURRENT_MESSAGE",
    "NEW_PASSWORDS_DO_NOT_MATCH_MESSAGE",
    "ChangePasswordResult",
    "RequestEmailChangeResult",
    "VerifyEmailChangeResult",
    "build_email_change_verify_url",
    "change_user_password",
    "generate_email_change_token",
    "hash_email_change_token",
    "request_email_change",
    "verify_email_change",
]
