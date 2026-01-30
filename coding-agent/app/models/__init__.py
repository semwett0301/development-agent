"""
Data models for the Coding Agent.
"""
from .issue import Issue, IssueSummary
from .plan import ActionPlan, PlanStep, StepAction, StepStatus
from .code_change import (
    CodeChange,
    FileEdit,
    ValidationResult,
    EditType,
    LintError,
    TestError,
)

# LLM Output models for PydanticOutputParser
from .llm_outputs import (
    IssueSummaryOutput,
    ActionPlanOutput,
    PlanStepOutput,
    CodeGenerationOutput,
    CodeFixOutput,
    CodeFixesOutput,
    LintErrorOutput,
    TestErrorOutput,
)

__all__ = [
    # Internal models
    "Issue",
    "IssueSummary",
    "ActionPlan",
    "PlanStep",
    "StepAction",
    "StepStatus",
    "CodeChange",
    "FileEdit",
    "EditType",
    "ValidationResult",
    "LintError",
    "TestError",
    # LLM Output models
    "IssueSummaryOutput",
    "ActionPlanOutput",
    "PlanStepOutput",
    "CodeGenerationOutput",
    "CodeFixOutput",
    "CodeFixesOutput",
    "LintErrorOutput",
    "TestErrorOutput",
]
