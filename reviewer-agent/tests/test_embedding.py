"""Tests for embedding and cosine similarity."""
import pytest

from reviewing_agent.embedding import cosine_similarity, embed


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_cosine_similarity_opposite():
    a = [1.0, 0.0, 0.0]
    b = [-1.0, 0.0, 0.0]
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6


def test_embed_returns_list():
    try:
        vec = embed("hello world")
    except ImportError:
        pytest.skip("sentence_transformers not installed")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(x, float) for x in vec)