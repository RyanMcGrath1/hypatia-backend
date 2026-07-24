# Logging and audit events

Hypatia separates **application logs**, **account audit events**, and **security log events**. Do not mix their purposes.

## Application logs

Configured in `hypatia/utils/logging_config.py`.

- HTTP request/access lines (`http_request`, optional `http_request_start`)
- Upstream calls (`upstream`)
- Operational errors and diagnostics

Correlation uses `g.request_id` (from `X-Request-ID` or a generated UUID), echoed on responses as `X-Request-ID`.

## Account events (`account_events`)

Persistent, user-scoped security/audit history. Written only through:

`hypatia.services.audit.record_account_event`

Supported taxonomy:

| Event | When |
|-------|------|
| `ACCOUNT_CREATED` | Registration |
| `LOGIN_SUCCESS` | Completed password login (or MFA completion) |
| `LOGIN_FAILED` | Failed auth for a known user |
| `LOGOUT` | Successful authenticated logout |
| `PASSWORD_CHANGED` | Password change |
| `EMAIL_CHANGE_REQUESTED` | Dual-confirm email change started |
| `EMAIL_CHANGED` | Email change completed |
| `TOTP_ENABLED` / `TOTP_DISABLED` | Authenticator app enable/disable |
| `ACCOUNT_DELETED` | Soft-delete / anonymization |

`record_account_event` does **not** commit; the business operation owns the transaction.

Request metadata captured (when available): `ip_address` (`request.remote_addr`), `request_id`, `user_agent`. Use `get_audit_request_context()` in routes instead of reading Flask request fields ad hoc.

Soft deletion keeps the User tombstone and all `AccountEvent` rows (including `ACCOUNT_DELETED`). If physical User deletion is added later, revisit audit retention and the `ON DELETE CASCADE` FK before enabling hard deletes.

## Security log events (`hypatia.security`)

Structured records (`event=security_event`) for security-relevant cases that cannot attach to a user row — notably `LOGIN_FAILED` for an unknown email. These use the existing Python logging stack (JSON-compatible when `LOG_FORMAT=json`). They must not invent a fake `user_id` or store the attempted email.

## Never log

Credentials, password hashes, session tokens / token hashes, `Authorization` headers, SMTP passwords, TOTP encryption keys / secrets / codes, MFA challenge tokens/hashes, email verification or email-change tokens/URLs, or provisioning URIs. Do not serialize full ORM objects into logs.
