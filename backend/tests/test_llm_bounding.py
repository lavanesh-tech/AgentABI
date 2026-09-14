"""Pure unit tests for deterministic evidence bounding (spec §26)."""

from app.llm.bounding import MAX_DETAIL_CHARS, MAX_SUMMARY_CHARS, bound_evidence
from app.llm.models import EvidenceItem


def _item(i: int, summary_len: int = 10, detail_len: int = 10) -> EvidenceItem:
    return EvidenceItem(
        kind="compatibility_change",
        reference_id=f"ref-{i}",
        summary="s" * summary_len,
        detail="d" * detail_len,
    )


def test_under_limit_is_not_truncated():
    items = [_item(i) for i in range(5)]
    result = bound_evidence(items, max_items=10)
    assert result.truncated is False
    assert result.original_count == 5
    assert len(result.items) == 5


def test_over_limit_is_truncated_deterministically():
    items = [_item(i) for i in range(30)]
    result = bound_evidence(items, max_items=25)
    assert result.truncated is True
    assert result.original_count == 30
    assert len(result.items) == 25
    # Order preserved — first N kept, not reordered.
    assert [item.reference_id for item in result.items] == [f"ref-{i}" for i in range(25)]


def test_long_summary_and_detail_are_clipped():
    item = _item(0, summary_len=MAX_SUMMARY_CHARS + 50, detail_len=MAX_DETAIL_CHARS + 50)
    result = bound_evidence([item])
    assert len(result.items[0].summary) == MAX_SUMMARY_CHARS
    assert result.items[0].summary.endswith("…")
    assert len(result.items[0].detail) == MAX_DETAIL_CHARS
    assert result.items[0].detail.endswith("…")


def test_short_items_are_unchanged_object_identity():
    item = _item(0)
    result = bound_evidence([item])
    assert result.items[0] is item


def test_empty_evidence():
    result = bound_evidence([])
    assert result.items == ()
    assert result.truncated is False
    assert result.original_count == 0
