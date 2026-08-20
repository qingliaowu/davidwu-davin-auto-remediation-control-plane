"""Application configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Control plane settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    database_url: str = Field(
        default="sqlite+aiosqlite:///./auto_remediation.db",
        description="Async SQLAlchemy database URL.",
    )
    host: str = Field(default="127.0.0.1", description="Server bind host.")
    port: int = Field(default=8000, description="Server bind port.")
    log_level: str = Field(default="INFO", description="Python logging level.")

    # Devin API settings
    devin_api_base_url: str = Field(
        default="https://api.devin.ai",
        description="Base URL for the Devin API.",
    )
    devin_api_key: str | None = Field(
        default=None,
        description="API key for authenticating with Devin.",
    )
    devin_org_id: str | None = Field(
        default=None,
        description="Devin organization ID.",
    )
    devin_repo: str = Field(
        default="qingliaowu/superset",
        description="Repository Devin should operate on.",
    )
    devin_mode: str = Field(
        default="normal",
        description="Devin session mode.",
    )
    devin_max_acu_limit: int = Field(
        default=100,
        description="Maximum ACU limit for a Devin session.",
    )
    devin_dry_run: bool = Field(
        default=False,
        description="When true, do not call the real Devin API.",
    )

    # Worker settings
    poll_interval_seconds: float = Field(
        default=10.0,
        description="Seconds between worker polling cycles.",
    )
    max_concurrent_tasks_per_repository: int = Field(
        default=1,
        description="Maximum active tasks per repository at one time.",
    )


settings = Settings()
