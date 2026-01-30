"""
Embedding and cosine similarity for summary comparison.
Uses sentence-transformers so the same model is used for both texts.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

_encoder = None
_DEFAULT_MODEL = "all-MiniLM-L6-v2"


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _encoder = SentenceTransformer(_DEFAULT_MODEL)
        except ImportError:
            logger.warning(
                "sentence_transformers not installed; install with: pip install sentence-transformers"
            )
            raise
    return _encoder


def embed(text: str) -> List[float]:
    """
    Embed a single text string into a vector.

    Args:
        text: Input text (e.g. summary string).

    Returns:
        List of floats (embedding vector).
    """
    if not (text or "").strip():
        # Return zero vector for empty to avoid errors; similarity will be 0
        enc = _get_encoder()
        return [0.0] * enc.get_sentence_embedding_dimension()
    model = _get_encoder()
    vec = model.encode(text, convert_to_numpy=True)
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
