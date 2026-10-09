from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://raglab:raglab@localhost:5432/raglab"
    cors_origins: list[str] = ["http://localhost:3000"]
    embedding_model_path: str = ""
    private_uploads_enabled: bool = True
