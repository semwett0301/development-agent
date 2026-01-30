"""
Service for processing and analyzing GitHub issues.
Uses LangChain chains for structured LLM interactions.
"""
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from ..models import (
    Issue,
    IssueSummary,
    ActionPlan,
    PlanStep,
    StepAction,
    IssueSummaryOutput,
    ActionPlanOutput,
)
from ..chains import create_summarize_chain, create_plan_chain

logger = logging.getLogger(__name__)


class IssueProcessor:
    """Process and analyze GitHub issues using LangChain."""

    def __init__(self, llm: BaseChatModel, langfuse_callbacks: Optional[list] = None):
        """
        Initialize the issue processor.

        Args:
            llm: LangChain chat model to use
            langfuse_callbacks: Optional list of callbacks for Langfuse tracing
        """
        self.llm = llm
        self._langfuse_callbacks = langfuse_callbacks
        self._summarize_chain: Optional[Runnable] = None
        self._plan_chain: Optional[Runnable] = None

    @property
    def summarize_chain(self) -> Runnable:
        """Lazy-loaded summarize chain."""
        if self._summarize_chain is None:
            self._summarize_chain = create_summarize_chain(self.llm)
        return self._summarize_chain

    @property
    def plan_chain(self) -> Runnable:
        """Lazy-loaded plan chain."""
        if self._plan_chain is None:
            self._plan_chain = create_plan_chain(self.llm)
        return self._plan_chain

    def summarize_issue(self, issue: Issue) -> IssueSummary:
        """
        Summarize an issue and extract requirements.

        Args:
            issue: The GitHub issue to summarize

        Returns:
            IssueSummary with extracted information
        """
        logger.info(f"Summarizing issue #{issue.number}: {issue.title}")

        # Invoke the chain with issue data
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        result: IssueSummaryOutput = self.summarize_chain.invoke({
            "title": issue.title,
            "body": issue.body or "No description provided",
            "labels": ", ".join(issue.labels) if issue.labels else "None",
        }, **invoke_kwargs)

        # Convert LLM output to internal model
        return IssueSummary(
            original_issue=issue,
            summary=result.summary,
            requirements=result.requirements,
            acceptance_criteria=result.acceptance_criteria,
            affected_areas=result.affected_areas,
        )

    def create_action_plan(
        self,
        summary: IssueSummary,
        code_context: str,
        project_structure: str,
        project_language: str = "Infer from project structure and code context.",
    ) -> ActionPlan:
        """
        Create an action plan for implementing the issue.

        Args:
            summary: Summarized issue
            code_context: Relevant code snippets from RAG
            project_structure: Project file structure
            project_language: Detected language/stack (e.g. "TypeScript/JavaScript. Use .ts, .tsx")

        Returns:
            ActionPlan with implementation steps
        """
        logger.info(f"Creating action plan for issue #{
                    summary.original_issue.number}")

        # Invoke the chain
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        result: ActionPlanOutput = self.plan_chain.invoke({
            "summary": summary.summary,
            "requirements": "\n".join(f"- {r}" for r in summary.requirements),
            "acceptance_criteria": "\n".join(f"- {c}" for c in summary.acceptance_criteria),
            "code_context": code_context or "No relevant code found",
            "project_structure": project_structure or "Structure not available",
            "project_language": project_language,
        }, **invoke_kwargs)

        # Convert LLM output to internal models
        steps = []
        for step_data in result.steps:
            steps.append(PlanStep(
                id=step_data.id,
                action=StepAction(step_data.action),
                file_path=step_data.file_path,
                description=step_data.description,
                details=step_data.details,
                depends_on=step_data.depends_on,
            ))

        return ActionPlan(
            issue_summary=result.issue_summary,
            steps=steps,
            notes=result.notes,
        )

    def create_commit_message(
        self,
        summary: IssueSummary,
        changes_description: str,
    ) -> str:
        """
        Generate a conventional commit message.

        Args:
            summary: Issue summary
            changes_description: Description of changes made

        Returns:
            Formatted commit message
        """
        # Determine commit type from issue labels or content
        commit_type = "feat"
        if any(label in ["bug", "fix", "bugfix"] for label in summary.original_issue.labels):
            commit_type = "fix"
        elif any(label in ["refactor", "cleanup"] for label in summary.original_issue.labels):
            commit_type = "refactor"
        elif any(label in ["docs", "documentation"] for label in summary.original_issue.labels):
            commit_type = "docs"

        # Determine scope from affected areas
        scope = ""
        if summary.affected_areas:
            scope = f"({summary.affected_areas[0]})"

        # Create message
        title = summary.summary[:50] if len(
            summary.summary) > 50 else summary.summary
        title = title.lower().replace(".", "")

        message = f"{commit_type}{scope}: {title}"

        if changes_description:
            message += f"\n\n{changes_description}"

        message += f"\n\nCloses #{summary.original_issue.number}"

        return message

    def create_pr_description(
        self,
        summary: IssueSummary,
        plan: ActionPlan,
        files_changed: list[str],
    ) -> str:
        """
        Generate a pull request description.

        Args:
            summary: Issue summary
            plan: Executed action plan
            files_changed: List of changed file paths

        Returns:
            Formatted PR description in markdown
        """
        sections = []

        # Summary
        sections.append("## Summary")
        sections.append(summary.summary)
        sections.append("")

        # Changes
        sections.append("## Changes")
        for step in plan.steps:
            status = "✅" if step.status.value == "completed" else "❌"
            sections.append(f"- {status} {step.description}")
        sections.append("")

        # Files changed
        sections.append("## Files Changed")
        for file in files_changed:
            sections.append(f"- `{file}`")
        sections.append("")

        # Related issue
        sections.append("## Related Issue")
        issue = summary.original_issue
        sections.append(f"Closes #{issue.number}")
        if issue.url:
            sections.append(f"Issue: {issue.url}")
        sections.append("")

        # Checklist
        sections.append("## Checklist")
        sections.append("- [ ] Code follows project conventions")
        sections.append("- [ ] Tests pass locally")
        sections.append("- [ ] Documentation updated if needed")

        return "\n".join(sections)
