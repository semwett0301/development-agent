"""
Langfuse callback handler for LangChain tracing.

For traces to appear as a single graph in Langfuse (one trace with nested spans),
wrap your entry point (e.g. run_demo) with @observe() and call init_langfuse_client()
before creating the handler. Then pass the handler to chain.invoke(config={"callbacks": [...]}).
"""
import logging
from typing import Optional

from ..config import LangfuseConfig

logger = logging.getLogger(__name__)

_CLIENT_INITIALIZED = False


def init_langfuse_client(config: Optional[LangfuseConfig]) -> bool:
    """
    Initialize the Langfuse client singleton (required for SDK v3 so CallbackHandler
    can use get_client()). Call once at startup when Langfuse is configured.

    Returns:
        True if client was initialized, False if config is missing or init failed.
    """
    global _CLIENT_INITIALIZED
    if config is None or not config.is_configured:
        return False
    if _CLIENT_INITIALIZED:
        return True
    try:
        from langfuse import Langfuse
        Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
        )
        _CLIENT_INITIALIZED = True
        return True
    except Exception as e:
        logger.warning("Langfuse client init failed: %s", e)
        return False


def get_langfuse_callback(config: Optional[LangfuseConfig]) -> Optional[list]:
    """
    Create Langfuse callback handler list for LangChain invoke().
    Initializes the Langfuse client if needed (v3). When used inside an
    @observe() or start_as_current_observation() block, the handler attaches
    chain runs to that trace so they appear in the Langfuse graph.

    Args:
        config: LangfuseConfig from load_config(); may be None if not configured.

    Returns:
        List with one CallbackHandler for use in config={"callbacks": ...},
        or None if Langfuse is not configured or creation fails.
    """
    if config is None or not config.is_configured:
        return None
    init_langfuse_client(config)
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
        # v3: no constructor args; handler uses get_client() and current trace context
        handler = LangfuseCallbackHandler()
        return [handler]
    except ImportError:
        try:
            from langfuse.callback import CallbackHandler as LangfuseCallbackHandler
            handler = LangfuseCallbackHandler(
                public_key=config.public_key,
                secret_key=config.secret_key,
                host=config.host,
            )
            return [handler]
        except Exception as e:
            logger.warning("Langfuse callback creation failed: %s", e)
            return None
    except Exception as e:
        logger.warning("Langfuse callback creation failed: %s", e)
        return None


def flush_langfuse(callbacks: Optional[list] = None) -> None:
    """
    Flush queued Langfuse events so traces are sent before process exit.
    Call at the end of short-lived scripts (e.g. demo.py).
    Prefers get_client().flush() (v3); falls back to handler.flush() if needed.

    Args:
        callbacks: Optional list from get_langfuse_callback(); used for fallback flush.
    """
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:
        if callbacks:
            try:
                handler = callbacks[0]
                if hasattr(handler, "flush"):
                    handler.flush()
                elif hasattr(handler, "langfuse") and hasattr(handler.langfuse, "flush"):
                    handler.langfuse.flush()
            except Exception as e:
                logger.warning("Langfuse flush failed: %s", e)
