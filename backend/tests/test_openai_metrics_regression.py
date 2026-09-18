"""Phase 16 spec §40 (mandatory) OpenAI regression: metrics recording
must never alter the explanation request/response shape, the decision
logic (there is none here — OpenAIProvider only explains, per spec §31's
architectural invariant), or failure handling/exception mapping
established in Phase 8. Structural source-inspection checks — needs the
`openai` package, not installed in this sandbox this session (PyPI
unreachable — see docs/DECISIONS.md). Written and `py_compile`-clean;
not pytest-executed.
"""

import inspect

from app.providers.openai_provider import OpenAIProvider


def test_explain_still_delegates_to_impl_unchanged():
    source = inspect.getsource(OpenAIProvider.explain)
    assert "self._explain_impl(request)" in source
    assert "record_openai_explanation" in source


def test_explain_impl_untouched_by_metrics_wiring():
    """The actual OpenAI SDK call, schema validation, and exception
    mapping all live in `_explain_impl` — Phase 16 adds no code to it at
    all, so every Phase 8 exception-mapping branch is exactly as it was."""

    source = inspect.getsource(OpenAIProvider._explain_impl)
    assert "record_openai_explanation" not in source
    assert "start_span" not in source
    for exc_name in (
        "LLMProviderNotConfigured",
        "LLMProviderTimeout",
        "LLMProviderUnavailable",
        "LLMExplanationFailed",
    ):
        assert exc_name in source

    # Invalid/malformed responses are mapped by the dedicated parser /
    # reference-validation helpers called by _explain_impl.
    assert "_parse_response" in source
    assert "_validate_references" in source


def test_metrics_never_swallow_a_provider_exception():
    """The `finally` block that records duration/outcome must not catch
    or suppress the exception — `explain()`'s source must re-raise via a
    bare `raise` in the `except` clause, with the metric call only in a
    `finally`, never returning a value from the `except` branch."""

    source = inspect.getsource(OpenAIProvider.explain)
    assert "except Exception:" in source
    except_block = source.split("except Exception:")[1].split("finally:")[0]
    assert "raise" in except_block
    assert "return" not in except_block
