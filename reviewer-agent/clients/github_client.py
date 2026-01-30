"""
GitHub API client for the Reviewing Agent.
Uses same env (GITHUB_TOKEN) as coding_agent; provides PR, diff, check runs.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

from ..config import GitHubConfig

logger = logging.getLogger(__name__)


@dataclass
class PullRequestData:
    """Pull request data from API."""
    number: int
    title: str
    body: Optional[str]
    head_sha: str
    base_ref: str
    html_url: str


def parse_issue_number_from_pr(body: Optional[str], title: Optional[str] = None) -> Optional[int]:
    """
    Extract linked issue number from PR body (Closes #N, Fixes #N) or title ([N] ...).
    """
    import re
    if body:
        m = re.search(r"(?:Closes|Fixes|Resolves)\s+#(\d+)", body, re.IGNORECASE)
        if m:
            return int(m.group(1))
    if title:
        m = re.match(r"\[(\d+)\]\s*", title)
        if m:
            return int(m.group(1))
    return None


def parse_coding_summary_from_pr_body(body: Optional[str]) -> Optional[str]:
    """
    Extract the coding_agent summary from PR body (block ## Summary until next ## or end).

    Matches the format from coding_agent/services/git_service._generate_pr_description.
    """
    if not body or not body.strip():
        return None
    match = re.search(r"## Summary\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip() or None


class GitHubClient:
    """Client for GitHub API (PR, diff, check runs)."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.base_url = config.api_url or "https://api.github.com"
        self._session = requests.Session()
        if config.token:
            self._session.headers["Authorization"] = f"token {config.token}"
        self._session.headers["Accept"] = "application/vnd.github.v3+json"

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> PullRequestData:
        """Fetch a pull request by number."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self._session.get(url)
        response.raise_for_status()
        data = response.json()
        return PullRequestData(
            number=data["number"],
            title=data["title"],
            body=data.get("body"),
            head_sha=data["head"]["sha"],
            base_ref=data["base"]["ref"],
            html_url=data.get("html_url", ""),
        )

    def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch the raw diff of a pull request."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        response = self._session.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def get_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, status: Optional[str] = None
    ) -> list[dict]:
        """List check runs for a commit ref (e.g. PR head SHA)."""
        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{ref}/check-runs"
        headers = {"Accept": "application/vnd.github+json"}
        params = {}
        if status:
            params["status"] = status
        response = self._session.get(url, headers=headers, params=params or None)
        response.raise_for_status()
        data = response.json()
        return data.get("check_runs", [])

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        """Fetch an issue (title, body) for review context."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        response = self._session.get(url)
        response.raise_for_status()
        return response.json()
