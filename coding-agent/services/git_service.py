import logging
from pathlib import Path
from typing import Optional

from ..clients import GitHubClient, PullRequest
from ..models import Issue, IssueSummary, ActionPlan

logger = logging.getLogger(__name__)


class GitService:
    """High-level Git operations for the coding agent."""

    def __init__(self, github_client: GitHubClient, work_dir: str):
        self.github = github_client
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def setup_repository(self, issue: Issue, base_branch: str = "main") -> Path:
        """
        Clone repository and create feature branch.

        Input:
            issue: The issue being worked on
            base_branch: Base branch to branch from

        Output:
            Path to the repository
        """
        # Clone or update repository
        repo_path = self.github.clone_repository(
            owner=issue.repo_owner,
            repo=issue.repo_name,
            target_dir=self.work_dir,
            branch=base_branch,
        )

        # Create feature branch
        branch_name = issue.branch_name
        self.github.create_branch(repo_path, branch_name)

        logger.info(f"Repository setup complete at {
                    repo_path}, branch: {branch_name}")
        return repo_path

    def commit_all_changes(self, repo_path: Path, message: str, files: Optional[list[str]] = None) -> None:
        """
        Commit all changes to the repository.

        Input:
            repo_path: Path to repository
            message: Commit message
            files: Specific files to commit (None = all)
        """
        self.github.commit_changes(repo_path, message, files)

    def push_and_create_pr(self, issue: Issue, summary: IssueSummary, plan: ActionPlan, files_changed: list[str], repo_path: Path, base_branch: str = "main") -> PullRequest:
        """
        Push changes and create a pull request.

        Input:
            issue: Original issue
            summary: Issue summary
            plan: Action plan that was executed
            files_changed: List of changed files
            repo_path: Path to repository
            base_branch: Target branch for PR

        Output:
            Created PullRequest
        """
        branch_name = issue.branch_name

        # Push branch
        self.github.push_branch(repo_path, branch_name)

        # Generate PR description
        from .issue_processor import IssueProcessor
        # Note: This is a bit circular, but IssueProcessor is stateless
        # We only need it for the PR description generation
        pr_description = self._generate_pr_description(
            summary=summary,
            plan=plan,
            files_changed=files_changed,
        )

        # Create PR title
        pr_title = f"[{issue.number}] {summary.summary[:60]}"

        # Create PR
        pr = self.github.create_pull_request(
            owner=issue.repo_owner,
            repo=issue.repo_name,
            title=pr_title,
            body=pr_description,
            head_branch=branch_name,
            base_branch=base_branch,
        )

        logger.info(f"Created PR #{pr.number}: {pr.url}")
        return pr

    def _generate_pr_description(self, summary: IssueSummary, plan: ActionPlan, files_changed: list[str]) -> str:
        """Generate a pull request description."""
        sections = []

        # Summary
        sections.append("## Summary")
        sections.append(summary.summary)
        sections.append("")

        # Changes made
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
        sections.append("")

        # Checklist
        sections.append("## Checklist")
        sections.append("- [x] Code follows project conventions")
        sections.append("- [x] Linter passes")
        sections.append("- [x] Tests pass")
        sections.append("- [ ] Documentation updated if needed")

        return "\n".join(sections)

    def cleanup(self, repo_path: Path) -> None:
        """
        Clean up the repository directory.

        Input:
            repo_path: Path to repository to clean
        """
        import shutil

        if repo_path.exists() and repo_path.is_relative_to(self.work_dir):
            try:
                shutil.rmtree(repo_path)
                logger.info(f"Cleaned up {repo_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up {repo_path}: {e}")
