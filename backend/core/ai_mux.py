"""AI Multiplexer service orchestrating LLM interactions."""

from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional

from backend.tools import ai_providers


class AIMux:
    """Provides async text generation and configuration over configured AI providers."""

    def __init__(self):
        pass

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> str:
        """Generate text asynchronously using the active or requested AI provider."""
        def _call() -> str:
            env = ai_providers.load_env_file()
            provider = ai_providers.Provider(provider_id, env) if provider_id else ai_providers.get_ai_provider(env)
            return provider.generate(prompt, system=system)

        return await asyncio.to_thread(_call)

    def get_settings(self) -> Dict[str, Any]:
        """Return sanitized settings suitable for frontend display."""
        return ai_providers.public_settings()

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save settings updates into .env."""
        return ai_providers.save_settings(payload)

    def get_info(self) -> Dict[str, Any]:
        """Return information about the currently active provider."""
        provider = ai_providers.get_ai_provider()
        return provider.get_info()

