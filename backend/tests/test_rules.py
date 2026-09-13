"""Pure unit tests for `app/compatibility/rules.py` — the classification/
severity lookup tables. No database, no I/O."""

from app.compatibility.models import (
    Change,
    ChangeType,
    Classification,
    CompatibilityStatus,
    Direction,
    Severity,
)
from app.compatibility.rules import (
    classify,
    classify_constraint_change,
    constraint_tightened,
    derive_status,
)


def test_required_field_added_input_is_critical_breaking():
    classification, severity = classify(ChangeType.REQUIRED_FIELD_ADDED, Direction.INPUT)
    assert classification == Classification.BREAKING
    assert severity == Severity.CRITICAL


def test_required_field_added_output_is_compatible():
    classification, severity = classify(ChangeType.REQUIRED_FIELD_ADDED, Direction.OUTPUT)
    assert classification == Classification.COMPATIBLE


def test_field_removed_direction_asymmetry():
    # Removing an optional input field is a softer signal than removing an
    # optional output field (existing consumers may depend on it).
    input_classification, _ = classify(ChangeType.FIELD_REMOVED, Direction.INPUT)
    output_classification, _ = classify(ChangeType.FIELD_REMOVED, Direction.OUTPUT)
    assert input_classification == Classification.POTENTIALLY_BREAKING
    assert output_classification == Classification.BREAKING


def test_field_added_is_compatible_for_both_directions():
    assert classify(ChangeType.FIELD_ADDED, Direction.INPUT)[0] == Classification.COMPATIBLE
    assert classify(ChangeType.FIELD_ADDED, Direction.OUTPUT)[0] == Classification.COMPATIBLE


def test_neutral_direction_is_never_more_lenient_than_either_known_direction():
    for change_type in ChangeType:
        try:
            input_result = classify(change_type, Direction.INPUT)
            output_result = classify(change_type, Direction.OUTPUT)
            neutral_result = classify(change_type, Direction.NEUTRAL)
        except KeyError:
            continue  # generic (non-schema) change type, no directional variants
        rank = {
            Classification.COMPATIBLE: 0,
            Classification.POTENTIALLY_BREAKING: 1,
            Classification.BREAKING: 2,
        }
        most_lenient = min(rank[input_result[0]], rank[output_result[0]])
        assert rank[neutral_result[0]] >= most_lenient


def test_enum_value_removed_breaking_for_input_compatible_for_output():
    assert classify(ChangeType.ENUM_VALUE_REMOVED, Direction.INPUT)[0] == Classification.BREAKING
    assert classify(ChangeType.ENUM_VALUE_REMOVED, Direction.OUTPUT)[0] == Classification.COMPATIBLE


def test_constraint_tightened_minimum_increasing_is_tighter():
    assert constraint_tightened("minimum", 1, 5) is True
    assert constraint_tightened("minimum", 5, 1) is False


def test_constraint_tightened_maximum_decreasing_is_tighter():
    assert constraint_tightened("maximum", 100, 50) is True
    assert constraint_tightened("maximum", 50, 100) is False


def test_constraint_tightened_pattern_is_ambiguous():
    assert constraint_tightened("pattern", "^a$", "^b$") is None


def test_constraint_tightened_unique_items_true_is_tighter():
    assert constraint_tightened("uniqueItems", False, True) is True
    assert constraint_tightened("uniqueItems", True, False) is False


def test_classify_constraint_change_tightened_input_is_potentially_breaking():
    classification, _ = classify_constraint_change(Direction.INPUT, tightened=True)
    assert classification == Classification.POTENTIALLY_BREAKING


def test_classify_constraint_change_loosened_input_is_compatible():
    classification, _ = classify_constraint_change(Direction.INPUT, tightened=False)
    assert classification == Classification.COMPATIBLE


def test_classify_constraint_change_tightened_output_is_compatible():
    # Less data returned is safe for an existing consumer.
    classification, _ = classify_constraint_change(Direction.OUTPUT, tightened=True)
    assert classification == Classification.COMPATIBLE


def test_classify_constraint_change_ambiguous_is_conservative():
    classification, severity = classify_constraint_change(Direction.INPUT, tightened=None)
    assert classification == Classification.POTENTIALLY_BREAKING


def _change(classification: Classification) -> Change:
    return Change(
        change_type=ChangeType.VALUE_CHANGED,
        path="$.x",
        classification=classification,
        severity=Severity.INFO,
        message="x",
    )


def test_derive_status_empty_is_compatible():
    assert derive_status(()) == CompatibilityStatus.COMPATIBLE


def test_derive_status_any_breaking_wins():
    changes = (
        _change(Classification.COMPATIBLE),
        _change(Classification.BREAKING),
        _change(Classification.POTENTIALLY_BREAKING),
    )
    assert derive_status(changes) == CompatibilityStatus.BREAKING


def test_derive_status_warning_without_breaking():
    changes = (_change(Classification.COMPATIBLE), _change(Classification.POTENTIALLY_BREAKING))
    assert derive_status(changes) == CompatibilityStatus.WARNING


def test_derive_status_all_compatible():
    changes = (_change(Classification.COMPATIBLE), _change(Classification.COMPATIBLE))
    assert derive_status(changes) == CompatibilityStatus.COMPATIBLE
