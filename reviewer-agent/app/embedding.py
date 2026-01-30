"""
Embedding and cosine similarity for summary comparison.
Uses fastembed (ONNX, no PyTorch) — small download (~100–200 MB total).
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

_encoder = None
_embedding_dim: int | None = None

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            from fastembed import TextEmbedding
            _encoder = TextEmbedding(_DEFAULT_MODEL)
        except ImportError:
            logger.warning(
                "fastembed not installed; install with: pip install fastembed"
            )
            raise
    return _encoder


def _get_embedding_dim() -> int:
    global _embedding_dim
    if _embedding_dim is None:
        enc = _get_encoder()
        vec = next(enc.embed([" "]))
        _embedding_dim = int(vec.shape[0])
    return _embedding_dim


def embed(text: str) -> List[float]:
    """
    Embed a single text string into a vector.

    Args:
        text: Input text (e.g. summary string).

    Returns:
        List of floats (embedding vector).
    """
    if not (text or "").strip():
        return [0.0] * _get_embedding_dim()
    model = _get_encoder()
    vec = next(model.embed([text]))
    return vec.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity between two vectors.

    Returns:
        Value in [-1, 1]; 1 means identical direction.
    """
    import math
    if not a or not b:
        return 0.0

    if len(a) != len(b):
        min_len = min(len(a), len(b))
        a = a[:min_len]
        b = b[:min_len]

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
