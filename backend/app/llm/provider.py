"""The provider abstraction (Phase 8 spec §4). Application/service code
depends on `LLMProvider` only — never on an OpenAI SDK type — so a
future provider (spec: "not Gemini right now, but the architecture must
allow it") is a new class implementing this `Protocol`, with no changes
to `ExplanationService` or any API route.
"""

from typing import Protocol

from app.llm.models import ExplanationRequest, ExplanationResponse


class LLMProvider(Protocol):
    """Structural interface — any object with a matching `explain`
    coroutine satisfies this, no explicit inheritance required (see
    `app/providers/fake_provider.py`, `app/providers/openai_provider.py`)."""

    async def explain(self, request: ExplanationRequest) -> ExplanationResponse: ...
