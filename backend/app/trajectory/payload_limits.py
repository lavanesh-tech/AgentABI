"""Payload size safeguards for recorded trajectory events (Phase 6 §10).

Two thresholds, deliberately different mechanisms:

- Below `DEFAULT_SOFT_LIMIT_BYTES`: stored as-is.
- Between the soft and `DEFAULT_HARD_LIMIT_BYTES`: stored as a
  deterministic truncated representation, with the original size and a
  `truncated=True` flag recorded alongside it — still useful evidence,
  just not the full payload.
- Above the hard limit: rejected outright (`TrajectoryPayloadTooLarge`).
  Even producing a truncated representation requires canonicalizing the
  whole payload in memory; an unbounded input has no business being
  accepted as inline evidence at any size.

No S3/external archival here (Phase 6 §10 explicitly defers that) — this
is the "safe, understandable" foundation the spec asks for; a future
phase can replace the hard-limit rejection with an archival upload
without changing this module's call sites.
"""

import json
from typing import Any

from app.domain.exceptions import TrajectoryPayloadTooLarge

DEFAULT_SOFT_LIMIT_BYTES = 32_768  # 32 KiB — stored in full below this
DEFAULT_HARD_LIMIT_BYTES = 1_048_576  # 1 MiB — rejected above this

TRUNCATION_PREVIEW_CHARS = 2_048


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def canonical_size_bytes(value: Any) -> int:
    """Deterministic byte size of a payload, used for both the size
    check and (via the same serialization) the truncation preview —
    the two never disagree about what "the payload" was."""

    return len(_canonical_json(value).encode("utf-8"))


def enforce_payload_limit(
    value: Any,
    *,
    field_name: str,
    soft_limit_bytes: int = DEFAULT_SOFT_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> tuple[Any, bool, int | None]:
    """Returns `(stored_value, truncated, original_size_bytes)`.

    `original_size_bytes` is `None` when no truncation happened (the
    common case) — callers should only surface it when `truncated` is
    True, keeping untruncated events' evidence free of noise fields.
    """

    if value is None:
        return None, False, None

    size = canonical_size_bytes(value)
    if size <= soft_limit_bytes:
        return value, False, None

    if size > hard_limit_bytes:
        raise TrajectoryPayloadTooLarge(field_name, size, hard_limit_bytes)

    preview = _canonical_json(value)[:TRUNCATION_PREVIEW_CHARS]
    truncated_value = {
        "_truncated": True,
        "_original_size_bytes": size,
        "_preview": preview,
    }
    return truncated_value, True, size
