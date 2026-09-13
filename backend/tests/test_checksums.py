"""Pure unit tests for deterministic content checksums — no database
required."""

from app.domain.checksums import compute_checksum


def test_checksum_is_deterministic_regardless_of_key_order():
    a = compute_checksum({"b": 1, "a": 2})
    b = compute_checksum({"a": 2, "b": 1})
    assert a == b


def test_checksum_is_deterministic_across_repeated_calls():
    content = {"template": "hello", "variables": ["name"]}
    assert compute_checksum(content) == compute_checksum(content)


def test_checksum_changes_when_content_changes():
    a = compute_checksum({"template": "hello"})
    b = compute_checksum({"template": "hello world"})
    assert a != b


def test_checksum_is_a_sha256_hex_digest():
    digest = compute_checksum({"x": 1})
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_checksum_distinguishes_nested_structures():
    a = compute_checksum({"tools": [{"name": "a"}, {"name": "b"}]})
    b = compute_checksum({"tools": [{"name": "b"}, {"name": "a"}]})
    assert a != b
