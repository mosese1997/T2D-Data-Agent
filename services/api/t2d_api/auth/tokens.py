"""Stateless auth tokens: itsdangerous-signed userid with expiry.

HTTP demo environment: no Secure cookie flag (would require HTTPS — task
book §6). Bearer header is the primary transport; cookies optional.
"""

from __future__ import annotations

from datetime import timedelta

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from ..settings import settings

_SIGNER = None


def _signer() -> TimestampSigner:
    global _SIGNER
    if _SIGNER is None:
        _SIGNER = TimestampSigner(settings.secret_key)
    return _SIGNER


def issue_token(user_id: int) -> str:
    return _signer().sign(str(user_id)).decode()


def verify_token(token: str) -> int | None:
    """Return user_id or None (invalid/expired)."""
    try:
        # itsdangerous expects max_age in integer seconds.
        payload = _signer().unsign(token, max_age=settings.token_ttl_hours * 3600)
        return int(payload.decode())
    except (BadSignature, SignatureExpired, ValueError):
        return None
