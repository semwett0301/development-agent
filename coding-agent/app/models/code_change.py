from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EditType(str, Enum):
    """Type of file edit."""
    CREATE = "create"
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


@dataclass
class FileEdit:
    """A single edit to a file."""
    file_path: str
    edit_type: EditType
    new_content: Optional[str] = None
    old_content: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


@dataclass
class CodeChange:
    """Collection of file edits for a single plan step."""
    step_id: int
    edits: list[FileEdit]
    commit_message: str
    description: str


@dataclass
class LintError:
    """A single linter error."""
    file_path: str
    line: int
    column: int
    message: str
    rule: Optional[str] = None
    severity: str = "error"


@dataclass
class TestError:
    """A single test failure."""
    test_name: str
    file_path: Optional[str]
    message: str
    traceback: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of running linter and tests."""
    success: bool
    lint_errors: list[LintError] = field(default_factory=list)
    test_errors: list[TestError] = field(default_factory=list)
    lint_output: str = ""
    test_output: str = ""
    lint_command: Optional[str] = None
    test_command: Optional[str] = None

    @property
    def has_lint_errors(self) -> bool:
        return len(self.lint_errors) > 0

    @property
    def has_test_errors(self) -> bool:
        return len(self.test_errors) > 0

    def get_error_summary(self) -> str:
        """Get a summary of all errors for LLM context."""
        parts = []

        if self.lint_errors:
            parts.append("=== LINT ERRORS ===")
            for err in self.lint_errors[:10]:
                parts.append(f"{err.file_path}:{err.line}:{
                             err.column} - {err.message}")

        if self.test_errors:
            parts.append("\n=== TEST FAILURES ===")
            for err in self.test_errors[:5]:
                parts.append(f"{err.test_name}: {err.message}")
                if err.traceback:
                    parts.append(err.traceback[:500])

        return "\n".join(parts)
