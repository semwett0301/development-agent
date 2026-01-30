"""
GitHub API client for the Coding Agent.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import requests

from ..config import GitHubConfig

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
    """Client for interacting with GitHub API."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.base_url = config.api_url
        self._session = requests.Session()
        if config.token:
            self._session.headers["Authorization"] = f"token {config.token}"
        self._session.headers["Accept"] = "application/vnd.github.v3+json"

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        """
        Fetch an issue from GitHub.
        
        Args:
            owner: Repository owner
            repo: Repository name
            issue_number: Issue number
            
        Returns:
            Issue data as dictionary
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        logger.debug(f"Fetching issue: {url}")
        
        response = self._session.get(url)
        response.raise_for_status()
        
        data = response.json()
        
        # Convert to Issue model format
        from ..models import Issue
        return Issue(
            id=data["id"],
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            repo_owner=owner,
            repo_name=repo,
            labels=[l["name"] for l in data.get("labels", [])],
            url=data.get("html_url"),
        )

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequest:
        """
        Create a pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            title: PR title
            body: PR body/description
            head: Source branch
            base: Target branch
            
        Returns:
            PullRequest object
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        
        logger.info(f"Creating PR: {title}")
        response = self._session.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        return PullRequest(
            number=data["number"],
            title=data["title"],
            url=data["url"],
            html_url=data["html_url"],
            state=data["state"],
        )

    def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        """Add a comment to an issue or PR."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        
        response = self._session.post(url, json={"body": body})
        response.raise_for_status()
        
        return response.json()

    def clone_url(self, owner: str, repo: str) -> str:
        """Get the clone URL for a repository."""
        if self.config.token:
            return f"https://{self.config.token}@github.com/{owner}/{repo}.git"
        return f"https://github.com/{owner}/{repo}.git"
