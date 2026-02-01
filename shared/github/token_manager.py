"""
GitHub App token manager.

Handles JWT creation, installation token retrieval, caching and automatic refresh.
"""
import time
import logging
from dataclasses import dataclass

import jwt
import httpx

logger = logging.getLogger(__name__)

# Token refresh buffer (refresh 5 minutes before expiry)
TOKEN_REFRESH_BUFFER = 300


@dataclass
class InstallationToken:
    """Cached installation access token."""
    token: str
    expires_at: float  # Unix timestamp


class GitHubAppTokenManager:
    """
    Manages GitHub App authentication tokens.

    Usage:
        manager = GitHubAppTokenManager(
            app_id="123456",
            private_key="-----BEGIN RSA PRIVATE KEY-----...",
        )

        # Get token for a specific installation
        token = await manager.get_token(installation_id=12345678)

        # Or get token by repository
        token = await manager.get_token_for_repo("owner/repo")
    """

    def __init__(
            self,
            app_id: str,
            private_key: str,
            api_url: str = "https://api.github.com",
    ):
        self.app_id = app_id
        self.private_key = private_key
        self.api_url = api_url
        self._token_cache: dict[int, InstallationToken] = {}
        # repo -> installation_id
        self._installation_cache: dict[str, int] = {}

    async def get_token_for_repo(self, repo: str) -> str:
        """
        Get an installation access token for a repository.

        Args:
            repo: Repository in "owner/repo" format
        """
        installation_id = self._installation_cache.get(repo)

        if not installation_id:
            installation_id = await self._get_installation_for_repo(repo)
            self._installation_cache[repo] = installation_id

        try:
            return await self._get_token(installation_id)
        except httpx.HTTPStatusError as e:
            # Installation might have changed, invalidate cache and retry
            logger.warning(f"Token fetch failed for installation {
                           installation_id}, refreshing installation_id")
            self._installation_cache.pop(repo, None)
            self._token_cache.pop(installation_id, None)

            installation_id = await self._get_installation_for_repo(repo)
            self._installation_cache[repo] = installation_id
            return await self._get_token(installation_id)

    async def _get_token(self, installation_id: int) -> str:
        """
        Get an installation access token.

        Returns cached token if still valid, otherwise fetches a new one.
        """
        cached = self._token_cache.get(installation_id)

        if cached and cached.expires_at > time.time() + TOKEN_REFRESH_BUFFER:
            return cached.token

        token_data = await self._fetch_installation_token(installation_id)
        return token_data.token

    async def _fetch_installation_token(self, installation_id: int) -> InstallationToken:
        """Fetch a new installation access token from GitHub API."""
        app_jwt = self._create_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            data = response.json()

        # Parse expiration time (ISO 8601 format)
        from datetime import datetime
        expires_at_str = data["expires_at"]
        expires_at = datetime.fromisoformat(
            expires_at_str.replace("Z", "+00:00")).timestamp()

        token_data = InstallationToken(
            token=data["token"],
            expires_at=expires_at,
        )

        self._token_cache[installation_id] = token_data
        logger.debug(f"Fetched new installation token for {
                     installation_id}, expires at {expires_at_str}")

        return token_data

    async def _get_installation_for_repo(self, repo: str) -> int:
        """Get the installation ID for a repository."""
        app_jwt = self._create_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/repos/{repo}/installation",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            data = response.json()

        return data["id"]

    async def refresh_remote_token(self, repo_path: "Path", remote: str = "origin") -> None:
        """
        Update the remote URL with a fresh installation token.

        Call this before git push to avoid expired-token errors.
        """
        import re
        import git as gitpython

        r = gitpython.Repo(repo_path)
        origin_url = r.remotes[remote].url
        match = re.match(
            r"https://x-access-token:[^@]+@github\.com/(.+?)\.git", origin_url
        )
        if not match:
            return

        repo = match.group(1)
        fresh_token = await self.get_token_for_repo(repo)
        fresh_url = f"https://x-access-token:{
            fresh_token}@github.com/{repo}.git"
        r.remotes[remote].set_url(fresh_url)
        logger.debug(f"Refreshed remote URL token for {repo}")

    def _create_jwt(self) -> str:
        """Create a JWT for GitHub App authentication."""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # Issued 60 seconds ago (clock drift tolerance)
            "exp": now + 600,  # Expires in 10 minutes
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")
