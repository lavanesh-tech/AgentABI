"""Deterministic Risk Engine (Phase 11).

Answers "PASS / WARN / BLOCK?" purely from already-computed deterministic
evidence (compatibility findings, differential analysis, blast radius).
No SQLAlchemy, no FastAPI, no Pydantic, and — critically — **no `openai`
or LLM-provider import anywhere in this package**. `RiskEngine` never
calls out to a model, never asks one to score or decide, and never
invents evidence. OpenAI (`app/llm/`) may, later and only on explicit
request, explain a decision this package already made — it never makes
one. `tests/test_risk_architectural_invariant.py` enforces the import
boundary via AST inspection, the same pattern used for `app/llm/`
(Phase 8) and `app/differential/`/`app/compatibility/`.
"""
