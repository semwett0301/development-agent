"""
Coding Agent - Main orchestrator for automated code generation.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from langfuse import observe, get_client

from .config import AgentConfig, load_config
from .models import Issue, IssueSummary, ActionPlan, StepStatus
from .clients import LLMClient, GitHubClient, ChromaClient, PullRequest, get_langfuse_callback, flush_langfuse
from .services import (
    IssueProcessor,
    CodeSearchService,
    CodeGenerator,
    ConfigFinder,
    Validator,
    GitService,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of agent execution."""
    success: bool
    issue: Issue
    repo: str
    issue_number: int
    summary: Optional[IssueSummary] = None
    plan: Optional[ActionPlan] = None
    pull_request: Optional[PullRequest] = None
    files_changed: list[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.files_changed is None:
            self.files_changed = []


class CodingAgent:
    """
    Main coding agent that orchestrates the full workflow.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or load_config()

        langfuse_callbacks = get_langfuse_callback(self.config.langfuse)

        self.llm_client = LLMClient(
            self.config.llm, langfuse_callbacks=langfuse_callbacks)
        self.github_client = GitHubClient(self.config.github)
        self.chroma_client = ChromaClient(self.config.chroma)

        llm = self.llm_client.llm

        self.issue_processor = IssueProcessor(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.code_search = CodeSearchService(self.chroma_client)
        self.code_generator = CodeGenerator(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.config_finder = ConfigFinder()
        self.validator = Validator(
            llm, self.config_finder, langfuse_callbacks=langfuse_callbacks)
        self.git_service = GitService(self.github_client, self.config.work_dir)

    def process_issue(
            self,
            issue: Issue,
            repo: str,
            issue_number: int,
            base_branch: str = "main",
    ) -> AgentResult:
        """Process a GitHub issue end-to-end."""
        logger.info(f"Processing issue #{issue_number}: {issue.title}")

        repo_name = repo.split("/")[1]
        result = AgentResult(success=False, issue=issue,
                             repo=repo, issue_number=issue_number)

        try:
            logger.info("Step 1: Setting up repository...")
            repo_path = self.git_service.setup_repository(
                repo=repo,
                issue_number=issue_number,
                title=issue.title,
                base_branch=base_branch,
            )

            logger.info("Step 2: Summarizing issue...")
            summary = self.issue_processor.summarize_issue(issue)
            result.summary = summary
            logger.info(f"Summary: {summary.summary}")

            logger.info("Step 3: Searching for relevant code...")
            search_results = self.code_search.search_for_issue(
                summary=summary,
                repo_name=repo_name,
            )
            code_context = self.code_search.build_context(search_results)
            project_structure = self.code_search.get_project_structure(
                repo_path)

            logger.info("Step 4: Creating action plan...")
            project_language = self.code_generator.get_project_language(
                repo_path)
            plan = self.issue_processor.create_action_plan(
                summary=summary,
                code_context=code_context,
                project_structure=project_structure,
                project_language=project_language,
            )
            result.plan = plan
            logger.info(f"Plan has {len(plan.steps)} steps")

            logger.info("Step 5: Executing plan...")
            files_changed = self._execute_plan(
                plan=plan,
                repo_path=repo_path,
                repo_name=repo_name,
            )
            result.files_changed = files_changed

            logger.info("Step 6: Validating changes...")
            validation_success = self._validate_and_fix(repo_path)

            if not validation_success:
                result.error = "Validation failed after max retries"
                logger.error(result.error)
                return result

            logger.info("Step 7: Committing changes...")
            commit_message = self.issue_processor.create_commit_message(
                summary=summary,
                changes_description=f"Changed {len(files_changed)} files",
                issue_number=issue_number,
            )
            self.git_service.commit_all_changes(
                repo_path=repo_path,
                message=commit_message,
            )

            logger.info("Step 8: Creating pull request...")
            pr = self.git_service.push_and_create_pr(
                repo=repo,
                issue_number=issue_number,
                summary=summary,
                plan=plan,
                files_changed=files_changed,
                repo_path=repo_path,
                base_branch=base_branch,
            )
            result.pull_request = pr
            result.success = True

            logger.info(f"Success! Created PR: {pr.url}")
            return result

        except Exception as e:
            logger.exception(f"Failed to process issue: {e}")
            result.error = str(e)
            return result

    def _execute_plan(self, plan: ActionPlan, repo_path: Path, repo_name: str) -> list[str]:
        """Execute all steps in the action plan."""
        all_files_changed = []
        conventions = self.code_generator.get_project_conventions(repo_path)

        for step in plan.steps:
            logger.info(f"Executing step {step.id}: {step.description}")
            step.status = StepStatus.IN_PROGRESS

            try:
                current_content = self.code_search.get_file_content(
                    step.file_path,
                    repo_path,
                )

                related_results = self.code_search.search_for_step(
                    step=step,
                    repo_name=repo_name,
                )
                related_context = self.code_search.build_context(
                    related_results)

                changes = self.code_generator.generate_for_step(
                    step=step,
                    current_content=current_content,
                    related_context=related_context,
                    conventions=conventions,
                    repo_path=repo_path,
                )

                files_changed = self.code_generator.apply_changes(
                    changes, repo_path)
                all_files_changed.extend(files_changed)

                plan.mark_step_completed(step.id)
                logger.info(f"Step {step.id} completed, changed: {
                    files_changed}")

            except Exception as e:
                logger.error(f"Step {step.id} failed: {e}")
                plan.mark_step_failed(step.id, str(e))

        return list(set(all_files_changed))

    def _validate_and_fix(self, repo_path: Path) -> bool:
        """Run validation and fix errors with retries."""
        commands = self.config_finder.find_commands(repo_path)

        # Install dependencies first
        logger.info(f"Installing dependencies for {commands.project_type} project...")
        if not self.validator.install_dependencies(repo_path, commands):
            logger.warning("Dependency installation failed, continuing with validation anyway")

        for attempt in range(1, self.config.max_fix_attempts + 1):
            logger.info(f"Validation attempt {
                attempt}/{self.config.max_fix_attempts}")

            result = self.validator.validate(repo_path, commands)

            if result.success:
                logger.info("Validation passed!")
                return True

            logger.warning(f"Validation failed: {len(result.lint_errors)} lint errors, "
                           f"{len(result.test_errors)} test failures")

            if attempt < self.config.max_fix_attempts:
                logger.info("Attempting to fix errors...")
                fixes = self.validator.fix_errors(result, repo_path)

                if fixes.fixes:
                    fixed_files = self.validator.apply_fixes(fixes, repo_path)
                    logger.info(f"Applied fixes to {len(fixed_files)} files")
                else:
                    logger.warning("No fixes generated")
                    break

        return False


@observe()
def run_agent(
        repo: str,
        issue_number: int,
        base_branch: str = "main",
        config: Optional[AgentConfig] = None,
) -> AgentResult:
    """
    Run the coding agent on a specific issue.

    Args:
        repo: Repository in "owner/repo" format
        issue_number: Issue number to process
        base_branch: Branch to base changes on
        config: Optional agent configuration
    """

    get_client().update_current_trace(session_id=f"{repo}#{issue_number}")

    agent = CodingAgent(config)

    issue_data = agent.github_client.get_issue(repo, issue_number)

    issue = Issue(
        title=issue_data.title,
        body=issue_data.body,
        labels=issue_data.labels,
    )

    result = agent.process_issue(issue, repo, issue_number, base_branch)

    if agent.config.langfuse and agent.config.langfuse.is_configured:
        flush_langfuse()

    return result
