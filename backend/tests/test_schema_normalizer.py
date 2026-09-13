"""Pure unit tests for `app/compatibility/schema_normalizer.py` — no
database, no I/O."""

import pytest

from app.compatibility.schema_normalizer import normalize_schema
from app.domain.exceptions import SchemaNormalizationError


def test_required_list_is_sorted_and_deduped():
    schema = {"type": "object", "required": ["b", "a", "b"]}
    assert normalize_schema(schema)["required"] == ["a", "b"]


def test_type_list_single_element_collapses_to_string():
    assert normalize_schema({"type": ["string"]})["type"] == "string"


def test_type_list_multi_element_sorted():
    assert normalize_schema({"type": ["string", "null"]})["type"] == ["null", "string"]
    assert normalize_schema({"type": ["null", "string"]})["type"] == ["null", "string"]


def test_enum_duplicates_collapsed_order_preserved():
    assert normalize_schema({"enum": ["a", "b", "a", "c"]})["enum"] == ["a", "b", "c"]


def test_nested_properties_normalized_recursively():
    schema = {
        "type": "object",
        "properties": {
            "child": {"type": "object", "required": ["y", "x"]},
        },
    }
    normalized = normalize_schema(schema)
    assert normalized["properties"]["child"]["required"] == ["x", "y"]


def test_items_normalized_recursively():
    schema = {"type": "array", "items": {"type": "object", "required": ["b", "a"]}}
    assert normalize_schema(schema)["items"]["required"] == ["a", "b"]


def test_does_not_mutate_input():
    schema = {"required": ["b", "a"]}
    normalize_schema(schema)
    assert schema["required"] == ["b", "a"]


def test_boolean_schema_passes_through():
    assert normalize_schema(True) is True
    assert normalize_schema(False) is False


def test_two_differently_ordered_schemas_normalize_identically():
    a = {"type": "object", "required": ["b", "a"], "properties": {"a": {}, "b": {}}}
    b = {"type": "object", "required": ["a", "b"], "properties": {"b": {}, "a": {}}}
    assert normalize_schema(a) == normalize_schema(b)


def test_exceeds_max_depth_raises_schema_normalization_error():
    schema: dict = {}
    node = schema
    for _ in range(100):
        node["properties"] = {"child": {}}
        node = node["properties"]["child"]
    with pytest.raises(SchemaNormalizationError):
        normalize_schema(schema)
