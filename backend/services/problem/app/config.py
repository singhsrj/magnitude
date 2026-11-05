from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Shared secret with the rating service. Required: the service refuses to start without it.
    internal_api_key: str
    log_level: str = "INFO"
