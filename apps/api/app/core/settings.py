from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MindMesh API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Database configuration
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "mindmesh"
    postgres_user: str = "mindmesh"
    postgres_password: str = "mindmesh_secret"

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()