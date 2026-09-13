"""Pure unit tests for `app/compatibility/diff.py` — the structured
JSON-Schema-like diff engine. No database, no I/O. Assertions check exact
paths/change types/classifications, never just counts (Phase 5 §23)."""

from app.compatibility.diff import diff_mapping, diff_schemas, sort_changes
from app.compatibility.models import ChangeType, Classification, Direction


def _by_path(changes, path):
    return [c for c in changes if c.path == path]


def _types(changes):
    return {c.change_type for c in changes}


# --- input-schema compatibility ---


def test_optional_field_added_input_is_compatible():
    changes = diff_schemas(
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {"x": {"type": "string"}}},
        Direction.INPUT,
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.FIELD_ADDED
    assert changes[0].path == "$.properties.x"
    assert changes[0].classification == Classification.COMPATIBLE


def test_required_field_added_input_is_breaking():
    changes = diff_schemas(
        {"type": "object", "properties": {}, "required": []},
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        Direction.INPUT,
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.REQUIRED_FIELD_ADDED
    assert changes[0].classification == Classification.BREAKING


def test_optional_field_removed_input():
    changes = diff_schemas(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        {"type": "object", "properties": {}},
        Direction.INPUT,
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.FIELD_REMOVED


def test_required_field_removed_input_is_compatible():
    changes = diff_schemas(
        {"type": "object", "properties": {"x": {}}, "required": ["x"]},
        {"type": "object", "properties": {"x": {}}, "required": []},
        Direction.INPUT,
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.REQUIRED_FIELD_REMOVED
    assert changes[0].classification == Classification.COMPATIBLE


def test_type_changed():
    changes = diff_schemas({"type": "string"}, {"type": "integer"}, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.TYPE_CHANGED
    assert changes[0].old_value == "string"
    assert changes[0].new_value == "integer"


def test_enum_added():
    changes = diff_schemas({"enum": ["a"]}, {"enum": ["a", "b"]}, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.ENUM_VALUE_ADDED
    assert changes[0].new_value == "b"


def test_enum_removed():
    changes = diff_schemas({"enum": ["a", "b"]}, {"enum": ["a"]}, Direction.INPUT)
    types = _types(changes)
    assert ChangeType.ENUM_VALUE_REMOVED in types
    assert ChangeType.ENUM_NARROWED in types


def test_enum_narrowed_only_fires_on_strict_subset():
    # A same-size enum swap (one added, one removed) is not "narrowed".
    changes = diff_schemas({"enum": ["a", "b"]}, {"enum": ["a", "c"]}, Direction.INPUT)
    assert ChangeType.ENUM_NARROWED not in _types(changes)
    assert ChangeType.ENUM_VALUE_REMOVED in _types(changes)
    assert ChangeType.ENUM_VALUE_ADDED in _types(changes)


def test_nullability_input_non_nullable_to_nullable_is_compatible():
    changes = diff_schemas({"type": "string"}, {"type": ["string", "null"]}, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.NON_NULLABLE_TO_NULLABLE
    assert changes[0].classification == Classification.COMPATIBLE


def test_nullability_input_nullable_to_non_nullable_is_breaking():
    changes = diff_schemas({"type": ["string", "null"]}, {"type": "string"}, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.NULLABLE_TO_NON_NULLABLE
    assert changes[0].classification == Classification.BREAKING


def test_nested_object_field_changes():
    base = {
        "type": "object",
        "properties": {"address": {"type": "object", "properties": {"city": {"type": "string"}}}},
    }
    cand = {
        "type": "object",
        "properties": {"address": {"type": "object", "properties": {"city": {"type": "integer"}}}},
    }
    changes = diff_schemas(base, cand, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].path == "$.properties.address.properties.city"
    assert changes[0].change_type == ChangeType.TYPE_CHANGED


def test_array_item_type_changed():
    changes = diff_schemas(
        {"type": "array", "items": {"type": "string"}},
        {"type": "array", "items": {"type": "integer"}},
        Direction.INPUT,
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.ARRAY_ITEM_TYPE_CHANGED
    assert changes[0].path == "$[]"


def test_array_item_nested_field_change_is_not_relabeled():
    base = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}
    cand = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "integer"}}}}
    changes = diff_schemas(base, cand, Direction.INPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.TYPE_CHANGED  # not ARRAY_ITEM_TYPE_CHANGED
    assert changes[0].path == "$[].properties.x"


def test_property_constraint_change_detected():
    changes = diff_schemas(
        {"type": "string", "maxLength": 10}, {"type": "string", "maxLength": 5}, Direction.INPUT
    )
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.CONSTRAINT_CHANGED
    assert changes[0].evidence["constraint"] == "maxLength"
    assert changes[0].evidence["tightened"] is True


# --- output-schema compatibility (direction asymmetry, Phase 5 §4) ---


def test_output_field_added_is_compatible():
    changes = diff_schemas(
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {"x": {}}},
        Direction.OUTPUT,
    )
    assert changes[0].classification == Classification.COMPATIBLE


def test_output_field_removed_is_breaking():
    changes = diff_schemas(
        {"type": "object", "properties": {"x": {}}},
        {"type": "object", "properties": {}},
        Direction.OUTPUT,
    )
    assert changes[0].change_type == ChangeType.FIELD_REMOVED
    assert changes[0].classification == Classification.BREAKING


def test_output_type_changed_is_breaking():
    changes = diff_schemas({"type": "string"}, {"type": "integer"}, Direction.OUTPUT)
    assert changes[0].classification == Classification.BREAKING


def test_output_nested_field_addition_is_compatible():
    base = {"type": "object", "properties": {"user": {"type": "object", "properties": {}}}}
    cand = {
        "type": "object",
        "properties": {"user": {"type": "object", "properties": {"email": {"type": "string"}}}},
    }
    changes = diff_schemas(base, cand, Direction.OUTPUT)
    assert len(changes) == 1
    assert changes[0].change_type == ChangeType.FIELD_ADDED
    assert changes[0].classification == Classification.COMPATIBLE


# --- general ---


def test_identical_schemas_produce_zero_changes():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer", "minimum": 0}},
        "required": ["a"],
    }
    assert diff_schemas(schema, schema, Direction.INPUT) == []


def test_normalization_eliminates_non_semantic_ordering_differences():
    base = {"type": "object", "required": ["b", "a"], "properties": {"a": {}, "b": {}}}
    cand = {"type": "object", "required": ["a", "b"], "properties": {"b": {}, "a": {}}}
    assert diff_schemas(base, cand, Direction.INPUT) == []


def test_same_input_produces_same_result():
    base = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    cand = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}
    first = diff_schemas(base, cand, Direction.INPUT)
    second = diff_schemas(base, cand, Direction.INPUT)
    assert first == second


def test_deterministic_ordering_by_path_then_type_then_classification():
    base = {"type": "object", "properties": {"z": {"type": "string"}, "a": {"type": "string"}}}
    cand = {"type": "object", "properties": {"z": {"type": "integer"}, "a": {"type": "integer"}}}
    changes = diff_schemas(base, cand, Direction.INPUT)
    ordered = sort_changes(changes)
    paths = [c.path for c in ordered]
    assert paths == sorted(paths)


def test_the_acceptance_case_from_phase_5_spec():
    """Exact case from the Phase 5 spec §31, using the generic engine
    (not hardcoded): customer_id/currency removed, user_id added."""

    baseline = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
        },
        "required": ["customer_id", "amount", "currency"],
    }
    candidate = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "amount": {"type": "number"},
        },
        "required": ["user_id", "amount"],
    }
    changes = diff_schemas(baseline, candidate, Direction.INPUT)
    by_path_type = {(c.path, c.change_type) for c in changes}
    assert ("$.properties.customer_id", ChangeType.REQUIRED_FIELD_REMOVED) in by_path_type
    assert ("$.properties.currency", ChangeType.REQUIRED_FIELD_REMOVED) in by_path_type
    assert ("$.properties.user_id", ChangeType.REQUIRED_FIELD_ADDED) in by_path_type
    assert len(changes) == 3


# --- diff_mapping (generic config-level diff) ---


def test_diff_mapping_added_removed_changed():
    base = {"a": 1, "b": 2}
    cand = {"a": 1, "b": 3, "c": 4}
    changes = diff_mapping(base, cand, "$")
    by_type_path = {(c.change_type, c.path) for c in changes}
    assert (ChangeType.VALUE_CHANGED, "$.b") in by_type_path
    assert (ChangeType.CONFIG_FIELD_ADDED, "$.c") in by_type_path


def test_diff_mapping_recurses_into_nested_dicts():
    base = {"settings": {"timeout": 30}}
    cand = {"settings": {"timeout": 60}}
    changes = diff_mapping(base, cand, "$")
    assert len(changes) == 1
    assert changes[0].path == "$.settings.timeout"


def test_diff_mapping_identical_produces_zero_changes():
    d = {"a": 1, "b": {"c": 2}}
    assert diff_mapping(d, d, "$") == []
