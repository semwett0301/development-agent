"""
Configuration settings for the Coding Agent.
"""
import os
from dataclasses import dataclass, field
from typing import Optional
import base64

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Kafka and app settings from environment."""
    kafka_bootstrap_servers: str = "localhost:9092"


settings = Settings()


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
class GitHubAppConfig:
    """GitHub App configuration."""
    app_id: Optional[str] = None
    private_key: Optional[str] = None
    api_url: str = "https://api.github.com"

    def __post_init__(self):
        if self.app_id is None:
            self.app_id = os.getenv("GITHUB_APP_ID")
        if self.private_key is None:
            raw = os.getenv("GITHUB_APP_PRIVATE_KEY")
            if raw:
                self.private_key = base64.b64decode(raw).decode()


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
class LangfuseConfig:
    """Langfuse observability configuration."""
    public_key: Optional[str] = None
    secret_key: Optional[str] = None
    host: str = "https://cloud.langfuse.com"

    def __post_init__(self):
        if self.public_key is None:
            self.public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        if self.secret_key is None:
            self.secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        if self.host == "https://cloud.langfuse.com":
            self.host = os.getenv("LANGFUSE_BASE_URL", self.host)

    @property
    def is_configured(self) -> bool:
        return bool(self.public_key and self.secret_key)


@dataclass
class AgentConfig:
    """Main agent configuration."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    github: GitHubAppConfig = field(default_factory=GitHubAppConfig)
    chroma: ChromaConfig = field(default_factory=ChromaConfig)
    langfuse: Optional[LangfuseConfig] = None

    max_fix_attempts: int = 3
    work_dir: str = "/tmp/coding_agent_workspaces"

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
    langfuse = LangfuseConfig(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
    )
    return AgentConfig(
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "anthropic"),
            model=os.getenv("LLM_MODEL", "claude-opus-4-5-20251101"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        ),
        github=GitHubAppConfig(),
        chroma=ChromaConfig(
            host=os.getenv("CHROMA_HOST", "localhost"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
        ),
        langfuse=langfuse if langfuse.is_configured else None,
        max_fix_attempts=int(os.getenv("MAX_FIX_ATTEMPTS", "3")),
        work_dir=os.getenv("WORK_DIR", "/tmp/coding_agent_workspaces"),
    )
