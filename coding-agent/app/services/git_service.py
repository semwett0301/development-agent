import logging
from pathlib import Path
from typing import Optional

from ..clients import GitHubClient, PullRequest
from ..models import IssueSummary, ActionPlan

logger = logging.getLogger(__name__)


class GitService:
    """High-level Git operations for the coding agent."""

    def __init__(self, github_client: GitHubClient, work_dir: str):
        self.github = github_client
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._current_branch_name: Optional[str] = None

    def generate_branch_name(self, issue_number: int, title: str) -> str:
        """Generate a branch name from issue number and title."""
        safe_title = title.lower()
        safe_title = "".join(c if c.isalnum() or c ==
                             " " else "" for c in safe_title)
        safe_title = "-".join(safe_title.split()[:5])
        return f"fix/issue-{issue_number}-{safe_title}"

    def setup_repository(self, repo: str, issue_number: int, title: str, base_branch: str = "main") -> Path:
        """
        Clone repository and create feature branch.

        Input:
            repo: Repository in "owner/repo" format
            issue_number: Issue number for branch naming
            title: Issue title for branch naming
            base_branch: Base branch to branch from

        Output:
            Path to the repository
        """
        owner, repo_name = repo.split("/")

        # Clone or update repository
        repo_path = self.github.clone_repository(
            owner=owner,
            repo=repo_name,
            target_dir=self.work_dir,
            branch=base_branch,
        )

        # Create feature branch
        branch_name = self.generate_branch_name(issue_number, title)
        self._current_branch_name = branch_name
        self.github.create_branch(repo_path, branch_name)

        logger.info(f"Repository setup complete at {
                    repo_path}, branch: {branch_name}")
        return repo_path

    def setup_repository_for_pr(self, repo: str, pr_number: int) -> Path:
        """
        Clone repository and checkout the PR's head branch (for REDO).

        Input:
            repo: Repository in "owner/repo" format
            pr_number: Pull request number

        Output:
            Path to the repository
        """
        owner, repo_name = repo.split("/")
        pr_info = self.github.get_pull_request(repo, pr_number)
        head_ref = pr_info.head_ref

        repo_path = self.github.clone_repository(
            owner=owner,
            repo=repo_name,
            target_dir=self.work_dir,
            branch=head_ref,
        )
        self._current_branch_name = head_ref
        logger.info(
            f"Repository setup for PR #{pr_number} at {repo_path}, branch: {head_ref}"
        )
        return repo_path

    def push_current_branch(self, repo_path: Path) -> None:
        """Push the current branch to origin (no PR creation)."""
        if not self._current_branch_name:
            raise RuntimeError("No current branch set")
        self.github.push_branch(repo_path, self._current_branch_name)
        logger.info(f"Pushed branch: {self._current_branch_name}")

    def commit_all_changes(self, repo_path: Path, message: str, files: Optional[list[str]] = None) -> None:
        """
        Commit all changes to the repository.

        Input:
            repo_path: Path to repository
            message: Commit message
            files: Specific files to commit (None = all)
        """
        self.github.commit_changes(repo_path, message, files)

    def push_and_create_pr(
        self,
        repo: str,
        issue_number: int,
        summary: IssueSummary,
        plan: ActionPlan,
        files_changed: list[str],
        repo_path: Path,
        base_branch: str = "main",
    ) -> PullRequest:
        """
        Push changes and create a pull request.

        Input:
            repo: Repository in "owner/repo" format
            issue_number: Issue number for PR linking
            summary: Issue summary
            plan: Action plan that was executed
            files_changed: List of changed files
            repo_path: Path to repository
            base_branch: Target branch for PR

        Output:
            Created PullRequest
        """
        owner, repo_name = repo.split("/")
        branch_name = self._current_branch_name

        # Push branch
        self.github.push_branch(repo_path, branch_name)

        # Generate PR description
        pr_description = self._generate_pr_description(
            summary=summary,
            plan=plan,
            files_changed=files_changed,
            issue_number=issue_number,
        )

        # Create PR title
        pr_title = f"[{issue_number}] {summary.summary[:60]}"

        # Create PR
        pr = self.github.create_pull_request(
            owner=owner,
            repo=repo_name,
            title=pr_title,
            body=pr_description,
            head_branch=branch_name,
            base_branch=base_branch,
        )

        logger.info(f"Created PR #{pr.number}: {pr.url}")
        return pr

    def _generate_pr_description(
        self,
        summary: IssueSummary,
        plan: ActionPlan,
        files_changed: list[str],
        issue_number: int,
    ) -> str:
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
        sections.append(f"Closes #{issue_number}")
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
