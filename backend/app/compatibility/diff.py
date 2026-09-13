"""The structured JSON-Schema-like diff engine. `diff_schemas()` is the
one recursive comparison function every schema-bearing component type
(SCHEMA, TOOL's input/output schemas) goes through; `diff_mapping()` is
the simpler generic config-level diff other component types reuse.

Both are pure functions: dict in, `list[Change]` out, no I/O, no
randomness, no wall-clock — the same two inputs always produce the exact
same output (see docs/DECISIONS.md's determinism ADR and
`test_diff.py::test_same_input_produces_same_result`).
"""

from typing import Any

from app.compatibility import rules
from app.compatibility.models import Change, ChangeType, Direction
from app.compatibility.schema_normalizer import normalize_schema

_MAX_DEPTH = 64

# Constraint keys this engine understands well enough to compare and
# reason about tightening/loosening (see rules.constraint_tightened).
# Anything not in this set is ignored — deliberately: a key AgentABI
# doesn't model isn't a "change" it can classify, and silently guessing
# would violate the no-fake-functionality rule.
_CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "multipleOf",
    "minProperties",
    "maxProperties",
)


def make_change(
    change_type: ChangeType,
    path: str,
    direction: Direction,
    *,
    old_value: Any = None,
    new_value: Any = None,
    evidence: dict[str, Any] | None = None,
    message: str | None = None,
) -> Change:
    classification, severity = rules.classify(change_type, direction)
    return Change(
        change_type=change_type,
        path=path,
        classification=classification,
        severity=severity,
        message=message or f"{change_type.value} at {path}",
        old_value=old_value,
        new_value=new_value,
        evidence=evidence or {},
    )


def _is_nullable(schema: dict[str, Any]) -> bool:
    """Supports both common conventions: JSON-Schema `type` arrays
    containing `"null"`, and the OpenAPI-3.0-style `"nullable": true`
    boolean flag."""

    schema_type = schema.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    return bool(schema.get("nullable", False))


def _non_null_type(schema: dict[str, Any]) -> Any:
    """The schema's `type`, with any `"null"` member removed — so a type
    change is compared on the *actual* type, independent of nullability
    (which is its own, separately classified change)."""

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        remaining = [t for t in schema_type if t != "null"]
        if not remaining:
            return None
        return remaining[0] if len(remaining) == 1 else sorted(remaining)
    return schema_type


def diff_schemas(
    baseline: Any,
    candidate: Any,
    direction: Direction,
    path: str = "$",
    *,
    _depth: int = 0,
) -> list[Change]:
    """Recursively compare two JSON-Schema-like structures and return
    every detected `Change`, in no particular order (callers sort — see
    `analyzer.py`). Both inputs are normalized first (see
    `schema_normalizer.py`) so non-semantic textual differences never
    appear as changes.
    """

    if _depth > _MAX_DEPTH:
        return [
            make_change(
                ChangeType.TYPE_CHANGED,
                path,
                direction,
                message=f"schema nesting exceeds max depth ({_MAX_DEPTH}); comparison truncated",
            )
        ]

    baseline = normalize_schema(baseline) if _depth == 0 else baseline
    candidate = normalize_schema(candidate) if _depth == 0 else candidate

    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        # Boolean schemas (`true`/`false`) or a malformed non-dict node:
        # compare by simple equality, nothing structural to recurse into.
        if baseline != candidate:
            return [
                make_change(
                    ChangeType.TYPE_CHANGED,
                    path,
                    direction,
                    old_value=baseline,
                    new_value=candidate,
                )
            ]
        return []

    changes: list[Change] = []

    # --- type ---
    base_type = _non_null_type(baseline)
    cand_type = _non_null_type(candidate)
    if base_type is not None and cand_type is not None and base_type != cand_type:
        changes.append(
            make_change(
                ChangeType.TYPE_CHANGED, path, direction, old_value=base_type, new_value=cand_type
            )
        )

    # --- nullability ---
    base_nullable = _is_nullable(baseline)
    cand_nullable = _is_nullable(candidate)
    if base_nullable and not cand_nullable:
        changes.append(make_change(ChangeType.NULLABLE_TO_NON_NULLABLE, path, direction))
    elif not base_nullable and cand_nullable:
        changes.append(make_change(ChangeType.NON_NULLABLE_TO_NULLABLE, path, direction))

    # --- enum ---
    changes.extend(_diff_enum(baseline.get("enum"), candidate.get("enum"), direction, path))

    # --- constraints ---
    changes.extend(_diff_constraints(baseline, candidate, direction, path))

    # --- properties / required (object schemas) ---
    changes.extend(_diff_properties(baseline, candidate, direction, path, _depth))

    # --- items (array schemas) ---
    changes.extend(_diff_items(baseline, candidate, direction, path, _depth))

    return changes


