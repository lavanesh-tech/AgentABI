"""GitHub webhook signature verification — pure unit tests (Security
Phase E spec §24). `app/github/webhook_signature.py` has no FastAPI/
SQLAlchemy import, so this runs for real via `pytest --noconftest`.
"""

from app.github.webhook_signature import compute_payload_hash, compute_signature, verify_signature

_SECRET = "test-webhook-secret"  # fake value only — never a real secret
_PAYLOAD = b'{"zen": "Keep it logically awesome."}'


def test_valid_signature_is_accepted():
    header = compute_signature(_SECRET, _PAYLOAD)
    assert verify_signature(_SECRET, _PAYLOAD, header) is True


def test_wrong_secret_is_rejected():
    header = compute_signature("a-different-secret", _PAYLOAD)
    assert verify_signature(_SECRET, _PAYLOAD, header) is False


def test_missing_signature_is_rejected():
    assert verify_signature(_SECRET, _PAYLOAD, None) is False
    assert verify_signature(_SECRET, _PAYLOAD, "") is False


def test_malformed_prefix_is_rejected():
    digest = compute_signature(_SECRET, _PAYLOAD).removeprefix("sha256=")
    assert verify_signature(_SECRET, _PAYLOAD, f"sha1={digest}") is False
    assert verify_signature(_SECRET, _PAYLOAD, digest) is False  # no prefix at all


def test_malformed_digest_is_rejected():
    assert verify_signature(_SECRET, _PAYLOAD, "sha256=not-hex-at-all") is False
    assert verify_signature(_SECRET, _PAYLOAD, "sha256=deadbeef") is False  # too short
    assert verify_signature(_SECRET, _PAYLOAD, "sha256=" + "g" * 64) is False  # non-hex chars


def test_modified_body_after_signing_is_rejected():
    header = compute_signature(_SECRET, _PAYLOAD)
    tampered = _PAYLOAD + b" "
    assert verify_signature(_SECRET, tampered, header) is False


def test_exact_body_bytes_are_required_not_a_reparsed_equivalent():
    # Two byte sequences that decode to "the same" JSON object are NOT
    # interchangeable for signature purposes (spec §5) — whitespace
    # alone must invalidate a signature computed over the original.
    payload = b'{"a":1,"b":2}'
    respaced = b'{"a": 1, "b": 2}'
    header = compute_signature(_SECRET, payload)
    assert verify_signature(_SECRET, payload, header) is True
    assert verify_signature(_SECRET, respaced, header) is False


def test_constant_time_compare_path_is_used():
    # Behavioral proxy for "uses hmac.compare_digest": verification
    # must still return a clean False for a digest that differs only in
    # its very last character (early-exit `==` and constant-time
    # compare both fail here either way, but this guards against a
    # naive prefix/substring check that might short-circuit oddly).
    header = compute_signature(_SECRET, _PAYLOAD)
    almost = header[:-1] + ("0" if header[-1] != "0" else "1")
    assert verify_signature(_SECRET, _PAYLOAD, almost) is False


def test_compute_payload_hash_is_deterministic_and_sensitive_to_content():
    a = compute_payload_hash(b"hello")
    b = compute_payload_hash(b"hello")
    c = compute_payload_hash(b"hello!")
    assert a == b
    assert a != c
    assert len(a) == 64  # hex-encoded SHA-256
