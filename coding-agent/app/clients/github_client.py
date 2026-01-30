"""
GitHub API client for the Coding Agent.

Uses GitHub App authentication with automatic token refresh.
"""
import logging
from dataclasses import dataclass

import httpx

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
        token = asyncio.get_event_loop().run_until_complete(
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
        token = asyncio.get_event_loop().run_until_complete(
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
        token = asyncio.get_event_loop().run_until_complete(
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
        token = asyncio.get_event_loop().run_until_complete(
            self._token_manager.get_token_for_repo(repo)
        )
        return f"https://x-access-token:{token}@github.com/{repo}.git"
