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
from .clients import LLMClient, GitHubClient, PullRequest, get_langfuse_callback, flush_langfuse
from .services import (
    IssueProcessor,
    CodeSearchService,
    CodeGenerator,
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

        llm = self.llm_client.llm

        self.issue_processor = IssueProcessor(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.code_search = CodeSearchService()
        self.code_generator = CodeGenerator(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.git_service = GitService(self.github_client, self.config.work_dir)

    def process_issue_redo(
            self,
            issue: Issue,
            repo: str,
            issue_number: int,
            pr_number: int,
    ) -> AgentResult:
        """Process REDO: checkout PR branch, re-run plan/execute, commit and push (no new PR)."""
        logger.info(f"REDO: Processing issue #{issue_number}, PR #{pr_number}")

        repo_name = repo.split("/")[1]
        result = AgentResult(success=False, issue=issue,
                             repo=repo, issue_number=issue_number)

        try:
            logger.info("Step 1: Setting up repository (PR branch)...")
            repo_path = self.git_service.setup_repository_for_pr(repo, pr_number)

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
            project_structure = self.code_search.get_project_structure(repo_path)

            logger.info("Step 4: Creating action plan...")
            project_language = self.code_generator.get_project_language(repo_path)
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

            logger.info("Step 6: Committing changes...")
            commit_message = self.issue_processor.create_commit_message(
                summary=summary,
                changes_description=f"REDO: changed {len(files_changed)} files",
                issue_number=issue_number,
            )
            self.git_service.commit_all_changes(
                repo_path=repo_path,
                message=commit_message,
            )

            logger.info("Step 7: Pushing to PR branch...")
            self.git_service.push_current_branch(repo_path)
            owner, repo_name = repo.split("/")
            result.pull_request = PullRequest(
                number=pr_number,
                title="",
                url=f"{self.github_client.base_url}/repos/{owner}/{repo_name}/pulls/{pr_number}",
                html_url=f"https://github.com/{owner}/{repo_name}/pull/{pr_number}",
                state="open",
            )
            result.success = True
            logger.info(f"REDO success: pushed to PR #{pr_number}")
            return result

        except Exception as e:
            logger.exception(f"Failed REDO: {e}")
            result.error = str(e)
            return result

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

            logger.info("Step 6: Committing changes...")
            commit_message = self.issue_processor.create_commit_message(
                summary=summary,
                changes_description=f"Changed {len(files_changed)} files",
                issue_number=issue_number,
            )
            self.git_service.commit_all_changes(
                repo_path=repo_path,
                message=commit_message,
            )

            logger.info("Step 7: Creating pull request...")
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


@observe()
def run_agent(
        repo: str,
        issue_number: int,
        base_branch: str = "main",
        pull_request_number: Optional[int] = None,
        config: Optional[AgentConfig] = None,
) -> AgentResult:
    """
    Run the coding agent on a specific issue.

    Args:
        repo: Repository in "owner/repo" format
        issue_number: Issue number to process
        base_branch: Branch to base changes on (START only)
        pull_request_number: If set, REDO mode: checkout PR branch, fix, push
        config: Optional agent configuration
    """
    get_client().update_current_trace(
        session_id=f"{repo}#{issue_number}" + (f"#pr{pull_request_number}" if pull_request_number else "")
    )

    agent = CodingAgent(config)

    issue_data = agent.github_client.get_issue(repo, issue_number)

    issue = Issue(
        title=issue_data.title,
        body=issue_data.body,
        labels=issue_data.labels,
    )

    if pull_request_number is not None:
        result = agent.process_issue_redo(
            issue, repo, issue_number, pull_request_number
        )
    else:
        result = agent.process_issue(issue, repo, issue_number, base_branch)

    if agent.config.langfuse and agent.config.langfuse.is_configured:
        flush_langfuse()

    return result
