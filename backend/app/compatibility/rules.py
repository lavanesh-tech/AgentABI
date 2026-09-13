"""Deterministic classification/severity rules. This module — plain
lookup tables and a handful of small pure functions — is the ONLY place
that decides whether a detected change is compatible, potentially
breaking, or breaking, and how severe it is. `diff.py` never assigns a
classification itself; it always calls into here. No LLM is involved
anywhere in this file or anything it's called from.

See docs/DECISIONS.md for the full input-vs-output direction rationale;
this module is the executable form of that decision, not a re-derivation
of it.
"""

from app.compatibility.models import (
    Change,
    ChangeType,
    Classification,
    CompatibilityStatus,
    Direction,
    Severity,
)

CT = ChangeType
CL = Classification
SV = Severity
DIR = Direction

# --- Structured schema changes: classification depends on Direction ---
#
# Read each row as: "this change, on an INPUT/OUTPUT/NEUTRAL schema, means
# this". NEUTRAL (a standalone `SCHEMA` component whose usage as someone's
# input or output isn't known here) is deliberately the more conservative
# of the two directional readings for every change type, never the more
# lenient one — an unknown direction should never look safer than either
# known direction.
_SCHEMA_RULES: dict[tuple[ChangeType, Direction], tuple[Classification, Severity]] = {
    (CT.FIELD_ADDED, DIR.INPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.FIELD_ADDED, DIR.OUTPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.FIELD_ADDED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.LOW),
    (CT.FIELD_REMOVED, DIR.INPUT): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.FIELD_REMOVED, DIR.OUTPUT): (CL.BREAKING, SV.HIGH),
    (CT.FIELD_REMOVED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    # A brand-new required INPUT field is the one case this engine treats
    # as CRITICAL rather than HIGH: every existing caller that doesn't
    # already send it is guaranteed to fail, not merely likely to.
    (CT.REQUIRED_FIELD_ADDED, DIR.INPUT): (CL.BREAKING, SV.CRITICAL),
    (CT.REQUIRED_FIELD_ADDED, DIR.OUTPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.REQUIRED_FIELD_ADDED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.REQUIRED_FIELD_REMOVED, DIR.INPUT): (CL.COMPATIBLE, SV.LOW),
    (CT.REQUIRED_FIELD_REMOVED, DIR.OUTPUT): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.REQUIRED_FIELD_REMOVED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.LOW),
    (CT.TYPE_CHANGED, DIR.INPUT): (CL.BREAKING, SV.HIGH),
    (CT.TYPE_CHANGED, DIR.OUTPUT): (CL.BREAKING, SV.HIGH),
    (CT.TYPE_CHANGED, DIR.NEUTRAL): (CL.BREAKING, SV.HIGH),
    (CT.NULLABLE_TO_NON_NULLABLE, DIR.INPUT): (CL.BREAKING, SV.HIGH),
    (CT.NULLABLE_TO_NON_NULLABLE, DIR.OUTPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.NULLABLE_TO_NON_NULLABLE, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.NON_NULLABLE_TO_NULLABLE, DIR.INPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.NON_NULLABLE_TO_NULLABLE, DIR.OUTPUT): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.NON_NULLABLE_TO_NULLABLE, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.LOW),
    (CT.ENUM_VALUE_ADDED, DIR.INPUT): (CL.COMPATIBLE, SV.INFO),
    (CT.ENUM_VALUE_ADDED, DIR.OUTPUT): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.ENUM_VALUE_ADDED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.LOW),
    (CT.ENUM_VALUE_REMOVED, DIR.INPUT): (CL.BREAKING, SV.HIGH),
    (CT.ENUM_VALUE_REMOVED, DIR.OUTPUT): (CL.COMPATIBLE, SV.LOW),
    (CT.ENUM_VALUE_REMOVED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.ENUM_NARROWED, DIR.INPUT): (CL.BREAKING, SV.HIGH),
    (CT.ENUM_NARROWED, DIR.OUTPUT): (CL.COMPATIBLE, SV.LOW),
    (CT.ENUM_NARROWED, DIR.NEUTRAL): (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    (CT.ARRAY_ITEM_TYPE_CHANGED, DIR.INPUT): (CL.BREAKING, SV.HIGH),
    (CT.ARRAY_ITEM_TYPE_CHANGED, DIR.OUTPUT): (CL.BREAKING, SV.HIGH),
    (CT.ARRAY_ITEM_TYPE_CHANGED, DIR.NEUTRAL): (CL.BREAKING, SV.HIGH),
}

# Constraint keys where a *larger* value is stricter/tighter (raising the
# floor); the complementary set (below) is where a *smaller* value is
# tighter (lowering the ceiling). Anything not in either set (e.g.
# `pattern`, `multipleOf`) has an ambiguous tightening direction and is
# classified conservatively regardless of direction — see
# `classify_constraint_change`.
_TIGHTENS_WHEN_LARGER = frozenset(
    {"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"}
)
_TIGHTENS_WHEN_SMALLER = frozenset(
    {"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"}
)

