"""Deterministic integrity hash for a trajectory event (Phase 6 §18),
reusing the exact canonicalization Phase 3 established
(`app.domain.checksums.canonicalize_content`) rather than inventing a
second hashing scheme. A SHA-256 digest over the replay-relevant fields
— everything a future replay would need to reproduce/verify this step —
is sufficient; this is audit/integrity evidence, not a cryptographic
commitment scheme.

Deliberately excluded from the hash: `id`, `recorded_at`,
`payload_truncated`/`payload_original_size_bytes` (an artifact of this
session's size limits, not of what happened), and `parent_event_id` (a
linkage detail, not part of "what this step was"). Included:
`trajectory_id`, `sequence_number`, `event_type`, the component version
actually used, and the (already-redacted, possibly-truncated)
input/output/error payloads — this is also why event idempotency
(Phase 6 §14) can use this same hash to detect "identical retry" vs.
"conflicting reuse of the same external_event_id" for free.
"""

import hashlib
import uuid
from typing import Any

from app.domain.checksums import canonicalize_content


def compute_event_hash(
    *,
    trajectory_id: uuid.UUID,
    sequence_number: int,
    event_type: str,
    component_version_id: uuid.UUID | None,
    input_payload: Any,
    output_payload: Any,
    error_payload: Any,
) -> str:
    canonical = canonicalize_content(
        {
            "trajectory_id": str(trajectory_id),
            "sequence_number": sequence_number,
            "event_type": event_type,
            "component_version_id": str(component_version_id) if component_version_id else None,
            "input": input_payload,
            "output": output_payload,
            "error": error_payload,
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