def _diff_properties(
    baseline: dict[str, Any], candidate: dict[str, Any], direction: Direction, path: str, depth: int
) -> list[Change]:
    base_props: dict[str, Any] = baseline.get("properties") or {}
    cand_props: dict[str, Any] = candidate.get("properties") or {}
    if not base_props and not cand_props:
        return []

    base_required = set(baseline.get("required") or [])
    cand_required = set(candidate.get("required") or [])

    changes: list[Change] = []
    for name in sorted(set(base_props) | set(cand_props)):
        prop_path = f"{path}.properties.{name}"
        in_base = name in base_props
        in_cand = name in cand_props
        was_required = name in base_required
        now_required = name in cand_required

        if in_base and not in_cand:
            change_type = (
                ChangeType.REQUIRED_FIELD_REMOVED if was_required else ChangeType.FIELD_REMOVED
            )
            changes.append(
                make_change(
                    change_type, prop_path, direction, old_value=base_props[name], new_value=None
                )
            )
            continue

        if not in_base and in_cand:
            change_type = (
                ChangeType.REQUIRED_FIELD_ADDED if now_required else ChangeType.FIELD_ADDED
            )
            changes.append(
                make_change(
                    change_type, prop_path, direction, old_value=None, new_value=cand_props[name]
                )
            )
            continue

        # Present on both sides: required-ness change is reported once,
        # independent of (and in addition to) any structural diff below.
        if not was_required and now_required:
            changes.append(make_change(ChangeType.REQUIRED_FIELD_ADDED, prop_path, direction))
        elif was_required and not now_required:
            changes.append(make_change(ChangeType.REQUIRED_FIELD_REMOVED, prop_path, direction))

        changes.extend(
            diff_schemas(base_props[name], cand_props[name], direction, prop_path, _depth=depth + 1)
        )

    return changes


def _diff_items(
    baseline: dict[str, Any], candidate: dict[str, Any], direction: Direction, path: str, depth: int
) -> list[Change]:
    base_items = baseline.get("items")
    cand_items = candidate.get("items")
    if base_items is None and cand_items is None:
        return []
    if base_items is None or cand_items is None:
        # One side declares item constraints, the other doesn't at all —
        # too structurally different to compare field-by-field; report it
        # as an array item type change rather than silently ignoring it.
        return [
            make_change(
                ChangeType.ARRAY_ITEM_TYPE_CHANGED,
                f"{path}[]",
                direction,
                old_value=base_items,
                new_value=cand_items,
            )
        ]

    item_path = f"{path}[]"
    nested = diff_schemas(base_items, cand_items, direction, item_path, _depth=depth + 1)

    # The item schema's own TYPE_CHANGED (if any) is the array-specific
    # fact the spec calls out by name; relabel just that one entry so it
    # reads as ARRAY_ITEM_TYPE_CHANGED instead of a generic TYPE_CHANGED.
    # Everything else about the items (nested fields, enums, constraints)
    # keeps its own, more specific change type.
    relabeled: list[Change] = []
    for change in nested:
        if change.path == item_path and change.change_type == ChangeType.TYPE_CHANGED:
            relabeled.append(
                make_change(
                    ChangeType.ARRAY_ITEM_TYPE_CHANGED,
                    change.path,
                    direction,
                    old_value=change.old_value,
                    new_value=change.new_value,
                )
            )
        else:
            relabeled.append(change)
    return relabeled


