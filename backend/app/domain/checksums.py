"""Deterministic content checksums for component versions.

Canonicalizes a content dict (sorted keys, compact separators, UTF-8) and
SHA-256 hashes it, so semantically identical content always produces the
same checksum regardless of key order — and the checksum never depends on
volatile fields (timestamps, database IDs, sequence numbers) because those
never appear in `content`; they live in dedicated columns, not the
payload. This is what later phases use for cheap "did anything actually
change" checks before running a full compatibility scan.
"""

import hashlib
import json
from typing import Any


def canonicalize_content(content: dict[str, Any]) -> str:
    """Stable JSON serialization: sorted keys, no extraneous whitespace."""

    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(content: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonicalized content."""

    canonical = canonicalize_content(content)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
