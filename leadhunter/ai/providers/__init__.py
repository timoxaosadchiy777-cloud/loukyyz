"""AI-провайдеры LeadHunter.

Каждый провайдер реализует единый контракт :class:`~ai.providers.base.AIProvider`
(`generate(prompt) -> str`). Роутер (:mod:`ai.llm`) перебирает провайдеров по
порядку с fallback, поэтому LeadHunter не зависит от одного платного API.
"""

from ai.providers.base import AIProvider, ProviderError

__all__ = ["AIProvider", "ProviderError"]
