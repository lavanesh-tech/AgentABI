"""`analyze()` — the single pure entry point that dispatches a
`(component_type, baseline_content, candidate_content)` triple to the
right comparison logic and returns a complete, sorted `AnalysisResult`.

This module owns the per-component-type dispatch table §2/§9-§14 of the
Phase 5 spec calls for; it deliberately does NOT touch SQLAlchemy, HTTP,
or any persistence concern — `app/services/compatibility_service.py` is
the only thing that calls this with content loaded from Postgres and the
only thing that persists what comes back.
"""

from typing import Any

from app.compatibility import diff, rules
from app.compatibility.diff import make_change, sort_changes
from app.compatibility.models import AnalysisResult, Change, ChangeType, Direction
from app.domain.enums import ComponentType
from app.domain.exceptions import UnsupportedCompatibilityType


def analyze(
    component_type: ComponentType,
    baseline_content: dict[str, Any],
    candidate_content: dict[str, Any],
) -> AnalysisResult:
    """Compare two validated component-version `content` dicts of the
    same `component_type` (see `app/domain/component_content.py` for the
    shape each type validates against) and return every detected change,
    deterministically ordered, with a derived scan-level status.
    """

    dispatch = _DISPATCH.get(component_type)
    if dispatch is None:
        raise UnsupportedCompatibilityType(component_type)

    changes = dispatch(baseline_content, candidate_content)
    ordered = tuple(sort_changes(changes))
    status = rules.derive_status(ordered)
    return AnalysisResult(status=status, changes=ordered)


