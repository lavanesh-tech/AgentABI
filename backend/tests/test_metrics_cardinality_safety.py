"""Phase 16 spec §22 (mandatory) cardinality-safety test: statically
verifies that no metric declared in `app.observability.metrics` uses any
of the explicitly forbidden high-cardinality label names — project_id,
organization_id, component_id, event_id, trace_id, request_id,
correlation_id, pull_request_number, head_sha, email, GitHub username,
raw URL, exception message. Pure source inspection — needs no
third-party dependency to run in principle, but this sandbox has no
project dependency installed this session (PyPI unreachable — see
docs/DECISIONS.md). Written and `py_compile`-clean; not pytest-executed.
"""

import ast
import inspect

from app.observability import metrics


def _declared_metric_labelnames() -> list[tuple[str, tuple[str, ...]]]:
    """Parses `metrics.py`'s source for every `_counter(...)`/
    `_histogram(...)`/`_gauge(...)` call and extracts the literal
    labelnames tuple passed to each — i.e. exactly what
    `_assert_safe_labels` already checks at import time, verified here
    independently via AST rather than trusting that runtime check alone."""

    source = inspect.getsource(metrics)
    tree = ast.parse(source)
    results: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", None)
        if func_name not in ("_counter", "_histogram", "_gauge"):
            continue
        if len(node.args) < 1 or not isinstance(node.args[0], ast.Constant):
            continue
        metric_name = node.args[0].value
        labelnames: tuple[str, ...] = ()
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Tuple):
            labelnames = tuple(
                elt.value for elt in node.args[2].elts if isinstance(elt, ast.Constant)
            )
        results.append((metric_name, labelnames))
    return results


def test_no_declared_metric_uses_a_forbidden_label_name():
    declared = _declared_metric_labelnames()
    assert declared, "expected at least one metric declaration to inspect"
    for metric_name, labelnames in declared:
        unsafe = metrics.FORBIDDEN_LABEL_NAMES.intersection(labelnames)
        assert not unsafe, f"{metric_name} declares forbidden label(s): {sorted(unsafe)}"


def test_all_agentabi_metric_names_follow_naming_convention():
    """spec §21: `agentabi_` prefix, `*_total` for counters, `*_seconds`
    for durations."""

    source = inspect.getsource(metrics)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", None)
        if func_name not in ("_counter", "_histogram", "_gauge"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        assert name.startswith("agentabi_"), name
        if func_name == "_counter":
            assert name.endswith("_total"), name
        if func_name == "_histogram":
            assert name.endswith("_seconds"), name
