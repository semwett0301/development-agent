"""
Review models for the Reviewing Agent.
"""
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field


@dataclass
class ReviewInput:
    """Input for a review run."""
    owner: str
    repo: str
    pr_number: int
    # Optional pre-fetched data (if already available)
    issue_title: Optional[str] = None
    issue_body: Optional[str] = None
    diff: Optional[str] = None
    head_sha: Optional[str] = None
    check_runs: Optional[list[dict]] = None
    coding_agent_summary: Optional[str] = None


@dataclass
class ReviewError:
    """A single error location and fix suggestion."""
    file_path: str
    lines: list[int]  # line numbers with the error
    fix_summary: str


@dataclass
class ReviewResult:
    """Result of a review run."""
    is_normal: bool
    requirements_met: bool
    ci_passed: bool
    summary_similarity: float
    reviewer_summary: str
    coding_agent_summary: Optional[str] = None
    errors: list[ReviewError] = field(default_factory=list)


# --- Pydantic models for LLM structured output ---


class ReviewSummaryOutput(BaseModel):
    """LLM output for the review summary step."""

    reviewer_summary: str = Field(
        description="A concise 1-2 sentence summary of what the PR does from a reviewer perspective"
    )
    requirements_met: bool = Field(
        description="Whether the requirements from the issue appear to be fulfilled by the changes"
    )
    issues_found: list[str] = Field(
        default_factory=list,
        description="List of specific issues or problems found (empty if none)",
    )


class ReviewErrorOutput(BaseModel):
    """Single error entry for the errors JSON output."""

    file_path: str = Field(description="Path to the file containing the error")
    lines: list[int] = Field(
        description="Line numbers where the error occurs (e.g. [10, 11, 12])"
    )
    fix_summary: str = Field(
        description="Brief summary of how to fix this error",
    )


class ReviewErrorsOutput(BaseModel):
    """LLM output for the errors-to-JSON step."""

    errors: list[ReviewErrorOutput] = Field(
        default_factory=list,
        description="List of errors with file, lines, and fix summary",
    )
