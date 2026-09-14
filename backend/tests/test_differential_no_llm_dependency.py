"""Structural proof that `app/differential/` never imports OpenAI or any
LLM-provider module (spec §25) — the differential analyzer must run
successfully with `OPENAI_API_KEY=` unset, and can't even call out to a
provider since it never imports one.
"""

import ast
from pathlib import Path

FORBIDDEN_IMPORT_ROOTS = ("openai",)
FORBIDDEN_MODULE_PREFIXES = ("app.providers", "app.llm", "app.services.explanation_service")


def _parse(py_file: Path) -> ast.Module | None:
    try:
        return ast.parse(py_file.read_text(), filename=str(py_file))
    except SyntaxError:
        return None


def test_differential_package_never_imports_openai_or_llm_modules():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    differential_dir = app_dir / "differential"
    violations = []
    for py_file in differential_dir.rglob("*.py"):
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
                if not name:
                    continue
                root = name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS or any(
                    name.startswith(p) for p in FORBIDDEN_MODULE_PREFIXES
                ):
                    violations.append(f"{py_file}: imports {name!r}")
    assert not violations, f"app/differential imports an LLM module: {violations}"


def test_differential_analyzer_runs_with_no_api_key(monkeypatch):
    """The differential analyzer is pure Python — it never reads
    settings or an API key at all, so this is really a proof that
    calling it has zero dependency on `OPENAI_API_KEY` being set."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app.differential.analyzer import analyze

    report = analyze([], [])
    assert report.summary.total_baseline_steps == 0
