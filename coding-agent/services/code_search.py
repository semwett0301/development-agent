import logging
from pathlib import Path
from typing import Optional

from ..clients import ChromaClient, SearchResult
from ..models import IssueSummary, PlanStep

logger = logging.getLogger(__name__)


class CodeSearchService:
    """Search for relevant code in the codebase."""

    def __init__(self, chroma_client: ChromaClient):
        self.chroma = chroma_client

    def search_for_issue(self, summary: IssueSummary, repo_name: str, n_results: int = 15) -> list[SearchResult]:
        """Search for code relevant to an issue.
        
        Input:
            summary: Summarized issue
            repo_name: Repository name
            n_results: Number of results to return
            
        Output:
            List of relevant code snippets
        """
        query_parts = [summary.summary]
        query_parts.extend(summary.requirements[:3])
        query_parts.extend(summary.affected_areas)
        
        query = " ".join(query_parts)
        
        logger.info(f"Searching for code relevant to: {query[:100]}...")
        
        return self.chroma.search(
            query=query,
            repo_name=repo_name,
            n_results=n_results,
        )

    def search_for_step(self, step: PlanStep, repo_name: str, n_results: int = 10) -> list[SearchResult]:
        """
        Search for code relevant to a specific plan step.
        
        Input:
            step: The plan step to search for
            repo_name: Repository name
            n_results: Number of results
            
        Output:
            List of relevant code snippets
        """
        query = f"{step.description} {step.details or ''}"
        
        results = self.chroma.search(
            query=query,
            repo_name=repo_name,
            n_results=n_results,
        )
        
        # бля че с хромой делать если она не стоит
        file_results = self.chroma.search_by_file(
            file_path=step.file_path,
            repo_name=repo_name,
            n_results=5,
        )
        
        seen_files = set()
        combined = []
        
        for result in results + file_results:
            if result.file_path not in seen_files:
                combined.append(result)
                seen_files.add(result.file_path)
        
        return combined[:n_results]

    def get_file_content(self, file_path: str, repo_path: Path) -> Optional[str]:
        """
        Get the content of a file from the repository.
        
        Input:
            file_path: Relative path to the file
            repo_path: Path to the repository root
            
        Output:
            File content if found
        """
        full_path = repo_path / file_path
        
        if not full_path.exists():
            logger.debug(f"File not found: {full_path}")
            return None
        
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {full_path}: {e}")
            return None

    def build_context(self, results: list[SearchResult], max_length: int = 10000) -> str:
        """
        Build a context string from search results.
        
        Input:
            results: Search results
            max_length: Maximum total length
            
        Output:
            Formatted context string
        """
        if not results:
            return "No relevant code found."
        
        context_parts = []
        current_length = 0
        
        for result in results:
            header = f"### {result.file_path}"
            if result.start_line and result.end_line:
                header += f" (lines {result.start_line}-{result.end_line})"
            header += f" [score: {result.score:.2f}]"
            
            snippet = f"{header}\n```\n{result.content}\n```\n"
            
            if current_length + len(snippet) > max_length:
                break
            
            context_parts.append(snippet)
            current_length += len(snippet)
        
        return "\n".join(context_parts)

    def get_project_structure(self, repo_path: Path, max_depth: int = 3, exclude_patterns: Optional[list[str]] = None) -> str:
        """
        Get the project file structure.
        
        Input:
            repo_path: Path to repository
            max_depth: Maximum directory depth
            exclude_patterns: Patterns to exclude
            
        Output:
            Formatted project structure
        """
        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__", ".git", "node_modules", ".venv", "venv",
                ".idea", ".vscode", "dist", "build", ".pytest_cache",
                ".mypy_cache", "*.pyc", ".DS_Store",
            ]

        def should_exclude(path: Path) -> bool:
            name = path.name
            for pattern in exclude_patterns:
                if pattern.startswith("*"):
                    if name.endswith(pattern[1:]):
                        return True
                elif name == pattern:
                    return True
            return False

        def build_tree(path: Path, prefix: str = "", depth: int = 0) -> list[str]:
            if depth >= max_depth:
                return []
            
            lines = []
            try:
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
            except PermissionError:
                return []
            
            items = [item for item in items if not should_exclude(item)]
            
            for i, item in enumerate(items):
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{item.name}")
                
                if item.is_dir():
                    extension = "    " if is_last else "│   "
                    lines.extend(build_tree(item, prefix + extension, depth + 1))
            
            return lines

        if not repo_path.exists():
            return "Repository not found"
        
        tree_lines = [repo_path.name + "/"]
        tree_lines.extend(build_tree(repo_path))
        
        return "\n".join(tree_lines)
