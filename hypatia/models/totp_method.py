"""Per-user TOTP authenticator-app enrollment.

One row per user (``user_id`` is the primary key). ``enabled=False`` means
setup has started but has not been confirmed; ``enabled=True`` means TOTP
MUST be enforced during login.

Before this feature is production-complete, add an account-recovery mechanism
(e.g. recovery codes). Without recovery, a user who permanently loses their
authenticator device can be locked out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hypatia.extensions import db
from hypatia.models.user import _utcnow

if TYPE_CHECKING:
    from hypatia.models.user import User


class TOTPMethod(db.Model):
    __tablename__ = "totp_methods"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_timecode: Mapped[int | None] = mapped_column(BigInteger)

    user: Mapped[User] = relationship(back_populates="totp_method")
