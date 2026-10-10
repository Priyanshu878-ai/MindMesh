from io import StringIO
import os
import tempfile

from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base


def test_alembic_config_and_script_directory():
    """Verify Alembic configuration loads properly and migration script is recognized."""
    ini_path = os.path.abspath("alembic.ini")
    assert os.path.exists(ini_path)

    config = Config(ini_path)
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())

    assert len(revisions) >= 1
    initial_rev = revisions[-1]
    assert initial_rev.revision == "0001_create_projects_table"
    assert initial_rev.down_revision is None


def test_apps_api_alembic_config():
    """Verify apps/api/alembic.ini resolves correctly."""
    api_ini = os.path.abspath(os.path.join("apps", "api", "alembic.ini"))
    assert os.path.exists(api_ini)

    config = Config(api_ini)
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())

    assert len(revisions) >= 1
    assert revisions[-1].revision == "0001_create_projects_table"


def test_alembic_offline_upgrade_sql_generation():
    """Verify Alembic offline upgrade produces correct SQL DDL for the projects table."""
    buf = StringIO()
    config = Config("alembic.ini", stdout=buf)
    command.upgrade(config, "head", sql=True)
    sql_output = buf.getvalue()

    assert "CREATE TABLE projects" in sql_output
    assert "id UUID NOT NULL" in sql_output
    assert "name VARCHAR(255) NOT NULL" in sql_output
    assert "source_type VARCHAR(50) NOT NULL" in sql_output
    assert "source_url VARCHAR(1024)" in sql_output
    assert "status VARCHAR(50)" in sql_output
    assert "created_at TIMESTAMP WITH TIME ZONE" in sql_output
    assert "updated_at TIMESTAMP WITH TIME ZONE" in sql_output
    assert "PRIMARY KEY (id)" in sql_output


def test_alembic_offline_downgrade_sql_generation():
    """Verify Alembic offline downgrade produces correct DROP TABLE statement."""
    buf = StringIO()
    config = Config("alembic.ini", stdout=buf)
    command.downgrade(config, "0001_create_projects_table:base", sql=True)
    sql_output = buf.getvalue()

    assert "DROP TABLE projects" in sql_output


@pytest.mark.asyncio
async def test_migration_execution_and_schema_validation():
    """Verify migration table creation and column structure using an async SQLite test engine."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name

    sqlite_url = f"sqlite+aiosqlite:///{db_path}"
    test_engine = create_async_engine(sqlite_url)

    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", sqlite_url)

        # Apply upgrade migration using async engine connection
        async with test_engine.begin() as conn:
            def do_upgrade(connection):
                migration_ctx = MigrationContext.configure(connection)
                script = ScriptDirectory.from_config(config)
                with Operations.context(migration_ctx):
                    for rev in script.iterate_revisions("head", "base"):
                        if rev.revision == "0001_create_projects_table":
                            rev.module.upgrade()

            await conn.run_sync(do_upgrade)

        # Inspect created table columns
        async with test_engine.connect() as conn:
            def get_cols(connection):
                insp = inspect(connection)
                return [c["name"] for c in insp.get_columns("projects")]

            columns = await conn.run_sync(get_cols)
            assert "id" in columns
            assert "name" in columns
            assert "source_type" in columns
            assert "source_url" in columns
            assert "status" in columns
            assert "created_at" in columns
            assert "updated_at" in columns

        # Test downgrade migration
        async with test_engine.begin() as conn:
            def do_downgrade(connection):
                migration_ctx = MigrationContext.configure(connection)
                script = ScriptDirectory.from_config(config)
                with Operations.context(migration_ctx):
                    for rev in script.iterate_revisions("head", "base"):
                        if rev.revision == "0001_create_projects_table":
                            rev.module.downgrade()

            await conn.run_sync(do_downgrade)

        # Verify table was dropped
        async with test_engine.connect() as conn:
            def get_tables(connection):
                insp = inspect(connection)
                return insp.get_table_names()

            tables = await conn.run_sync(get_tables)
            assert "projects" not in tables

    finally:
        await test_engine.dispose()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_base_metadata_contains_project_table():
    """Verify Declarative Base metadata contains registered Project table."""
    assert "projects" in Base.metadata.tables
    table = Base.metadata.tables["projects"]
    assert table.name == "projects"
