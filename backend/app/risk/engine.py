"""`RiskEngine` — the pure, deterministic orchestration function that
turns a `RiskContext` into a `RiskAssessment` (spec §5-§9, §17-§19).

No randomness, no wall-clock, no I/O, no OpenAI/LLM call: `evaluate()`
is a total function of its `RiskContext` argument — the same context
always produces the same `RiskAssessment` (spec §33's reproducibility
requirement), byte-for-byte, forever, for a fixed
`RISK_ENGINE_VERSION`.
"""

from app.risk.models import (
    CategoryContribution,
    RiskAssessment,
    RiskCategory,
    RiskContext,
    RiskDecision,
    TriggeredRule,
)
from app.risk.rules import CATEGORY_CAPS, HARD_BLOCK_RULES, MAX_SCORE, SCORE_RULES

# Bump this whenever SCORE_RULES/HARD_BLOCK_RULES/CATEGORY_CAPS/the
# threshold banding below changes in any way that could change a past
# assessment's decision or score — never edit the rules in place under
# the same version (spec §19). Persisted `RiskAssessmentRecord`s carry
# this value forever; old assessments keep the meaning they were
# computed with even after a new version ships.
RISK_ENGINE_VERSION = "1"

# Recommended and adopted banding (spec §8): PASS < 30, WARN 30-69,
# BLOCK >= 70.
_PASS_MAX = 29
_WARN_MAX = 69


def _decide(score: int, hard_block: bool) -> RiskDecision:
    if hard_block:
        return RiskDecision.BLOCK
    if score <= _PASS_MAX:
        return RiskDecision.PASS
    if score <= _WARN_MAX:
        return RiskDecision.WARN
    return RiskDecision.BLOCK


def evaluate(context: RiskContext) -> RiskAssessment:
    """Evaluate every rule in `SCORE_RULES` and `HARD_BLOCK_RULES`
    against `context`, apply the per-category cap and the overall
    100-point cap, and derive the final decision. A `RiskContext()`
    with every field at its default ("no evidence") triggers nothing
    and yields `score=0, decision=PASS, hard_block=False` (spec §36) —
    there is no special-case branch for "no evidence"; it falls out of
    every rule's predicate simply not matching.
    """

    triggered: list[TriggeredRule] = [
        rule for rule in (score_rule(context) for score_rule in SCORE_RULES) if rule is not None
    ]
    hard_block_triggered: list[TriggeredRule] = [
        rule for rule in (hb_rule(context) for hb_rule in HARD_BLOCK_RULES) if rule is not None
    ]
    all_triggered = tuple(triggered + hard_block_triggered)

    contributions: list[CategoryContribution] = []
    capped_score = 0
    for category in RiskCategory:
        cap = CATEGORY_CAPS[category]
        raw_total = sum(r.score_delta for r in triggered if r.category is category)
        category_capped = min(raw_total, cap)
        contributions.append(
            CategoryContribution(
                category=category, raw_total=raw_total, capped_total=category_capped, cap=cap
            )
        )
        capped_score += category_capped

    score = min(capped_score, MAX_SCORE)
    hard_block = len(hard_block_triggered) > 0
    decision = _decide(score, hard_block)

    return RiskAssessment(
        risk_engine_version=RISK_ENGINE_VERSION,
        decision=decision,
        score=score,
        hard_block=hard_block,
        triggered_rules=all_triggered,
        category_contributions=tuple(contributions),
    )