def _analyze_schema(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    base_schema = baseline.get("schema_definition", {})
    cand_schema = candidate.get("schema_definition", {})
    changes = diff.diff_schemas(base_schema, cand_schema, Direction.NEUTRAL, path="$")
    if baseline.get("schema_format") != candidate.get("schema_format"):
        changes.append(
            make_change(
                ChangeType.VALUE_CHANGED,
                "$.schema_format",
                Direction.NEUTRAL,
                old_value=baseline.get("schema_format"),
                new_value=candidate.get("schema_format"),
            )
        )
    return changes


def _analyze_tool(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    changes.extend(
        diff.diff_schemas(
            baseline.get("input_schema", {}),
            candidate.get("input_schema", {}),
            Direction.INPUT,
            path="$.input_schema",
        )
    )
    changes.extend(
        diff.diff_schemas(
            baseline.get("output_schema", {}),
            candidate.get("output_schema", {}),
            Direction.OUTPUT,
            path="$.output_schema",
        )
    )
    if baseline.get("description") != candidate.get("description"):
        changes.append(
            make_change(
                ChangeType.DESCRIPTION_CHANGED,
                "$.description",
                Direction.NEUTRAL,
                old_value=baseline.get("description"),
                new_value=candidate.get("description"),
            )
        )
    return changes


def _analyze_mcp_server(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    # `MCPServerContent` (app/domain/component_content.py) has no
    # input/output schema field today, so — per the Phase 5 spec's own
    # "where its tool/schema representation makes comparison possible"
    # qualifier — this is a config-level comparison only, not a schema
    # diff. See docs/DECISIONS.md.
    changes: list[Change] = []
    field_map = {
        "server_name": ChangeType.SERVER_NAME_CHANGED,
        "transport": ChangeType.TRANSPORT_CHANGED,
        "endpoint": ChangeType.ENDPOINT_CHANGED,
    }
    for field, change_type in field_map.items():
        if baseline.get(field) != candidate.get(field):
            changes.append(
                make_change(
                    change_type,
                    f"$.{field}",
                    Direction.NEUTRAL,
                    old_value=baseline.get(field),
                    new_value=candidate.get(field),
                )
            )
    changes.extend(
        diff.diff_mapping(baseline.get("settings", {}), candidate.get("settings", {}), "$.settings")
    )
    return changes


def _analyze_model(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    if baseline.get("provider") != candidate.get("provider"):
        changes.append(
            make_change(
                ChangeType.PROVIDER_CHANGED,
                "$.provider",
                Direction.NEUTRAL,
                old_value=baseline.get("provider"),
                new_value=candidate.get("provider"),
            )
        )
    if baseline.get("model_identifier") != candidate.get("model_identifier"):
        changes.append(
            make_change(
                ChangeType.MODEL_IDENTIFIER_CHANGED,
                "$.model_identifier",
                Direction.NEUTRAL,
                old_value=baseline.get("model_identifier"),
                new_value=candidate.get("model_identifier"),
            )
        )
    changes.extend(
        diff.diff_mapping(
            baseline.get("parameters", {}),
            candidate.get("parameters", {}),
            "$.parameters",
            value_change_type=ChangeType.PARAMETER_CHANGED,
        )
    )
    return changes


def _analyze_prompt(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    if baseline.get("template") != candidate.get("template"):
        changes.append(
            make_change(
                ChangeType.CONTENT_CHANGED,
                "$.template",
                Direction.NEUTRAL,
                old_value=baseline.get("template"),
                new_value=candidate.get("template"),
            )
        )

    base_vars = set(baseline.get("variables") or [])
    cand_vars = set(candidate.get("variables") or [])
    for name in sorted(cand_vars - base_vars):
        changes.append(
            make_change(
                ChangeType.VARIABLE_ADDED, f"$.variables.{name}", Direction.NEUTRAL, new_value=name
            )
        )
    for name in sorted(base_vars - cand_vars):
        changes.append(
            make_change(
                ChangeType.VARIABLE_REMOVED,
                f"$.variables.{name}",
                Direction.NEUTRAL,
                old_value=name,
            )
        )

    changes.extend(
        diff.diff_mapping(baseline.get("settings", {}), candidate.get("settings", {}), "$.settings")
    )
    return changes


def _analyze_api(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    # `APIContent` (app/domain/component_content.py) carries `base_url`/
    # `method`/`auth` only — no request/response schema field today, so
    # request/response schema diffing (spec §13) doesn't apply until a
    # later phase extends that content model. See docs/DECISIONS.md.
    changes: list[Change] = []
    if baseline.get("base_url") != candidate.get("base_url"):
        changes.append(
            make_change(
                ChangeType.BASE_URL_CHANGED,
                "$.base_url",
                Direction.NEUTRAL,
                old_value=baseline.get("base_url"),
                new_value=candidate.get("base_url"),
            )
        )
    if baseline.get("method") != candidate.get("method"):
        changes.append(
            make_change(
                ChangeType.METHOD_CHANGED,
                "$.method",
                Direction.NEUTRAL,
                old_value=baseline.get("method"),
                new_value=candidate.get("method"),
            )
        )
    changes.extend(
        diff.diff_mapping(
            baseline.get("auth", {}),
            candidate.get("auth", {}),
            "$.auth",
            value_change_type=ChangeType.AUTH_CHANGED,
        )
    )
    return changes


def _analyze_workflow(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    base_def = baseline.get("definition", {})
    cand_def = candidate.get("definition", {})
    base_steps = base_def.get("steps") if isinstance(base_def, dict) else None
    cand_steps = cand_def.get("steps") if isinstance(cand_def, dict) else None

    if isinstance(base_steps, list) and isinstance(cand_steps, list):
        changes = _diff_workflow_steps(base_steps, cand_steps)
        # Any other top-level definition keys besides "steps".
        base_rest = {k: v for k, v in base_def.items() if k != "steps"}
        cand_rest = {k: v for k, v in cand_def.items() if k != "steps"}
        changes.extend(
            diff.diff_mapping(
                base_rest,
                cand_rest,
                "$.definition",
                value_change_type=ChangeType.WORKFLOW_CONFIG_CHANGED,
            )
        )
        return changes

    # No recognized "steps" convention (see module docstring on
    # `_analyze_workflow` in ARCHITECTURE.md): fall back to a generic
    # config-level diff of the whole definition dict.
    return diff.diff_mapping(
        base_def if isinstance(base_def, dict) else {},
        cand_def if isinstance(cand_def, dict) else {},
        "$.definition",
        value_change_type=ChangeType.WORKFLOW_CONFIG_CHANGED,
    )


def _diff_workflow_steps(base_steps: list[Any], cand_steps: list[Any]) -> list[Change]:
    def step_key(step: Any, index: int) -> str:
        if isinstance(step, dict):
            return str(step.get("id") or step.get("name") or index)
        return str(index)

    base_by_key = {step_key(s, i): s for i, s in enumerate(base_steps)}
    cand_by_key = {step_key(s, i): s for i, s in enumerate(cand_steps)}

    changes: list[Change] = []
    for key in sorted(set(base_by_key) | set(cand_by_key)):
        step_path = f"$.definition.steps.{key}"
        in_base = key in base_by_key
        in_cand = key in cand_by_key
        if in_base and not in_cand:
            was_required = isinstance(base_by_key[key], dict) and bool(
                base_by_key[key].get("required")
            )
            change_type = (
                ChangeType.REQUIRED_STEP_REMOVED if was_required else ChangeType.STEP_REMOVED
            )
            changes.append(
                make_change(change_type, step_path, Direction.NEUTRAL, old_value=base_by_key[key])
            )
        elif not in_base and in_cand:
            changes.append(
                make_change(
                    ChangeType.STEP_ADDED, step_path, Direction.NEUTRAL, new_value=cand_by_key[key]
                )
            )

    # Ordering: compare the sequence of keys present in both versions.
    common_base_order = [
        step_key(s, i) for i, s in enumerate(base_steps) if step_key(s, i) in cand_by_key
    ]
    common_cand_order = [
        step_key(s, i) for i, s in enumerate(cand_steps) if step_key(s, i) in base_by_key
    ]
    if common_base_order != common_cand_order:
        changes.append(
            make_change(
                ChangeType.STEP_ORDER_CHANGED,
                "$.definition.steps",
                Direction.NEUTRAL,
                old_value=common_base_order,
                new_value=common_cand_order,
            )
        )

    return changes


def _analyze_policy(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    # `PolicyContent.rules` is an open dict with no fixed schema (Phase 3
    # deliberately didn't standardize policy-rule shape) — a generic
    # config-level diff is the deterministic thing to do without
    # inventing structure that isn't actually there. See docs/DECISIONS.md.
    return diff.diff_mapping(
        baseline.get("rules", {}),
        candidate.get("rules", {}),
        "$.rules",
        added_type=ChangeType.RULE_ADDED,
        removed_type=ChangeType.RULE_REMOVED,
        value_change_type=ChangeType.RULE_CHANGED,
    )


def _analyze_agent(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    if baseline.get("model_ref") != candidate.get("model_ref"):
        changes.append(
            make_change(
                ChangeType.MODEL_REF_CHANGED,
                "$.model_ref",
                Direction.NEUTRAL,
                old_value=baseline.get("model_ref"),
                new_value=candidate.get("model_ref"),
            )
        )
    if baseline.get("prompt_ref") != candidate.get("prompt_ref"):
        changes.append(
            make_change(
                ChangeType.PROMPT_REF_CHANGED,
                "$.prompt_ref",
                Direction.NEUTRAL,
                old_value=baseline.get("prompt_ref"),
                new_value=candidate.get("prompt_ref"),
            )
        )

    changes.extend(_diff_agent_tools(baseline.get("tools") or [], candidate.get("tools") or []))

    changes.extend(
        diff.diff_mapping(
            baseline.get("system_config", {}), candidate.get("system_config", {}), "$.system_config"
        )
    )
    return changes


def _diff_agent_tools(base_tools: list[Any], cand_tools: list[Any]) -> list[Change]:
    def tool_key(tool: Any) -> str | None:
        if isinstance(tool, dict):
            key = tool.get("component_id") or tool.get("name")
            return str(key) if key is not None else None
        return None

    # The walrus assigns and narrows the *same* expression mypy then
    # yields, so `base_keys`/`cand_keys` are `set[str]`, not
    # `set[str | None]` (calling `tool_key(t)` again in the yielded
    # expression wouldn't narrow, since mypy can't correlate two
    # separate calls as returning the same value).
    base_keys = {key for t in base_tools if (key := tool_key(t)) is not None}
    cand_keys = {key for t in cand_tools if (key := tool_key(t)) is not None}

    changes: list[Change] = []
    for key in sorted(base_keys - cand_keys):
        changes.append(
            make_change(ChangeType.TOOL_REMOVED, f"$.tools.{key}", Direction.NEUTRAL, old_value=key)
        )
    for key in sorted(cand_keys - base_keys):
        changes.append(
            make_change(ChangeType.TOOL_ADDED, f"$.tools.{key}", Direction.NEUTRAL, new_value=key)
        )
    return changes


_DISPATCH: dict[ComponentType, Any] = {
    ComponentType.SCHEMA: _analyze_schema,
    ComponentType.TOOL: _analyze_tool,
    ComponentType.MCP_SERVER: _analyze_mcp_server,
    ComponentType.MODEL: _analyze_model,
    ComponentType.PROMPT: _analyze_prompt,
    ComponentType.API: _analyze_api,
    ComponentType.WORKFLOW: _analyze_workflow,
    ComponentType.POLICY: _analyze_policy,
    ComponentType.AGENT: _analyze_agent,
    # ComponentType.PROVIDER deliberately absent — see
    # UnsupportedCompatibilityType and docs/DECISIONS.md.
}
