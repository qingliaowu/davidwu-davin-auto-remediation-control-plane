"""Application configuration."""

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Control plane settings loaded from environment variables."""

    model_config = ConfigDict(env_file=".env", extra="ignore")

    github_webhook_secret: str = Field(
        default="",
        description="Secret used to validate GitHub webhook HMAC signatures.",
    )
    github_allowed_repository: str = Field(
        default="",
        description="Only process webhooks from this 'owner/repo' value.",
    )
    github_target_branch: str = Field(
        default="main",
        description="Target branch for generated remediation pull requests.",
    )
    dry_run: bool = Field(
        default=False,
        description="When true, tasks are created in dry-run mode.",
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./auto_remediation.db",
        description="Async SQLAlchemy database URL.",
    )
    host: str = Field(default="127.0.0.1", description="Server bind host.")
    port: int = Field(default=8000, description="Server bind port.")
    log_level: str = Field(default="INFO", description="Python logging level.")


settings = Settings()
