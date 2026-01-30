"""Langfuse callback for Reviewing Agent (LangChain tracing)."""
import logging
from typing import Optional

from ..config import LangfuseConfig

logger = logging.getLogger(__name__)

_client_initialized = False


def init_langfuse_client(config: Optional[LangfuseConfig]) -> bool:
    """Initialize Langfuse client singleton for v3 CallbackHandler."""
    global _client_initialized
    if config is None or not config.is_configured:
        return False
    if _client_initialized:
        return True
    try:
        from langfuse import Langfuse
        Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
        )
        _client_initialized = True
        return True
    except Exception as e:
        logger.warning("Langfuse client init failed: %s", e)
        return False


def get_langfuse_callback(config: Optional[LangfuseConfig]) -> Optional[list]:
    """Create Langfuse callback handler list for chain.invoke(config={"callbacks": ...})."""
    if config is None or not config.is_configured:
        return None
    init_langfuse_client(config)
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
        return [LangfuseCallbackHandler()]
    except ImportError:
        try:
            from langfuse.callback import CallbackHandler as LangfuseCallbackHandler
            return [LangfuseCallbackHandler(
                public_key=config.public_key,
                secret_key=config.secret_key,
                host=config.host,
            )]
        except Exception as e:
            logger.warning("Langfuse callback creation failed: %s", e)
            return None
    except Exception as e:
        logger.warning("Langfuse callback creation failed: %s", e)
        return None


def flush_langfuse(callbacks: Optional[list] = None) -> None:
    """Flush Langfuse events (for short-lived scripts)."""
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:
        if callbacks:
            try:
                handler = callbacks[0]
                if hasattr(handler, "flush"):
                    handler.flush()
            except Exception as e:
                logger.warning("Langfuse flush failed: %s", e)
