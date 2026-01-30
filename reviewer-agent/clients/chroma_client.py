"""
Chroma client for the Reviewing Agent (search for code context).
"""
import logging
from dataclasses import dataclass
from typing import Optional

from ..config import ChromaConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result from the vector database."""
    file_path: str
    content: str
    score: float
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    metadata: Optional[dict] = None


class ChromaClient:
    """Client for Chroma vector search (code context for review)."""

    def __init__(self, config: ChromaConfig):
        self.config = config
        self._client = None
        self._collection = None

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.HttpClient(
                    host=self.config.host,
                    port=self.config.port,
                )
            except ImportError:
                raise ImportError(
                    "chromadb not installed. Run: pip install chromadb")
            except Exception as e:
                logger.warning(f"Could not connect to Chroma: {e}")
                raise
        return self._client

    def _get_collection(self, name: Optional[str] = None):
        if self._collection is None or name:
            client = self._get_client()
            collection_name = name or self.config.collection_name
            self._collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def search(
        self,
        query: str,
        repo_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[SearchResult]:
        """Search for similar documents (code chunks)."""
        try:
            collection = self._get_collection(collection_name)
        except Exception as e:
            logger.warning(f"Chroma not available: {e}")
            return []
        kwargs = {"query_texts": [query], "n_results": n_results}
        filters = where or {}
        if repo_name:
            filters["repo_name"] = repo_name
        if filters:
            kwargs["where"] = filters
        results = collection.query(**kwargs)
        formatted = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {
                }
                distance = results["distances"][0][i] if results["distances"] else 0
                formatted.append(SearchResult(
                    file_path=metadata.get("file_path", "unknown"),
                    content=doc,
                    score=1.0 - distance,
                    start_line=metadata.get("start_line"),
                    end_line=metadata.get("end_line"),
                    metadata=metadata,
                ))
        return formatted
