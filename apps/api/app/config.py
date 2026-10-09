from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://raglab:raglab@localhost:5432/raglab"
    cors_origins: list[str] = ["http://localhost:3000"]
    embedding_model_path: str = ""
    private_uploads_enabled: bool = True
    generation_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_models: list[str] = ["qwen2.5:1.5b"]
    generation_timeout_seconds: float = Field(default=90, ge=1, le=300)
    generation_max_tokens: int = Field(default=384, ge=64, le=1024)
    generation_context_chars: int = Field(default=10_000, ge=1000, le=16000)
