"""
Coding Agent - Main orchestrator for automated code generation.

This is the entry point that orchestrates the full flow:
1. Receive issue from queue
2. Summarize and create action plan
3. Search for relevant code (RAG)
4. Generate code changes
5. Run linter and tests, fix if needed
6. Create pull request
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of agent execution."""
    success: bool
    issue: Issue
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

    Flow:
    1. Clone repo, create branch
    2. Summarize issue → extract requirements
    3. Generate action plan
    4. For each step:
       - Search for relevant code (RAG)
       - Generate code changes
       - Apply changes
    5. Run linter + tests
    6. If failed → fix → retry (max 3x)
    7. Commit, push, create PR
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or load_config()

        langfuse_callbacks = get_langfuse_callback(self.config.langfuse)

        # Initialize clients
        self.llm_client = LLMClient(
            self.config.llm, langfuse_callbacks=langfuse_callbacks)
        self.github_client = GitHubClient(self.config.github)
        self.chroma_client = ChromaClient(self.config.chroma)

        # Get the underlying LangChain LLM for services
        llm = self.llm_client.llm

        # Initialize services (now use LangChain LLM directly)
        self.issue_processor = IssueProcessor(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.code_search = CodeSearchService(self.chroma_client)
        self.code_generator = CodeGenerator(
            llm, langfuse_callbacks=langfuse_callbacks)
        self.config_finder = ConfigFinder()
        self.validator = Validator(
            llm, self.config_finder, langfuse_callbacks=langfuse_callbacks)
        self.git_service = GitService(self.github_client, self.config.work_dir)

    def process_issue(self, issue: Issue, base_branch: str = "main") -> AgentResult:
        """
        Process a GitHub issue end-to-end.

        Input:
            issue: The issue to process
            base_branch: Branch to base changes on

        Output:
            AgentResult with execution details
        """
        logger.info(f"Processing issue #{issue.number}: {issue.title}")

        result = AgentResult(success=False, issue=issue)
        repo_path = None

        try:
            # Step 1: Setup repository
            logger.info("Step 1: Setting up repository...")
            repo_path = self.git_service.setup_repository(issue, base_branch)

            # Step 2: Summarize issue
            logger.info("Step 2: Summarizing issue...")
            summary = self.issue_processor.summarize_issue(issue)
            result.summary = summary
            logger.info(f"Summary: {summary.summary}")

            # Step 3: Search for relevant code
            logger.info("Step 3: Searching for relevant code...")
            search_results = self.code_search.search_for_issue(
                summary=summary,
                repo_name=issue.repo_name,
            )
            code_context = self.code_search.build_context(search_results)
            project_structure = self.code_search.get_project_structure(
                repo_path)

            # Step 4: Create action plan
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

            # Step 5: Execute plan
            logger.info("Step 5: Executing plan...")
            files_changed = self._execute_plan(
                plan=plan,
                repo_path=repo_path,
                issue=issue,
            )
            result.files_changed = files_changed

            # Step 6: Validate and fix
            logger.info("Step 6: Validating changes...")
            validation_success = self._validate_and_fix(repo_path)

            if not validation_success:
                result.error = "Validation failed after max retries"
                logger.error(result.error)
                return result

            # Step 7: Commit changes
            logger.info("Step 7: Committing changes...")
            commit_message = self.issue_processor.create_commit_message(
                summary=summary,
                changes_description=f"Changed {len(files_changed)} files",
            )
            self.git_service.commit_all_changes(
                repo_path=repo_path,
                message=commit_message,
            )

            # Step 8: Push and create PR
            logger.info("Step 8: Creating pull request...")
            pr = self.git_service.push_and_create_pr(
                issue=issue,
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

    def _execute_plan(self, plan: ActionPlan, repo_path: Path, issue: Issue) -> list[str]:
        """Execute all steps in the action plan."""
        all_files_changed = []
        conventions = self.code_generator.get_project_conventions(repo_path)

        for step in plan.steps:
            logger.info(f"Executing step {step.id}: {step.description}")
            step.status = StepStatus.IN_PROGRESS

            try:
                # Get current file content
                current_content = self.code_search.get_file_content(
                    step.file_path,
                    repo_path,
                )

                # Search for related code
                related_results = self.code_search.search_for_step(
                    step=step,
                    repo_name=issue.repo_name,
                )
                related_context = self.code_search.build_context(
                    related_results)

                # Generate code changes
                changes = self.code_generator.generate_for_step(
                    step=step,
                    current_content=current_content,
                    related_context=related_context,
                    conventions=conventions,
                    repo_path=repo_path,
                )

                # Apply changes
                files_changed = self.code_generator.apply_changes(
                    changes, repo_path)
                all_files_changed.extend(files_changed)

                plan.mark_step_completed(step.id)
                logger.info(f"Step {step.id} completed, changed: {
                            files_changed}")

            except Exception as e:
                logger.error(f"Step {step.id} failed: {e}")
                plan.mark_step_failed(step.id, str(e))

        return list(set(all_files_changed))  # Deduplicate

    def _validate_and_fix(self, repo_path: Path) -> bool:
        """Run validation and fix errors with retries."""
        commands = self.config_finder.find_commands(repo_path)

        for attempt in range(1, self.config.max_fix_attempts + 1):
            logger.info(f"Validation attempt {
                        attempt}/{self.config.max_fix_attempts}")

            # Run validation
            result = self.validator.validate(repo_path, commands)

            if result.success:
                logger.info("Validation passed!")
                return True

            logger.warning(f"Validation failed: {len(result.lint_errors)} lint errors, "
                           f"{len(result.test_errors)} test failures")

            if attempt < self.config.max_fix_attempts:
                # Try to fix errors
                logger.info("Attempting to fix errors...")
                fixes = self.validator.fix_errors(result, repo_path)

                if fixes.fixes:
                    fixed_files = self.validator.apply_fixes(fixes, repo_path)
                    logger.info(f"Applied fixes to {len(fixed_files)} files")
                else:
                    logger.warning("No fixes generated")
                    break

        return False

    def process_issue_from_payload(self, payload: dict, base_branch: str = "main") -> AgentResult:
        """
        Process an issue from a webhook payload.

        Input:
            payload: GitHub webhook payload
            base_branch: Branch to base changes on

        Output:
            AgentResult with execution details
        """
        # Extract issue from payload
        issue_data = payload.get("issue", payload)
        repo_data = payload.get("repository", {})

        issue = Issue(
            id=issue_data.get("id", 0),
            number=issue_data.get("number", 0),
            title=issue_data.get("title", ""),
            body=issue_data.get("body", ""),
            repo_owner=repo_data.get("owner", {}).get("login", ""),
            repo_name=repo_data.get("name", ""),
            labels=[l.get("name", "") for l in issue_data.get("labels", [])],
            url=issue_data.get("html_url"),
        )

        return self.process_issue(issue, base_branch)


def _observe_if_available(fn):
    """Wrap in Langfuse @observe when available so all steps appear in one trace graph."""
    try:
        from langfuse import observe
        return observe(name="coding_agent_run")(fn)
    except ImportError:
        return fn


# Convenience function for direct execution
@_observe_if_available
def run_agent(owner: str, repo: str, issue_number: int, base_branch: str = "main", config: Optional[AgentConfig] = None) -> AgentResult:
    """
    Run the coding agent on a specific issue.

    Input:
        owner: Repository owner
        repo: Repository name
        issue_number: Issue number to process
        base_branch: Branch to base changes on
        config: Optional agent configuration

    Output:
        AgentResult with execution details
    """
    agent = CodingAgent(config)

    # Fetch issue from GitHub
    issue = agent.github_client.get_issue(owner, repo, issue_number)

    result = agent.process_issue(issue, base_branch)
    # Flush Langfuse in short-lived runs so traces appear in the dashboard
    if agent.config.langfuse and agent.config.langfuse.is_configured:
        flush_langfuse()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Coding Agent")
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--issue", type=int,
                        required=True, help="Issue number")
    parser.add_argument("--branch", default="main", help="Base branch")

    args = parser.parse_args()

    result = run_agent(
        owner=args.owner,
        repo=args.repo,
        issue_number=args.issue,
        base_branch=args.branch,
    )

    if result.success:
        print(f"Success! PR created: {result.pull_request.url}")
    else:
        print(f"Failed: {result.error}")
        exit(1)
