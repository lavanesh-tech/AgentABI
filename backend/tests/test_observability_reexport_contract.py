"""Regression test for the `record_http_request` re-export bug: it was
fully implemented in `app.observability.metrics` (and listed in that
module's own `__all__`) but accidentally left out of
`app.observability.__init__`'s re-export `from ... import (...)` block and
`__all__` list, so every module that did `from app.observability import
record_http_request` (starting with `app.core.metrics_middleware`, pulled
in transitively by `app.main`) raised `ImportError` at process startup —
the API container exited immediately.

Pure `ast`/text source inspection of the two files on disk — deliberately
does NOT `import app.observability` or anything under `app.core.config`
(which pulls in `pydantic`/`pydantic_settings`), so unlike most of this
project's tests this one has zero third-party dependencies and actually
executes in this sandbox (verified via a bare `pytest` invocation, not
just `py_compile`).
"""

from __future__ import annotations

import ast
from pathlib import Path

_OBSERVABILITY_DIR = Path(__file__).resolve().parent.parent / "app" / "observability"
_APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _metrics_public_callables() -> set[str]:
    """Every function/generator name in `metrics.py`'s own `__all__` — the
    module's declared public *callables*, independent of whether the
    package re-exports them. Deliberately excludes plain module-level
    constants such as `FORBIDDEN_LABEL_NAMES`, which is intentionally
    reached via `from app.observability import metrics` (the submodule)
    rather than the package's re-export surface — the bug class this test
    guards against is a missing *function* re-export, and callers never
    do `from app.observability import FORBIDDEN_LABEL_NAMES`."""

    tree = _parse(_OBSERVABILITY_DIR / "metrics.py")
    all_names: set[str] = set()
    for node in ast.walk(tree):
        is_all_assign = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        )
        if is_all_assign and isinstance(node.value, ast.List):
            all_names = {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    if not all_names:
        raise AssertionError("app/observability/metrics.py has no __all__ list")

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    return all_names & function_names


def _init_imported_metrics_names() -> set[str]:
    """Every name the package `__init__.py` actually imports from
    `app.observability.metrics` via its `from app.observability.metrics
    import (...)` block."""

    tree = _parse(_OBSERVABILITY_DIR / "__init__.py")
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.observability.metrics":
            names.update(alias.name for alias in node.names)
    return names


def _init_all_names() -> set[str]:
    tree = _parse(_OBSERVABILITY_DIR / "__init__.py")
    for node in ast.walk(tree):
        is_all_assign = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        )
        if is_all_assign and isinstance(node.value, ast.List):
            return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    raise AssertionError("app/observability/__init__.py has no __all__ list")


def _names_imported_from_observability_package() -> set[str]:
    """Every name any module under `app/` actually does
    `from app.observability import <name>` for — the real blast radius of
    a re-export omission, not just what `metrics.py` happens to define."""

    names: set[str] = set()
    for path in _APP_DIR.rglob("*.py"):
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.observability":
                names.update(alias.name for alias in node.names)
    return names


def test_every_public_metrics_name_is_reexported_by_the_package():
    """Every name `metrics.py` declares public (its own `__all__`) must be
    both imported into and listed in `__init__.py`'s `__all__` — the exact
    contract that silently broke for `record_http_request`."""

    public = _metrics_public_callables()
    imported = _init_imported_metrics_names()
    exported = _init_all_names()

    missing_import = public - imported
    assert not missing_import, (
        f"metrics.py declares these public but __init__.py never imports them: "
        f"{sorted(missing_import)}"
    )
    missing_all = public - exported
    assert not missing_all, (
        f"metrics.py declares these public but __init__.py's __all__ omits them: "
        f"{sorted(missing_all)}"
    )


def test_every_call_site_import_is_satisfied_by_the_package_all():
    """Every `from app.observability import X` anywhere under `app/` must
    name something `__init__.py` actually exports — this is the check
    that would have failed loudly (rather than only at container startup)
    for `app.core.metrics_middleware`'s `record_http_request` import."""

    used = _names_imported_from_observability_package()
    exported = _init_all_names()

    unsatisfied = used - exported
    assert not unsatisfied, (
        f"modules import these names from app.observability but __init__.py's "
        f"__all__ doesn't export them: {sorted(unsatisfied)}"
    )
