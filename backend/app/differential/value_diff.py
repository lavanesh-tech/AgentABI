"""Deterministic, recursive comparison of two JSON-like values (spec
§10/§11). Pure function — no I/O, no randomness. Dict/list/scalar
type-aware; missing-vs-null stays distinguishable (a dict comparison
checks key *presence*, never `dict.get(key) is not None`); sensitive
fields are compared on their raw value (to correctly detect a change)
but never exposed raw in the output (spec §12) — reuses
`app.trajectory.redaction`'s sensitive-key set rather than duplicating it.
"""

from typing import Any

from app.differential.models import DifferenceType, FieldDifference
from app.trajectory.redaction import DEFAULT_SENSITIVE_KEYS, REDACTED_PLACEHOLDER, sanitize

_MAX_DEPTH = 64


def diff_values(
    baseline: Any, candidate: Any, *, path: str = "$", _depth: int = 0
) -> list[FieldDifference]:
    if _depth > _MAX_DEPTH:
        return []

    if isinstance(baseline, dict) and isinstance(candidate, dict):
        return _diff_dict(baseline, candidate, path=path, depth=_depth)
    if isinstance(baseline, list) and isinstance(candidate, list):
        return _diff_list(baseline, candidate, path=path, depth=_depth)
    if type(baseline) is not type(candidate):
        return [
            FieldDifference(
                difference_type=DifferenceType.SCHEMA_CHANGED,
                path=path,
                old_value=_display(baseline),
                new_value=_display(candidate),
                evidence={"reason": "type_changed"},
            )
        ]
    if baseline != candidate:
        return [
            FieldDifference(
                difference_type=DifferenceType.VALUE_CHANGED,
                path=path,
                old_value=_display(baseline),
                new_value=_display(candidate),
            )
        ]
    return []


def _diff_dict(
    baseline: dict[str, Any], candidate: dict[str, Any], *, path: str, depth: int
) -> list[FieldDifference]:
    diffs: list[FieldDifference] = []
    # Deterministic ordering (spec §33): sorted key iteration, never
    # dict insertion order (which can legitimately differ between two
    # otherwise-identical payloads — spec §28's "reordered dict keys").
    for key in sorted(set(baseline) - set(candidate)):
        diffs.append(_removed_field(f"{path}.{key}", baseline[key]))
    for key in sorted(set(candidate) - set(baseline)):
        diffs.append(_added_field(f"{path}.{key}", candidate[key]))
    for key in sorted(set(baseline) & set(candidate)):
        field_path = f"{path}.{key}"
        if _is_sensitive(key):
            if baseline[key] != candidate[key]:
                diffs.append(
                    FieldDifference(
                        difference_type=DifferenceType.VALUE_CHANGED,
                        path=field_path,
                        old_value=REDACTED_PLACEHOLDER,
                        new_value=REDACTED_PLACEHOLDER,
                        redacted=True,
                    )
                )
            continue
        diffs.extend(diff_values(baseline[key], candidate[key], path=field_path, _depth=depth + 1))
    return diffs


def _diff_list(
    baseline: list[Any], candidate: list[Any], *, path: str, depth: int
) -> list[FieldDifference]:
    diffs: list[FieldDifference] = []
    common = min(len(baseline), len(candidate))
    for i in range(common):
        diffs.extend(diff_values(baseline[i], candidate[i], path=f"{path}[{i}]", _depth=depth + 1))
    for i in range(common, len(baseline)):
        diffs.append(_removed_field(f"{path}[{i}]", baseline[i]))
    for i in range(common, len(candidate)):
        diffs.append(_added_field(f"{path}[{i}]", candidate[i]))
    return diffs


def _removed_field(path: str, value: Any) -> FieldDifference:
    return FieldDifference(
        difference_type=DifferenceType.SCHEMA_CHANGED,
        path=path,
        old_value=_display(value),
        new_value=None,
        evidence={"reason": "field_removed"},
    )


def _added_field(path: str, value: Any) -> FieldDifference:
    return FieldDifference(
        difference_type=DifferenceType.SCHEMA_CHANGED,
        path=path,
        old_value=None,
        new_value=_display(value),
        evidence={"reason": "field_added"},
    )


def _is_sensitive(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in DEFAULT_SENSITIVE_KEYS


def _display(value: Any) -> Any:
    """Sanitizes any nested sensitive keys before a value is recorded on
    a `FieldDifference` — matters when an entire added/removed subtree
    (spec §8/§12) is a dict/list that itself contains sensitive fields
    at a deeper level than the diff walked (e.g. a whole newly-added
    `headers` object containing `authorization`)."""

    return sanitize(value)
