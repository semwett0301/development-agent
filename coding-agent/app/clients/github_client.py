"""
GitHub API client for the Coding Agent.

Uses GitHub App authentication with automatic token refresh.
"""
import logging
from dataclasses import dataclass

from pathlib import Path

import httpx
from git import Repo

from ..config import GitHubAppConfig
from shared.github import GitHubAppTokenManager

logger = logging.getLogger(__name__)


@dataclass
class PullRequest:
    """Represents a GitHub Pull Request."""
    number: int
    title: str
    url: str
    html_url: str
    state: str = "open"


class GitHubClient:
    """Client for interacting with GitHub API using GitHub App authentication."""

    def __init__(self, config: GitHubAppConfig):
        self.config = config
        self.base_url = config.api_url
        self._token_manager = GitHubAppTokenManager(
            app_id=config.app_id,
            private_key=config.private_key,
            api_url=config.api_url,
        )

    def _get_headers(self, token: str) -> dict:
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_issue(self, repo: str, issue_number: int):
        """
        Fetch an issue from GitHub.

        Args:
            repo: Repository in "owner/repo" format
            issue_number: Issue number

        Returns:
            Issue object with title, body, labels
        """
        import asyncio
        token = asyncio.run(
            self._token_manager.get_token_for_repo(repo)
        )

        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}"
        logger.debug(f"Fetching issue: {url}")

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(token))
            response.raise_for_status()

        data = response.json()

        from ..models import Issue
        return Issue(
            title=data["title"],
            body=data.get("body", ""),
            labels=[label["name"] for label in data.get("labels", [])],
        )

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequest:
        """
        Create a pull request.

        Args:
            repo: Repository in "owner/repo" format
            title: PR title
            body: PR body/description
            head: Source branch
            base: Target branch

        Returns:
            PullRequest object
        """
        import asyncio
        token = asyncio.run(
            self._token_manager.get_token_for_repo(repo)
        )

        url = f"{self.base_url}/repos/{repo}/pulls"

        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }

        logger.info(f"Creating PR: {title}")

        with httpx.Client() as client:
            response = client.post(
                url, headers=self._get_headers(token), json=payload)
            response.raise_for_status()

        data = response.json()
        return PullRequest(
            number=data["number"],
            title=data["title"],
            url=data["url"],
            html_url=data["html_url"],
            state=data["state"],
        )

    def add_comment(self, repo: str, issue_number: int, body: str) -> dict:
        """Add a comment to an issue or PR."""
        import asyncio
        token = asyncio.run(
            self._token_manager.get_token_for_repo(repo)
        )

        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}/comments"

        with httpx.Client() as client:
            response = client.post(
                url, headers=self._get_headers(token), json={"body": body})
            response.raise_for_status()

        return response.json()

    def get_clone_url(self, repo: str) -> str:
        """Get the authenticated clone URL for a repository."""
        import asyncio
        token = asyncio.run(
            self._token_manager.get_token_for_repo(repo)
        )
        return f"https://x-access-token:{token}@github.com/{repo}.git"

    def clone_repository(self, owner: str, repo: str, target_dir: Path, branch: str = "main") -> Path:
        """Clone a repository or pull latest if it already exists."""
        full_repo = f"{owner}/{repo}"
        repo_path = Path(target_dir) / repo

        if repo_path.exists():
            logger.info(f"Repository already exists at {
                        repo_path}, pulling latest")
            git_repo = Repo(repo_path)
            git_repo.remotes.origin.pull(branch)
        else:
            clone_url = self.get_clone_url(full_repo)
            logger.info(f"Cloning {full_repo} into {repo_path}")
            Repo.clone_from(clone_url, repo_path, branch=branch)

        return repo_path

    def create_branch(self, repo_path: Path, branch_name: str) -> None:
        """Create and checkout a new branch."""
        git_repo = Repo(repo_path)
        git_repo.git.checkout("-b", branch_name)
        logger.info(f"Created and checked out branch: {branch_name}")

    def commit_changes(self, repo_path: Path, message: str, files: list[str] | None = None) -> None:
        """Stage and commit changes."""
        git_repo = Repo(repo_path)
        if files:
            git_repo.index.add(files)
        else:
            git_repo.git.add("-A")
        git_repo.index.commit(message)
        logger.info(f"Committed: {message}")

    def push_branch(self, repo_path: Path, branch_name: str) -> None:
        """Push a branch to the remote."""
        git_repo = Repo(repo_path)
        git_repo.remotes.origin.push(branch_name)
        logger.info(f"Pushed branch: {branch_name}")
