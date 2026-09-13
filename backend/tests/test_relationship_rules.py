"""Pure unit tests for `app/domain/relationship_rules.py` — no database,
no Neo4j, just the allowed-triples table."""

import itertools

import pytest

from app.domain.enums import ComponentType, DependencyRelationshipType
from app.domain.exceptions import InvalidDependencyRelationship
from app.domain.relationship_rules import (
    _ALLOWED_RELATIONSHIPS,
    is_relationship_allowed,
    validate_relationship,
)


@pytest.mark.parametrize(
    "source_type, relationship_type, target_type", sorted(_ALLOWED_RELATIONSHIPS)
)
def test_every_allowed_triple_passes(source_type, relationship_type, target_type):
    assert is_relationship_allowed(source_type, relationship_type, target_type)
    validate_relationship(source_type, relationship_type, target_type)  # must not raise


def test_model_cannot_call_workflow():
    assert not is_relationship_allowed(
        ComponentType.MODEL, DependencyRelationshipType.CALLS, ComponentType.WORKFLOW
    )
    with pytest.raises(InvalidDependencyRelationship):
        validate_relationship(
            ComponentType.MODEL, DependencyRelationshipType.CALLS, ComponentType.WORKFLOW
        )


def test_invalid_relationship_error_carries_the_triple():
    with pytest.raises(InvalidDependencyRelationship) as exc_info:
        validate_relationship(
            ComponentType.PROMPT, DependencyRelationshipType.CALLS_API, ComponentType.MODEL
        )
    exc = exc_info.value
    assert exc.source_type == ComponentType.PROMPT
    assert exc.relationship_type == DependencyRelationshipType.CALLS_API
    assert exc.target_type == ComponentType.MODEL


def test_every_relationship_type_is_used_by_at_least_one_allowed_triple():
    # Guards against a relationship type being added to the enum but never
    # wired into the allow-list.
    used_types = {rel for _, rel, _ in _ALLOWED_RELATIONSHIPS}
    assert used_types == set(DependencyRelationshipType)


def test_reversed_triples_are_not_automatically_allowed():
    # Direction matters: (Agent, CALLS, Tool) being allowed says nothing
    # about (Tool, CALLS, Agent).
    reversed_triples = {
        (target_type, relationship_type, source_type)
        for source_type, relationship_type, target_type in _ALLOWED_RELATIONSHIPS
    }
    unexpectedly_allowed = reversed_triples & _ALLOWED_RELATIONSHIPS
    # Only true if a triple is its own reverse (source_type == target_type),
    # which does legitimately happen for (AGENT, DEPENDS_ON, AGENT).
    for source_type, _relationship_type, target_type in unexpectedly_allowed:
        assert source_type == target_type


def test_unallowed_combinations_outnumber_allowed_ones():
    # Sanity check that this is a genuine allow-list, not something that
    # accidentally allows everything.
    all_triples = set(itertools.product(ComponentType, DependencyRelationshipType, ComponentType))
    assert len(_ALLOWED_RELATIONSHIPS) < len(all_triples)
