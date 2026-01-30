"""
Issue-related data models.
"""
from dataclasses import dataclass, field


@dataclass
class Issue:
    """Minimal issue representation for LLM processing."""
    title: str
    body: str
    labels: list[str] = field(default_factory=list)


@dataclass
class IssueSummary:
    """Summarized issue with extracted requirements."""
    original_issue: Issue
    summary: str
    requirements: list[str]
    acceptance_criteria: list[str]
    affected_areas: list[str]  # e.g., ["users", "api", "database"]
