from typing import Optional
from pydantic import BaseModel, Field


class IssueSummaryOutput(BaseModel):
    """LLM output for issue summarization."""

    summary: str = Field(
        description="A concise 1-2 sentence summary of what needs to be done"
    )
    requirements: list[str] = Field(
        description="List of specific and actionable requirements"
    )
    acceptance_criteria: list[str] = Field(
        description="List of criteria to verify the issue is resolved"
    )
    affected_areas: list[str] = Field(
        description="Areas of the codebase affected (e.g., 'api', 'database', 'frontend')"
    )


class PlanStepOutput(BaseModel):
    """LLM output for a single plan step."""

    id: int = Field(description="Step ID (sequential number)")
    action: str = Field(
        description="Action type: 'create', 'modify', or 'delete'")
    file_path: str = Field(description="Path to the file to modify")
    description: str = Field(description="What to change in this file")
    details: Optional[str] = Field(
        default=None,
        description="Specific implementation details, function signatures, etc."
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="List of step IDs this step depends on"
    )


class ActionPlanOutput(BaseModel):
    """LLM output for action plan generation."""

    issue_summary: str = Field(
        description="Brief summary suitable for commit messages"
    )
    steps: list[PlanStepOutput] = Field(
        description="List of implementation steps"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Any important considerations or warnings"
    )


class CodeGenerationOutput(BaseModel):
    """LLM output for code generation."""

    file_path: str = Field(description="Path to the file")
    edit_type: str = Field(
        description="Edit type: 'create', 'replace', 'insert', or 'delete'")
    new_content: Optional[str] = Field(
        default=None,
        description="The new file content or code to insert"
    )
    commit_message: str = Field(
        description="Commit message in conventional format (e.g., 'feat(auth): add login')"
    )
    explanation: str = Field(
        description="Brief explanation of changes made"
    )


class CodeFixOutput(BaseModel):
    """LLM output for a single file fix."""

    file_path: str = Field(description="Path to the file")
    new_content: str = Field(description="Complete corrected file content")
    issues_fixed: list[str] = Field(
        description="List of issues fixed in this file"
    )


class CodeFixesOutput(BaseModel):
    """LLM output for fixing code errors."""

    fixes: list[CodeFixOutput] = Field(
        description="List of file fixes"
    )
    explanation: str = Field(
        description="Summary of all fixes applied"
    )
    unfixable: list[str] = Field(
        default_factory=list,
        description="List of issues that cannot be automatically fixed"
    )


class LintErrorOutput(BaseModel):
    """LLM output for a single lint error."""

    file_path: str = Field(description="Path to the file")
    line: int = Field(description="Line number")
    column: int = Field(description="Column number")
    message: str = Field(description="Error message")
    rule: Optional[str] = Field(default=None, description="Rule name")
    severity: str = Field(default="error", description="'error' or 'warning'")


class TestErrorOutput(BaseModel):
    """LLM output for a single test error."""

    test_name: str = Field(description="Name of the failed test")
    file_path: Optional[str] = Field(
        default=None, description="Path to test file")
    message: str = Field(description="Failure message")
    traceback: Optional[str] = Field(
        default=None, description="Relevant traceback")
