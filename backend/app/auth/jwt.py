"""Minimal, dependency-free HS256 JWT (RFC 7519/7515 JWS compact
serialization) — stdlib `hmac`/`hashlib`/`base64`/`json` only.

Why not PyJWT/authlib: this sandbox cannot install packages (every prior
phase's ADR-005/006/008/... documents the same PyPI 403), and the rest
of this codebase's pure-logic modules (`app/compatibility/`,
`app/trajectory/`, `app/replay/`) already establish the pattern of
keeping security/business-critical logic stdlib-only so it's genuinely
`pytest`-executable in this environment. HS256 is a small, well-specified
surface: one algorithm (fixed — never read from the token, closing the
classic "alg: none" / algorithm-confusion attack class outright), one
constant-time signature comparison (`hmac.compare_digest`). See
docs/DECISIONS.md for the decision to keep this in place going forward
vs. swapping to a vetted library once dependencies are installable.

Every failure mode raises a specific `app.domain.exceptions` error —
callers never see a raw `KeyError`/`ValueError`/`binascii.Error`.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.auth.claims import REQUIRED_CLAIM_KEYS, JWTClaims
from app.domain.exceptions import ExpiredToken, InvalidToken

_HEADER = {"alg": "HS256", "typ": "JWT"}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding)
    except (ValueError, TypeError) as exc:
        raise InvalidToken("token is not valid base64url") from exc


def encode_token(
    *,
    subject: str,
    secret: str,
    algorithm: str,
    issuer: str,
    audience: str,
    expires_in_seconds: int,
    organization_id: str | None = None,
    now: int | None = None,
) -> str:
    """Issue a signed token. `algorithm` must be `"HS256"` — passed
    explicitly (not read from settings here) so callers can't
    accidentally sign with something this module doesn't also verify."""

    if algorithm != "HS256":
        raise InvalidToken(f"unsupported signing algorithm {algorithm!r}")

    issued_at = now if now is not None else int(time.time())
    claims = JWTClaims(
        sub=subject,
        iss=issuer,
        aud=audience,
        iat=issued_at,
        exp=issued_at + expires_in_seconds,
        org_id=organization_id,
    )
    header_segment = _b64url_encode(json.dumps(_HEADER, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(
        json.dumps(claims.to_payload(), separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def decode_token(
    token: str,
    *,
    secret: str,
    algorithm: str,
    issuer: str,
    audience: str,
    now: int | None = None,
) -> JWTClaims:
    """Verify and decode a token. Fails closed and specifically for every
    documented failure mode (Phase A spec §5): malformed structure,
    invalid signature, expiry, wrong issuer, wrong audience, missing
    required claims — never a bare/uncaught parse exception."""

    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidToken("token is not a three-part JWS compact serialization")
    header_segment, payload_segment, signature_segment = parts

    header = _parse_json_segment(header_segment, what="header")
    if header.get("alg") != "HS256" or algorithm != "HS256":
        raise InvalidToken("unsupported or mismatched signing algorithm")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_signature = _b64url_decode(signature_segment)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise InvalidToken("signature verification failed")

    payload = _parse_json_segment(payload_segment, what="payload")

    missing = REQUIRED_CLAIM_KEYS - payload.keys()
    if missing:
        raise InvalidToken(f"token is missing required claims: {sorted(missing)}")

    if payload["iss"] != issuer:
        raise InvalidToken("token issuer does not match")
    if payload["aud"] != audience:
        raise InvalidToken("token audience does not match")

    current_time = now if now is not None else int(time.time())
    try:
        expires_at = int(payload["exp"])
        issued_at = int(payload["iat"])
    except (TypeError, ValueError) as exc:
        raise InvalidToken("token has non-numeric iat/exp claims") from exc
    if current_time >= expires_at:
        raise ExpiredToken()

    return JWTClaims(
        sub=str(payload["sub"]),
        iss=str(payload["iss"]),
        aud=str(payload["aud"]),
        iat=issued_at,
        exp=expires_at,
        org_id=str(payload["org_id"]) if payload.get("org_id") is not None else None,
    )


def _parse_json_segment(segment: str, *, what: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_b64url_decode(segment))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidToken(f"token {what} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidToken(f"token {what} must be a JSON object")
    return parsed
