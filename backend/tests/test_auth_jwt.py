"""Pure unit tests for `app/auth/jwt.py`. No database, no I/O, no
network — stdlib HS256 only."""

import uuid

import pytest

from app.auth.jwt import decode_token, encode_token
from app.domain.exceptions import ExpiredToken, InvalidToken

SECRET = "test-secret"
ISSUER = "agentabi"
AUDIENCE = "agentabi-api"
USER_ID = str(uuid.uuid4())


def _issue(**overrides):
    kwargs = {
        "subject": USER_ID,
        "secret": SECRET,
        "algorithm": "HS256",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "expires_in_seconds": 3600,
    }
    kwargs.update(overrides)
    return encode_token(**kwargs)


def test_valid_token_round_trips():
    token = _issue(organization_id="org-1")
    claims = decode_token(token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)
    assert claims.sub == USER_ID
    assert claims.org_id == "org-1"
    assert claims.iss == ISSUER
    assert claims.aud == AUDIENCE


def test_token_without_organization_id_has_no_org_claim():
    token = _issue()
    claims = decode_token(token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)
    assert claims.org_id is None


def test_expired_token_raises_expired_token():
    token = _issue(expires_in_seconds=-10)
    with pytest.raises(ExpiredToken):
        decode_token(token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)


def test_malformed_token_raises_invalid_token():
    with pytest.raises(InvalidToken):
        decode_token(
            "not-a-jwt", secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE
        )


def test_two_part_token_raises_invalid_token():
    with pytest.raises(InvalidToken):
        decode_token("a.b", secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)


def test_tampered_signature_raises_invalid_token():
    token = _issue()
    header, payload, signature = token.split(".")
    # Flip the *first* signature character rather than the last: the
    # last base64url character of a 32-byte digest encodes some
    # discarded padding bits, so altering it can (data-dependently)
    # decode to the same bytes and make this assertion flaky.
    flipped = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{flipped}{signature[1:]}"
    with pytest.raises(InvalidToken):
        decode_token(tampered, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)


def test_wrong_secret_raises_invalid_token():
    token = _issue()
    with pytest.raises(InvalidToken):
        decode_token(
            token, secret="wrong-secret", algorithm="HS256", issuer=ISSUER, audience=AUDIENCE
        )


def test_wrong_issuer_raises_invalid_token():
    token = _issue()
    with pytest.raises(InvalidToken):
        decode_token(
            token, secret=SECRET, algorithm="HS256", issuer="someone-else", audience=AUDIENCE
        )


def test_wrong_audience_raises_invalid_token():
    token = _issue()
    with pytest.raises(InvalidToken):
        decode_token(
            token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience="someone-else"
        )


def test_missing_required_claim_raises_invalid_token():
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(
        b"="
    )
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": USER_ID, "iss": ISSUER}).encode()  # missing aud/iat/exp
    ).rstrip(b"=")
    import hashlib
    import hmac as hmac_mod

    signing_input = header + b"." + payload
    sig = base64.urlsafe_b64encode(
        hmac_mod.new(SECRET.encode(), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    token = b".".join([header, payload, sig]).decode()
    with pytest.raises(InvalidToken):
        decode_token(token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)


def test_alg_none_is_rejected():
    """Algorithm-confusion / 'none' attack: a header claiming alg=none
    (or anything but HS256) must never be accepted, even with a
    signature segment supplied."""

    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(
        b"="
    )
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"sub": USER_ID, "iss": ISSUER, "aud": AUDIENCE, "iat": 0, "exp": 99999999999}
        ).encode()
    ).rstrip(b"=")
    token = (header + b"." + payload + b".").decode()
    with pytest.raises(InvalidToken):
        decode_token(token, secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)


def test_encode_rejects_unsupported_algorithm():
    with pytest.raises(InvalidToken):
        _issue(algorithm="RS256")
