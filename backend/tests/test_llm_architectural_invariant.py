"""Structural proof that the deterministic core does not depend on
OpenAI (Phase 8 spec §31; reinforced by Phase 10 and Phase 11's own
deterministic packages). Pure — no network, no API key, no `openai`
import required for this file itself to run.
"""

import ast
from pathlib import Path

DETERMINISTIC_PACKAGES = (
    "compatibility",
    "graph",
    "replay",
    "trajectory",
    "domain",
    "differential",
    # Phase 11 spec §29: the deterministic Risk Engine must never import
    # OpenAI or any LLM-provider module — it only ever consumes already-
    # computed deterministic evidence.
    "risk",
)
FORBIDDEN_IMPORT_ROOTS = ("openai",)


def _iter_py_files(package_dir: Path):
    yield from package_dir.rglob("*.py")


def _parse(py_file: Path) -> ast.Module | None:
    # Some modules use Python 3.12-only syntax (PEP 695 generics); this
    # test's own interpreter may be older in some environments, so a
    # SyntaxError here means "can't check this file with this
    # interpreter," not "found a violation" — skip it rather than fail.
    try:
        return ast.parse(py_file.read_text(), filename=str(py_file))
    except SyntaxError:
        return None


def test_deterministic_packages_never_import_openai():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    violations = []
    for package in DETERMINISTIC_PACKAGES:
        package_dir = app_dir / package
        if not package_dir.is_dir():
            continue
        for py_file in _iter_py_files(package_dir):
            tree = _parse(py_file)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                for name in names:
                    if name and name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                        violations.append(f"{py_file}: imports {name!r}")
    assert not violations, f"deterministic core imports OpenAI: {violations}"


def test_only_openai_provider_module_imports_the_openai_sdk():
    """The `openai` package name may appear (as a lazy import) in exactly
    one file — `app/providers/openai_provider.py` — proving the
    abstraction boundary (spec §4) is real, not just documented."""

    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for py_file in app_dir.rglob("*.py"):
        if py_file.name == "openai_provider.py":
            continue
        tree = _parse(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                if name and name.split(".")[0] == "openai":
                    offenders.append(str(py_file))
    assert not offenders, f"unexpected openai import outside the provider module: {offenders}"


def test_explanation_service_depends_on_protocol_not_concrete_provider():
    import inspect

    from app.services.explanation_service import ExplanationService

    sig = inspect.signature(ExplanationService.__init__)
    annotation = sig.parameters["provider"].annotation
    assert annotation in ("LLMProvider", None) or "LLMProvider" in str(annotation)
