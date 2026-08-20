"""Application configuration."""

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Control plane settings loaded from environment."""

    model_config = ConfigDict(env_prefix="ARP_", env_file=".env")

    github_token: str = Field(default="", description="GitHub personal access token")
    github_app_id: str | None = Field(default=None, description="GitHub App ID")
    github_private_key: str | None = Field(default=None, description="GitHub App private key")
    webhook_secret: str | None = Field(default=None, description="GitHub webhook secret")
    devin_api_key: str | None = Field(default=None, description="Devin API key")
    devin_org_id: str | None = Field(default=None, description="Devin organization ID")
    devin_base_url: str = "https://api.devin.ai/v3"
    devin_create_as_user_id: str | None = Field(
        default=None, description="User ID to attribute Devin sessions to"
    )
    listen_host: str = "127.0.0.1"
    listen_port: int = 8000


settings = Settings()
