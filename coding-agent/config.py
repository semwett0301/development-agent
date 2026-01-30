"""
Configuration settings for the Coding Agent.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "anthropic"
    model: str = "claude-opus-4-5-20251101"
    api_key: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.1

    def __post_init__(self):
        if self.api_key is None:
            if self.provider == "anthropic":
                self.api_key = os.getenv("ANTHROPIC_API_KEY")
            else:
                raise ValueError(f"Unknown LLM provider: {self.provider}")


@dataclass
class GitHubConfig:
    """GitHub API configuration."""
    token: Optional[str] = None
    api_url: str = "https://api.github.com"

    def __post_init__(self):
        if self.token is None:
            self.token = os.getenv("GITHUB_TOKEN")


@dataclass
class ChromaConfig:
    """Chroma vector database configuration."""
    host: str = "localhost"
    port: int = 8000
    collection_name: str = "codebase"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class AgentConfig:
    """Main agent configuration."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    chroma: ChromaConfig = field(default_factory=ChromaConfig)

    # Agent behavior settings
    max_fix_attempts: int = 3
    work_dir: str = "/tmp/coding_agent_workspaces"

    # Config files to search for lint/test commands
    config_files: list[str] = field(default_factory=lambda: [
        "README.md",
        "package.json",
        "pyproject.toml",
        "Makefile",
        ".pre-commit-config.yaml",
        "tox.ini",
        "setup.cfg",
        "setup.py",
    ])


def load_config() -> AgentConfig:
    """Load configuration from environment variables."""
    return AgentConfig(
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "anthropic"),
            model=os.getenv("LLM_MODEL", "claude-opus-4-5-20251101"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        ),
        github=GitHubConfig(),
        chroma=ChromaConfig(
            host=os.getenv("CHROMA_HOST", "localhost"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
        ),
        max_fix_attempts=int(os.getenv("MAX_FIX_ATTEMPTS", "3")),
        work_dir=os.getenv("WORK_DIR", "/tmp/coding_agent_workspaces"),
    )
