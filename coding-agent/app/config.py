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
    """LLM provider configuration.

    Supported providers:
    - anthropic: Claude models (claude-opus-4-5-20251101, claude-sonnet-4-20250514, etc.)
    - openai: GPT models (gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.)
    - mistral: Mistral models (mistral-large-latest, mistral-medium, codestral-latest, etc.)
    - yandex: YandexGPT models (yandexgpt, yandexgpt-lite, etc.)
    """
    provider: str = "anthropic"
    model: str = "claude-opus-4-5-20251101"
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # For custom endpoints
    max_tokens: int = 4096
    temperature: float = 0.1

    # Yandex-specific
    folder_id: Optional[str] = None

    def __post_init__(self):
        # Auto-load API keys from environment
        if self.api_key is None:
            env_keys = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "mistral": "MISTRAL_API_KEY",
                "yandex": "YANDEX_API_KEY",
            }
            env_var = env_keys.get(self.provider)
            if env_var:
                self.api_key = os.getenv(env_var)

        # Yandex folder_id
        if self.provider == "yandex" and self.folder_id is None:
            self.folder_id = os.getenv("YANDEX_FOLDER_ID")


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
        langfuse=langfuse if langfuse.is_configured else None,
        max_fix_attempts=int(os.getenv("MAX_FIX_ATTEMPTS", "3")),
        work_dir=os.getenv("WORK_DIR", "/tmp/coding_agent_workspaces"),
    )
