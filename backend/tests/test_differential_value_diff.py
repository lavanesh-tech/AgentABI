"""Pure unit tests for the deterministic value-diff engine (spec §27/§28)."""

from app.differential.models import DifferenceType
from app.differential.value_diff import diff_values


def test_identical_scalars_no_diff():
    assert diff_values(1, 1) == []
    assert diff_values("a", "a") == []
    assert diff_values(None, None) == []


def test_scalar_value_changed():
    diffs = diff_values(1, 2, path="$.x")
    assert len(diffs) == 1
    assert diffs[0].difference_type == DifferenceType.VALUE_CHANGED
    assert diffs[0].path == "$.x"
    assert diffs[0].old_value == 1
    assert diffs[0].new_value == 2


def test_type_changed():
    diffs = diff_values(1, "1", path="$.x")
    assert diffs[0].difference_type == DifferenceType.SCHEMA_CHANGED
    assert diffs[0].evidence["reason"] == "type_changed"


def test_nested_field_added_and_removed():
    baseline = {"a": 1, "b": 2}
    candidate = {"a": 1, "c": 3}
    diffs = diff_values(baseline, candidate, path="$")
    reasons = {(d.path, d.evidence.get("reason")) for d in diffs}
    assert ("$.b", "field_removed") in reasons
    assert ("$.c", "field_added") in reasons


def test_missing_vs_null_distinguishable():
    baseline = {"a": 1}
    candidate = {"a": 1, "b": None}
    diffs = diff_values(baseline, candidate, path="$")
    assert len(diffs) == 1
    assert diffs[0].evidence["reason"] == "field_added"
    assert diffs[0].new_value is None


def test_nested_json_field_changed():
    baseline = {"outer": {"inner": 1}}
    candidate = {"outer": {"inner": 2}}
    diffs = diff_values(baseline, candidate, path="$")
    assert len(diffs) == 1
    assert diffs[0].path == "$.outer.inner"
    assert diffs[0].difference_type == DifferenceType.VALUE_CHANGED


def test_list_element_changed():
    diffs = diff_values([1, 2, 3], [1, 9, 3], path="$")
    assert len(diffs) == 1
    assert diffs[0].path == "$[1]"


def test_list_length_changed():
    diffs = diff_values([1, 2], [1, 2, 3], path="$")
    assert len(diffs) == 1
    assert diffs[0].evidence["reason"] == "field_added"
    assert diffs[0].path == "$[2]"


def test_reordered_dict_keys_do_not_matter():
    baseline = {"b": 2, "a": 1}
    candidate = {"a": 1, "b": 2}
    assert diff_values(baseline, candidate) == []


def test_sensitive_field_changed_is_redacted():
    baseline = {"authorization": "Bearer secret-old"}
    candidate = {"authorization": "Bearer secret-new"}
    diffs = diff_values(baseline, candidate, path="$")
    assert len(diffs) == 1
    assert diffs[0].redacted is True
    assert diffs[0].old_value == "***REDACTED***"
    assert diffs[0].new_value == "***REDACTED***"


def test_sensitive_field_unchanged_produces_no_diff():
    baseline = {"api_key": "same-secret"}
    candidate = {"api_key": "same-secret"}
    assert diff_values(baseline, candidate) == []


def test_added_subtree_with_nested_secret_is_redacted():
    baseline = {}
    candidate = {"headers": {"authorization": "Bearer xyz", "content_type": "json"}}
    diffs = diff_values(baseline, candidate, path="$")
    assert len(diffs) == 1
    added_value = diffs[0].new_value
    assert added_value["authorization"] == "***REDACTED***"
    assert added_value["content_type"] == "json"


def test_deterministic_ordering_is_stable_across_runs():
    baseline = {"z": 1, "a": 2, "m": 3}
    candidate = {"z": 9, "a": 8, "m": 7}
    first = diff_values(baseline, candidate)
    second = diff_values(baseline, candidate)
    assert [d.path for d in first] == [d.path for d in second]
    assert [d.path for d in first] == ["$.a", "$.m", "$.z"]


def test_empty_values():
    assert diff_values({}, {}) == []
    assert diff_values([], []) == []


def test_null_output_vs_value():
    diffs = diff_values(None, {"a": 1}, path="$")
    assert diffs[0].difference_type == DifferenceType.SCHEMA_CHANGED
    assert diffs[0].evidence["reason"] == "type_changed"
