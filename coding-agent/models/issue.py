"""
Issue-related data models.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Issue:
    """Represents a GitHub issue."""
    id: int
    number: int
    title: str
    body: str
    repo_owner: str
    repo_name: str
    labels: list[str] = field(default_factory=list)
    url: Optional[str] = None

    @property
    def repo_full_name(self) -> str:
        return f"{self.repo_owner}/{self.repo_name}"

    @property
    def branch_name(self) -> str:
        """Generate branch name for this issue."""
        safe_title = self.title.lower()
        safe_title = "".join(c if c.isalnum() or c == " " else "" for c in safe_title)
        safe_title = "-".join(safe_title.split()[:5])
        return f"fix/issue-{self.number}-{safe_title}"


@dataclass
class IssueSummary:
    """Summarized issue with extracted requirements."""
    original_issue: Issue
    summary: str
    requirements: list[str]
    acceptance_criteria: list[str]
    affected_areas: list[str]  # e.g., ["users", "api", "database"]
