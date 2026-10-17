from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_SETTINGS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SETTINGS_DIR.parents[2]


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

    # Local repository ingestion configuration
    local_projects_root: str = ""
    allowed_repo_roots: list[str] = []
    repositories_root: str = "data/repositories"

    # ZIP upload and extraction configuration
    max_zip_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_zip_extracted_size_bytes: int = 200 * 1024 * 1024  # 200 MB
    max_zip_file_count: int = 10_000
    max_zip_single_file_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_zip_compression_ratio: float = 100.0

    @property
    def project_root(self) -> Path:
        """The absolute canonical root directory of the MindMesh workspace."""
        return _PROJECT_ROOT

    def get_repositories_dir(self, create: bool = False) -> Path:
        """The absolute canonical path to the dedicated managed repository workspace."""
        raw = Path(self.repositories_root)
        resolved = raw.resolve() if raw.is_absolute() else (self.project_root / raw).resolve()
        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    @property
    def async_database_url(self) -> str:
        return f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()