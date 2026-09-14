"""GitHub webhook HMAC-SHA256 signature verification (Security Phase E
spec §6). Pure stdlib (`hmac`, `hashlib`) — no FastAPI/SQLAlchemy
import, so this is `pytest --noconftest`-testable, same testability
choice as `app/auth/jwt.py`/`app/authz/permissions.py`.

Verification always runs against the exact raw request body bytes
(spec §5) — never a re-serialized/re-parsed JSON representation, which
could differ byte-for-byte from what GitHub actually signed (key
ordering, whitespace, unicode escaping) even while decoding to an
"equivalent" object.
"""

import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="
_HEX_DIGEST_LENGTH = 64  # SHA-256 -> 32 bytes -> 64 hex chars
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def compute_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, payload: bytes, header_value: str | None) -> bool:
    """Constant-time verification. Returns False (never raises) for any
    malformed input — missing header, wrong prefix, wrong-length or
    non-hex digest — so callers get one uniform "invalid" outcome
    without needing to distinguish failure shapes (mirrors
    `InvalidToken`'s ADR-032 precedent: telling an attacker *which*
    validation step failed would help them probe the verifier)."""

    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        return False
    provided_hex = header_value[len(_SIGNATURE_PREFIX) :]
    if len(provided_hex) != _HEX_DIGEST_LENGTH or not all(c in _HEX_DIGITS for c in provided_hex):
        return False

    expected = compute_signature(secret, payload)
    expected_hex = expected[len(_SIGNATURE_PREFIX) :]
    # hmac.compare_digest, not `==` — constant-time regardless of where
    # the strings first differ (spec §6).
    return hmac.compare_digest(provided_hex.lower(), expected_hex.lower())


def compute_payload_hash(payload: bytes) -> str:
    """Deterministic SHA-256 hash of the raw payload bytes, used for
    delivery-idempotency conflict detection (spec §8/§9) — a cheap,
    fixed-size fingerprint stored instead of the full payload."""

    return hashlib.sha256(payload).hexdigest()