def _diff_enum(
    base_enum: list[Any] | None, cand_enum: list[Any] | None, direction: Direction, path: str
) -> list[Change]:
    if base_enum is None and cand_enum is None:
        return []
    base_set = set(base_enum or [])
    cand_set = set(cand_enum or [])
    if base_set == cand_set:
        return []

    changes: list[Change] = []
    removed = sorted(base_set - cand_set, key=str)
    added = sorted(cand_set - base_set, key=str)

    for value in removed:
        changes.append(make_change(ChangeType.ENUM_VALUE_REMOVED, path, direction, old_value=value))
    for value in added:
        changes.append(make_change(ChangeType.ENUM_VALUE_ADDED, path, direction, new_value=value))

    if removed and cand_set and cand_set < base_set:
        changes.append(
            make_change(
                ChangeType.ENUM_NARROWED,
                path,
                direction,
                old_value=sorted(base_set, key=str),
                new_value=sorted(cand_set, key=str),
                evidence={"removed": removed},
            )
        )

    return changes


def _diff_constraints(
    baseline: dict[str, Any], candidate: dict[str, Any], direction: Direction, path: str
) -> list[Change]:
    changes: list[Change] = []
    for key in _CONSTRAINT_KEYS:
        base_value = baseline.get(key)
        cand_value = candidate.get(key)
        if base_value == cand_value:
            continue
        if base_value is None and cand_value is None:
            continue
        tightened = rules.constraint_tightened(key, base_value, cand_value)
        classification, severity = rules.classify_constraint_change(direction, tightened)
        changes.append(
            Change(
                change_type=ChangeType.CONSTRAINT_CHANGED,
                path=path,
                classification=classification,
                severity=severity,
                message=f"constraint {key!r} changed at {path}",
                old_value=base_value,
                new_value=cand_value,
                evidence={"constraint": key, "tightened": tightened},
            )
        )
    return changes


def diff_mapping(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    path: str = "$",
    *,
    value_change_type: ChangeType = ChangeType.VALUE_CHANGED,
    added_type: ChangeType = ChangeType.CONFIG_FIELD_ADDED,
    removed_type: ChangeType = ChangeType.CONFIG_FIELD_REMOVED,
) -> list[Change]:
    """Generic, non-directional top-level dict diff: added/removed/
    changed keys, one `Change` per key. Used for the config-shaped parts
    of MCP server settings, model parameters, agent `system_config`,
    policy rules, and workflow config — anywhere the content is an open
    dict without a fixed, versioned schema of its own (see docs/DECISIONS.md).
    Recurses into nested dicts so a change inside a nested config object is
    reported at its own dotted path, not collapsed into a single
    top-level VALUE_CHANGED.
    """

    changes: list[Change] = []
    for key in sorted(set(baseline) | set(candidate)):
        key_path = f"{path}.{key}"
        in_base = key in baseline
        in_cand = key in candidate
        if in_base and not in_cand:
            changes.append(
                make_change(removed_type, key_path, Direction.NEUTRAL, old_value=baseline[key])
            )
        elif not in_base and in_cand:
            changes.append(
                make_change(added_type, key_path, Direction.NEUTRAL, new_value=candidate[key])
            )
        elif isinstance(baseline[key], dict) and isinstance(candidate[key], dict):
            changes.extend(
                diff_mapping(
                    baseline[key],
                    candidate[key],
                    key_path,
                    value_change_type=value_change_type,
                    added_type=added_type,
                    removed_type=removed_type,
                )
            )
        elif baseline[key] != candidate[key]:
            changes.append(
                make_change(
                    value_change_type,
                    key_path,
                    Direction.NEUTRAL,
                    old_value=baseline[key],
                    new_value=candidate[key],
                )
            )
    return changes


def sort_changes(changes: list[Change]) -> list[Change]:
    """Deterministic display/storage order: path, then change type, then
    classification. Never relies on dict/database insertion order."""

    return sorted(changes, key=lambda c: (c.path, c.change_type.value, c.classification.value))
