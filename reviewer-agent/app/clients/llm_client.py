"""LLM client for the Reviewing Agent (LangChain chat model from config)."""
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel

from ..config import LLMConfig

logger = logging.getLogger(__name__)


def create_chat_model(config: LLMConfig) -> BaseChatModel:
    """Create a LangChain chat model from config."""
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=config.model,
            api_key=config.api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except ImportError:
        raise ImportError(
            "langchain-anthropic not installed. Run: pip install langchain-anthropic"
        )
