"""ИИ-слой: клиент Gemini и промпты."""

from ai.gemini_client import GeminiClient
from ai.prompts import SYSTEM_PROMPT, build_user_content

__all__ = ["GeminiClient", "SYSTEM_PROMPT", "build_user_content"]