# Generic (non-directional) config/mapping-level and per-component facts.
# These don't have an INPUT/OUTPUT reading the way a schema field does —
# each is classified once, conservatively, reflecting "this changed and
# the behavioral impact isn't fully knowable from static comparison alone
# (that's what Phase 7's replay engine is for)".
_GENERIC_RULES: dict[ChangeType, tuple[Classification, Severity]] = {
    CT.CONFIG_FIELD_ADDED: (CL.COMPATIBLE, SV.INFO),
    CT.CONFIG_FIELD_REMOVED: (CL.POTENTIALLY_BREAKING, SV.LOW),
    CT.VALUE_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.CONTENT_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    # A prompt's `variables` list is treated as an implicit input contract
    # (the set of substitutions a caller must supply), so these mirror the
    # INPUT-direction schema rules for REQUIRED_FIELD_ADDED/REMOVED above.
    CT.VARIABLE_ADDED: (CL.BREAKING, SV.HIGH),
    CT.VARIABLE_REMOVED: (CL.COMPATIBLE, SV.LOW),
    CT.PROVIDER_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.MODEL_IDENTIFIER_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.PARAMETER_CHANGED: (CL.POTENTIALLY_BREAKING, SV.LOW),
    CT.MODEL_REF_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.PROMPT_REF_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.TOOL_ADDED: (CL.COMPATIBLE, SV.INFO),
    CT.TOOL_REMOVED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.DESCRIPTION_CHANGED: (CL.COMPATIBLE, SV.INFO),
    CT.ENDPOINT_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.TRANSPORT_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.SERVER_NAME_CHANGED: (CL.COMPATIBLE, SV.INFO),
    CT.BASE_URL_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    # A changed HTTP method is a hard contract break for every existing
    # caller — no partial-compatibility reading makes sense.
    CT.METHOD_CHANGED: (CL.BREAKING, SV.HIGH),
    CT.AUTH_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.STEP_ADDED: (CL.COMPATIBLE, SV.INFO),
    CT.STEP_REMOVED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.STEP_ORDER_CHANGED: (CL.POTENTIALLY_BREAKING, SV.LOW),
    CT.REQUIRED_STEP_REMOVED: (CL.BREAKING, SV.HIGH),
    CT.WORKFLOW_CONFIG_CHANGED: (CL.POTENTIALLY_BREAKING, SV.LOW),
    CT.RULE_ADDED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.RULE_REMOVED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
    CT.RULE_CHANGED: (CL.POTENTIALLY_BREAKING, SV.MEDIUM),
}


def classify(change_type: ChangeType, direction: Direction) -> tuple[Classification, Severity]:
    """The single entry point `diff.py` uses for every non-constraint
    change. Raises `KeyError` (a programming error, not a domain error —
    every `(ChangeType, Direction)` pair `diff.py` can produce must have
    an entry here) if the combination isn't registered."""

    if (change_type, direction) in _SCHEMA_RULES:
        return _SCHEMA_RULES[(change_type, direction)]
    return _GENERIC_RULES[change_type]


def constraint_tightened(key: str, old_value: object, new_value: object) -> bool | None:
    """Whether changing constraint `key` from `old_value` to `new_value`
    made the constraint stricter (True), looser (False), or the direction
    is ambiguous/unknown for this key (None — e.g. `pattern`,
    `multipleOf`, or a key not modeled here at all)."""

    if key in _TIGHTENS_WHEN_LARGER and _both_numeric(old_value, new_value):
        return new_value > old_value  # type: ignore[operator]
    if key in _TIGHTENS_WHEN_SMALLER and _both_numeric(old_value, new_value):
        return new_value < old_value  # type: ignore[operator]
    if key == "uniqueItems":
        # False -> True adds a constraint (tighter); True -> False removes
        # one (looser).
        if old_value is False and new_value is True:
            return True
        if old_value is True and new_value is False:
            return False
    return None


def classify_constraint_change(
    direction: Direction, tightened: bool | None
) -> tuple[Classification, Severity]:
    """Classification for `CONSTRAINT_CHANGED`, which — unlike every other
    schema change type — needs a third input (whether the change tightened
    or loosened the constraint) alongside direction."""

    if tightened is None:
        # Ambiguous direction (e.g. `pattern` changed to a different
        # regex): treat as uncertain-but-worth-flagging in every context,
        # same as the NEUTRAL schema-direction default.
        return (CL.POTENTIALLY_BREAKING, SV.MEDIUM)
    if direction == DIR.INPUT:
        return (CL.POTENTIALLY_BREAKING, SV.MEDIUM) if tightened else (CL.COMPATIBLE, SV.INFO)
    if direction == DIR.OUTPUT:
        return (CL.COMPATIBLE, SV.LOW) if tightened else (CL.POTENTIALLY_BREAKING, SV.MEDIUM)
    return (CL.POTENTIALLY_BREAKING, SV.LOW)  # NEUTRAL


def _both_numeric(a: object, b: object) -> bool:
    is_a_number = isinstance(a, int | float) and not isinstance(a, bool)
    is_b_number = isinstance(b, int | float) and not isinstance(b, bool)
    return is_a_number and is_b_number


def derive_status(changes: tuple[Change, ...]) -> CompatibilityStatus:
    """Scan-level rollup: the worst classification among all changes wins.
    Zero changes (identical content) is COMPATIBLE."""

    if any(c.classification == Classification.BREAKING for c in changes):
        return CompatibilityStatus.BREAKING
    if any(c.classification == Classification.POTENTIALLY_BREAKING for c in changes):
        return CompatibilityStatus.WARNING
    return CompatibilityStatus.COMPATIBLE
