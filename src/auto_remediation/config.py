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
    listen_host: str = "0.0.0.0"
    listen_port: int = 8000


settings = Settings()
