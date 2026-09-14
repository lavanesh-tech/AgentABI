"""Factory/dependency for obtaining an `LLMProvider` (spec §17). Exactly
one branch today — OpenAI — but routes/services depend on the
`LLMProvider` protocol, so adding a second provider later is a new
`if`/class here, not a change to `ExplanationService` or any route.
"""

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.providers.openai_provider import OpenAIProvider


def get_llm_provider(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    # No Gemini branch (Phase 9 intentionally skipped — see
    # docs/ROADMAP.md). `OpenAIProvider` itself raises
    # `LLMProviderNotConfigured` only when `explain()` is actually
    # called with no API key set — constructing it here never fails, so
    # the application still starts and every non-explanation endpoint
    # still works with no OPENAI_API_KEY configured (spec §25).
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )
