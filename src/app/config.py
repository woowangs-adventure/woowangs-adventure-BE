from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Woowangs Adventure Backend"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    edge_device_token: str = "change-this-device-token"
    map_source_robot_id: str = "TB3-01"
    control_enabled: bool = False
    control_command_ttl_ms: int = Field(default=300, ge=100, le=500)
    database_url: str = (
        "postgresql+asyncpg://robot_local_dev:robot_local_dev_password"
        "@127.0.0.1:5432/robot_inspection"
    )
    data_dir: Path = Path("data")
    max_map_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    frontend_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WOOWANGS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
