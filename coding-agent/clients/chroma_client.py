"""
Chroma vector database client for the Coding Agent.
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
    """Client for interacting with Chroma vector database."""

    def __init__(self, config: ChromaConfig):
        self.config = config
        self._client = None
        self._collection = None

    def _get_client(self):
        """Lazy initialization of Chroma client."""
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.HttpClient(
                    host=self.config.host,
                    port=self.config.port,
                )
            except ImportError:
                raise ImportError(
                    "chromadb not installed. Run: pip install chromadb"
                )
            except Exception as e:
                logger.warning(f"Could not connect to Chroma: {e}")
                raise
        return self._client

    def _get_collection(self, name: Optional[str] = None):
        """Get or create a collection."""
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
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[SearchResult]:
        """
        Search for similar documents.
        
        Args:
            query: Search query text
            repo_name: Optional repository name filter
            collection_name: Optional collection name override
            n_results: Number of results to return
            where: Optional metadata filter
            
        Returns:
            List of SearchResult objects
        """
        try:
            collection = self._get_collection(collection_name)
        except Exception as e:
            logger.warning(f"Chroma not available: {e}")
            return []
        
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
        }
        
        # Build where filter
        filters = where or {}
        if repo_name:
            filters["repo_name"] = repo_name
        if filters:
            kwargs["where"] = filters

        results = collection.query(**kwargs)
        
        # Format results as SearchResult objects
        formatted = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0
                
                formatted.append(SearchResult(
                    file_path=metadata.get("file_path", "unknown"),
                    content=doc,
                    score=1.0 - distance,  # Convert distance to similarity score
                    start_line=metadata.get("start_line"),
                    end_line=metadata.get("end_line"),
                    metadata=metadata,
                ))
        
        return formatted

    def search_by_file(
        self,
        file_path: str,
        repo_name: Optional[str] = None,
        n_results: int = 5,
    ) -> list[SearchResult]:
        """
        Search for code chunks from a specific file.
        
        Args:
            file_path: Path to the file
            repo_name: Optional repository name filter
            n_results: Number of results to return
            
        Returns:
            List of SearchResult objects from the specified file
        """
        where = {"file_path": file_path}
        if repo_name:
            where["repo_name"] = repo_name
        
        try:
            collection = self._get_collection()
            results = collection.get(
                where=where,
                limit=n_results,
            )
        except Exception as e:
            logger.warning(f"Could not search by file: {e}")
            return []
        
        formatted = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"]):
                metadata = results["metadatas"][i] if results["metadatas"] else {}
                
                formatted.append(SearchResult(
                    file_path=metadata.get("file_path", file_path),
                    content=doc,
                    score=1.0,  # Exact match
                    start_line=metadata.get("start_line"),
                    end_line=metadata.get("end_line"),
                    metadata=metadata,
                ))
        
        return formatted

    def add_documents(
        self,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        collection_name: Optional[str] = None,
    ) -> None:
        """
        Add documents to the collection.
        
        Args:
            documents: List of document texts
            metadatas: List of metadata dicts
            ids: List of unique IDs
            collection_name: Optional collection name override
        """
        collection = self._get_collection(collection_name)
        
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        
        logger.info(f"Added {len(documents)} documents to {collection_name or self.config.collection_name}")

    def delete_collection(self, name: Optional[str] = None) -> None:
        """Delete a collection."""
        client = self._get_client()
        collection_name = name or self.config.collection_name
        
        try:
            client.delete_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
        except Exception as e:
            logger.warning(f"Could not delete collection {collection_name}: {e}")
