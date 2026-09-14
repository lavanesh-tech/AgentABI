"""The one place a Phase 11 `RiskDecision` becomes a GitHub check
`conclusion` (spec §12: "centralize this mapping... do not allow the
LLM to choose GitHub conclusion"), plus the concise, non-JSON-dump
check-run body (spec §13-§16). Pure — no `httpx`/SQLAlchemy import —
`app.risk`/`app.github.checks_models` are the only inputs, never an
OpenAI explanation (an explanation is, at most, appended verbatim by
the caller — this module never invokes one).
"""

from app.github.checks_models import CheckConclusion, CheckRunOutput
from app.risk.models import RiskDecision

CHECK_NAME = "AgentABI Compatibility"
"""A single, stable check name (spec §10) — Phase 12 publishes exactly
one check per analysis, never one check per rule or per phase."""

_DECISION_TO_CONCLUSION: dict[RiskDecision, CheckConclusion] = {
    RiskDecision.PASS: CheckConclusion.SUCCESS,
    RiskDecision.WARN: CheckConclusion.NEUTRAL,
    RiskDecision.BLOCK: CheckConclusion.FAILURE,
}

_MAX_TOP_RULES = 5


def decision_to_conclusion(decision: RiskDecision) -> CheckConclusion:
    """Total over every `RiskDecision` member — a `KeyError` here would
    mean a new decision value shipped without updating this mapping,
    which `tests/test_github_check_mapping.py` guards against by
    asserting every `RiskDecision` member is covered."""

    return _DECISION_TO_CONCLUSION[decision]


def build_in_progress_output(*, compatibility_summary: str | None) -> CheckRunOutput:
    """The check body while the deterministic pipeline is still running
    (spec §11's queued/in_progress step)."""

    lines = ["AgentABI is running its deterministic analysis pipeline."]
    if compatibility_summary:
        lines.append(compatibility_summary)
    return CheckRunOutput(title="AgentABI analysis in progress", summary="\n\n".join(lines))


def build_completed_output(
    *,
    decision: RiskDecision,
    score: int,
    risk_engine_version: str,
    hard_block: bool,
    top_rules: list[tuple[str, int]],
    compatibility_summary: str | None = None,
    differential_summary: str | None = None,
    report_url: str | None = None,
    explanation: str | None = None,
) -> CheckRunOutput:
    """The final, completed check body (spec §13-§16) — concise,
    deterministic-evidence-first, never a raw JSON dump. `explanation`
    is the ONLY place an optional Phase 8 OpenAI explanation of the
    already-computed decision may appear (spec §17); it is never
    required and never changes `decision`/`score` themselves."""

    title = f"AgentABI decision: {decision.value} (score {score}/100)"

    lines: list[str] = []
    if decision is RiskDecision.PASS:
        lines.append(
            "Deterministic analysis passed: no configured AgentABI "
            "blocking or warning threshold was exceeded."
        )
    elif decision is RiskDecision.WARN:
        lines.append(
            "AgentABI decision: WARN — potentially risky evidence was "
            "found, but it did not cross the configured blocking threshold."
        )
    else:
        lines.append(
            "AgentABI decision: BLOCK — deterministic evidence indicates "
            "this change should not deploy automatically."
        )

    lines.append(f"**Score:** {score}/100  ·  **Engine version:** {risk_engine_version}")
    if hard_block:
        lines.append("**Hard block:** at least one hard-block rule fired independent of score.")

    if top_rules:
        rule_lines = "\n".join(
            f"- `{rule_id}` ({'+' if delta >= 0 else ''}{delta})"
            for rule_id, delta in top_rules[:_MAX_TOP_RULES]
        )
        lines.append(f"**Top triggered rules:**\n{rule_lines}")

    if compatibility_summary:
        lines.append(f"**Compatibility:** {compatibility_summary}")
    if differential_summary:
        lines.append(f"**Differential:** {differential_summary}")
    if explanation:
        lines.append(f"**Explanation:** {explanation}")
    if report_url:
        lines.append(f"[Full AgentABI report]({report_url})")

    return CheckRunOutput(title=title, summary="\n\n".join(lines))
