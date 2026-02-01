"""
Configuration settings for the Reviewing Agent.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    """Application settings from environment."""
    kafka_bootstrap_servers: str = "localhost:9092"

    def __post_init__(self):
        self.kafka_bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", self.kafka_bootstrap_servers)


settings = Settings()


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "anthropic"
    model: str = "claude-opus-4-5-20251101"
    api_key: Optional[str] = None
    max_tokens: int = 16384
    temperature: float = 0.1

    def __post_init__(self):
        if self.api_key is None:
            if self.provider == "anthropic":
                self.api_key = os.getenv("ANTHROPIC_API_KEY")
            else:
                raise ValueError(f"Unknown LLM provider: {self.provider}")


@dataclass
class GitHubConfig:
    """GitHub configuration."""
    api_url: str = "https://api.github.com"
    token: Optional[str] = None

    def __post_init__(self):
        if self.token is None:
            self.token = os.getenv("GITHUB_TOKEN")


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
class ReviewAgentConfig:
    """Reviewing Agent configuration."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    langfuse: Optional[LangfuseConfig] = None

    # Review behavior
    summary_similarity_threshold: float = 0.45
    # When no check runs exist: True = do not block, False = require explicit green
    ci_required: bool = False

    # Webhook (optional)
    webhook_secret: Optional[str] = None


def load_config() -> ReviewAgentConfig:
    """Load configuration from environment variables."""
    langfuse = LangfuseConfig(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
    )
    return ReviewAgentConfig(
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "anthropic"),
            model=os.getenv("LLM_MODEL", "claude-opus-4-5-20251101"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        ),
        github=GitHubConfig(),
        langfuse=langfuse if langfuse.is_configured else None,
        summary_similarity_threshold=float(
            os.getenv("REVIEW_SUMMARY_SIMILARITY_THRESHOLD", "0.45")
        ),
        ci_required=os.getenv("REVIEW_CI_REQUIRED", "false").lower() == "true",
        webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET"),
    )
