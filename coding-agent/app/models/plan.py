from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StepAction(str, Enum):
    """Type of action for a plan step."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class StepStatus(str, Enum):
    """Status of a plan step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in the action plan."""
    id: int
    action: StepAction
    file_path: str
    description: str
    details: Optional[str] = None
    depends_on: list[int] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    error_message: Optional[str] = None


@dataclass
class ActionPlan:
    """Complete action plan for implementing an issue."""
    issue_summary: str
    steps: list[PlanStep]
    estimated_files_changed: int = 0
    notes: Optional[str] = None

    def __post_init__(self):
        if self.estimated_files_changed == 0:
            self.estimated_files_changed = len(
                set(s.file_path for s in self.steps))

    def get_pending_steps(self) -> list[PlanStep]:
        """Get all pending steps."""
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def get_next_step(self) -> Optional[PlanStep]:
        """Get the next step to execute."""
        pending = self.get_pending_steps()
        if not pending:
            return None

        for step in pending:
            deps_completed = all(
                self.steps[dep_id - 1].status == StepStatus.COMPLETED
                for dep_id in step.depends_on
                if dep_id <= len(self.steps)
            )
            if deps_completed:
                return step

        return pending[0]

    def mark_step_completed(self, step_id: int) -> None:
        """Mark a step as completed."""
        for step in self.steps:
            if step.id == step_id:
                step.status = StepStatus.COMPLETED
                break

    def mark_step_failed(self, step_id: int, error: str) -> None:
        """Mark a step as failed."""
        for step in self.steps:
            if step.id == step_id:
                step.status = StepStatus.FAILED
                step.error_message = error
                break
