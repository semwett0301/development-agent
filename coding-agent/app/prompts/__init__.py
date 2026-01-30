"""
Prompt templates for the Coding Agent.

Each prompt module exports:
- *_SYSTEM: System prompt for LangChain ChatPromptTemplate
- *_HUMAN: Human prompt template with {format_instructions} placeholder
"""
from .summary_issue import (
    SUMMARY_ISSUE_SYSTEM,
    SUMMARY_ISSUE_HUMAN,
)
from .make_plan import (
    MAKE_PLAN_SYSTEM,
    MAKE_PLAN_HUMAN,
)
from .generate_code import (
    GENERATE_CODE_SYSTEM,
    GENERATE_CODE_HUMAN,
    ACTION_INSTRUCTIONS,
)
from .fix_code import (
    FIX_CODE_SYSTEM,
    FIX_CODE_HUMAN,
    PARSE_LINT_ERRORS_PROMPT,
    PARSE_TEST_ERRORS_PROMPT,
)

__all__ = [
    # Summary issue prompts
    "SUMMARY_ISSUE_SYSTEM",
    "SUMMARY_ISSUE_HUMAN",
    # Make plan prompts
    "MAKE_PLAN_SYSTEM",
    "MAKE_PLAN_HUMAN",
    # Generate code prompts
    "GENERATE_CODE_SYSTEM",
    "GENERATE_CODE_HUMAN",
    "ACTION_INSTRUCTIONS",
    # Fix code prompts
    "FIX_CODE_SYSTEM",
    "FIX_CODE_HUMAN",
    "PARSE_LINT_ERRORS_PROMPT",
    "PARSE_TEST_ERRORS_PROMPT",
]
