from app.core.settings import Settings


def test_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.app_name == "MindMesh API"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "development"
    assert settings.debug is True
    assert settings.api_v1_prefix == "/api/v1"
    assert "http://localhost:3000" in settings.cors_origins
    assert settings.postgres_server == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "mindmesh"
    assert settings.postgres_user == "mindmesh"
    assert settings.postgres_password == "mindmesh_secret"
    assert settings.database_url == "postgresql://mindmesh:mindmesh_secret@localhost:5432/mindmesh"
    assert settings.async_database_url == "postgresql+psycopg://mindmesh:mindmesh_secret@localhost:5432/mindmesh"


def test_settings_custom_values():
    settings = Settings(
        app_name="MindMesh Test",
        app_version="1.0.0",
        environment="test",
        debug=False,
        api_v1_prefix="/api/custom",
        cors_origins=["http://example.com"],
        postgres_server="db.internal",
        postgres_port=5433,
        postgres_db="custom_db",
        postgres_user="custom_user",
        postgres_password="custom_password",
        _env_file=None,
    )
    assert settings.app_name == "MindMesh Test"
    assert settings.app_version == "1.0.0"
    assert settings.environment == "test"
    assert settings.debug is False
    assert settings.api_v1_prefix == "/api/custom"
    assert settings.cors_origins == ["http://example.com"]
    assert settings.postgres_server == "db.internal"
    assert settings.postgres_port == 5433
    assert settings.postgres_db == "custom_db"
    assert settings.postgres_user == "custom_user"
    assert settings.postgres_password == "custom_password"
    assert settings.database_url == "postgresql://custom_user:custom_password@db.internal:5433/custom_db"
    assert settings.async_database_url == "postgresql+psycopg://custom_user:custom_password@db.internal:5433/custom_db"
