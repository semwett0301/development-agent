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
    if body:
        m = re.search(r"(?:Closes|Fixes|Resolves)\s+#(\d+)",
                      body, re.IGNORECASE)
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


# Review count marker in PR body
REVIEW_COUNT_MARKER = "<!-- reviewer-agent-count:"
REVIEW_FAILED_MARKER = "<!-- reviewer-agent-failed -->"


def parse_review_count_from_pr_body(body: Optional[str]) -> int:
    """
    Extract the review count from PR body.
    
    Format: <!-- reviewer-agent-count:N -->
    Returns 0 if not found.
    """
    if not body:
        return 0
    match = re.search(r"<!-- reviewer-agent-count:(\d+) -->", body)
    if match:
        return int(match.group(1))
    return 0


def update_review_count_in_body(body: Optional[str], count: int) -> str:
    """
    Update or add the review count marker in PR body.
    
    Returns updated body.
    """
    body = body or ""
    marker = f"<!-- reviewer-agent-count:{count} -->"
    
    # Check if marker already exists
    if REVIEW_COUNT_MARKER in body:
        # Replace existing marker
        return re.sub(
            r"<!-- reviewer-agent-count:\d+ -->",
            marker,
            body
        )
    else:
        # Add marker at the end
        return f"{body}\n\n{marker}"


def add_review_failed_message(body: str, max_attempts: int) -> str:
    """
    Add a failure message to PR body indicating reviewer couldn't fix issues.
    """
    if REVIEW_FAILED_MARKER in body:
        return body  # Already has failure message
    
    failure_message = f"""

---

⚠️ **Reviewer Agent**: После {max_attempts} попыток ревью пайплайны всё ещё падают. 
Требуется ручное вмешательство.

{REVIEW_FAILED_MARKER}
"""
    return body + failure_message


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
        response = self._session.get(
            url, headers=headers, params=params or None)
        response.raise_for_status()
        data = response.json()
        return data.get("check_runs", [])

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        """Fetch an issue (title, body) for review context."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        response = self._session.get(url)
        response.raise_for_status()
        return response.json()

    def update_pull_request(self, owner: str, repo: str, pr_number: int, body: str) -> None:
        """Update pull request body."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self._session.patch(url, json={"body": body})
        response.raise_for_status()
        logger.info(f"Updated PR #{pr_number} body")

    def approve_pull_request(self, owner: str, repo: str, pr_number: int, comment: str = "LGTM! ✅") -> None:
        """Create an approval review on the pull request."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        response = self._session.post(url, json={
            "event": "APPROVE",
            "body": comment,
        })
        response.raise_for_status()
        logger.info(f"Approved PR #{pr_number}")

    def request_changes(self, owner: str, repo: str, pr_number: int, comment: str) -> None:
        """Request changes on the pull request."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        response = self._session.post(url, json={
            "event": "REQUEST_CHANGES",
            "body": comment,
        })
        response.raise_for_status()
        logger.info(f"Requested changes on PR #{pr_number}")
