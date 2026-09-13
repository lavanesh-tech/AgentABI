"""Normalize JSON-Schema-like dicts before comparison, so textual
differences that carry no semantic meaning (key order, an unsorted
`required` list, duplicate enum entries) never show up as a detected
change. This is deliberately narrower than "canonicalize everything" —
see module docstring notes inline for what is and isn't touched, and
docs/DECISIONS.md for why Phase 3's content checksum alone can't serve
this purpose (it proves content changed, never *how*).
"""

from typing import Any

from app.domain.exceptions import SchemaNormalizationError

# Recursion is bounded so a malformed/cyclic-looking schema (accidentally
# self-referential via a shared, then-mutated dict; a very deeply nested
# adversarial payload) fails loudly and cheaply instead of hanging or
# blowing the stack.
_MAX_DEPTH = 64


def normalize_schema(schema: Any, *, _depth: int = 0) -> Any:
    """Return a new, normalized copy of `schema`. Does not mutate the
    input. Non-dict/list/scalar JSON values pass through unchanged; a
    boolean schema (`true`/`false`, valid JSON Schema) passes through as
    the corresponding Python `bool`.
    """

    if _depth > _MAX_DEPTH:
        raise SchemaNormalizationError(f"exceeds max normalization depth ({_MAX_DEPTH})")

    if isinstance(schema, bool):
        return schema
    if isinstance(schema, dict):
        return _normalize_object(schema, _depth=_depth)
    if isinstance(schema, list):
        return [normalize_schema(item, _depth=_depth + 1) for item in schema]
    return schema


def _normalize_object(schema: dict[str, Any], *, _depth: int) -> dict[str, Any]:
    normalized: dict[str, Any] = {}

    for key, value in schema.items():
        if key == "required" and isinstance(value, list):
            # Stable property ordering: which fields are required is a
            # set, not a sequence — sort + dedupe so `["b", "a"]` and
            # `["a", "b", "a"]` normalize identically.
            normalized[key] = sorted(dict.fromkeys(value))
        elif key == "type" and isinstance(value, list):
            # `{"type": ["string", "null"]}` vs `{"type": ["null",
            # "string"]}` are the same schema; a single-element list is
            # equivalent to the bare string form.
            deduped = sorted(dict.fromkeys(value))
            normalized[key] = deduped[0] if len(deduped) == 1 else deduped
        elif key == "properties" and isinstance(value, dict):
            normalized[key] = {
                prop_name: normalize_schema(prop_schema, _depth=_depth + 1)
                for prop_name, prop_schema in value.items()
            }
        elif key == "items":
            normalized[key] = normalize_schema(value, _depth=_depth + 1)
        elif key == "enum" and isinstance(value, list):
            # Order is preserved (not semantically meaningless — see
            # diff.py's enum handling) but exact duplicates are collapsed.
            seen: list[Any] = []
            for item in value:
                if item not in seen:
                    seen.append(item)
            normalized[key] = seen
        else:
            normalized[key] = normalize_schema(value, _depth=_depth + 1)

    return normalized
