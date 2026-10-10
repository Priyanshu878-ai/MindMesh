from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.future import select

from app.db.base import Base
from app.models.project import Project


def test_project_tablename():
    """Verify projects table name and metadata binding."""
    assert Project.__tablename__ == "projects"
    assert "projects" in Base.metadata.tables


def test_project_columns_metadata():
    """Verify column types, nullability, and constraints in table metadata."""
    table = Base.metadata.tables["projects"]

    # Primary key
    assert "id" in table.columns
    assert isinstance(table.columns["id"].type, Uuid)
    assert table.columns["id"].primary_key is True
    assert table.columns["id"].nullable is False

    # Name
    assert "name" in table.columns
    assert isinstance(table.columns["name"].type, String)
    assert table.columns["name"].type.length == 255
    assert table.columns["name"].nullable is False

    # Source type
    assert "source_type" in table.columns
    assert isinstance(table.columns["source_type"].type, String)
    assert table.columns["source_type"].type.length == 50
    assert table.columns["source_type"].nullable is False

    # Source URL
    assert "source_url" in table.columns
    assert isinstance(table.columns["source_url"].type, String)
    assert table.columns["source_url"].type.length == 1024
    assert table.columns["source_url"].nullable is True

    # Status
    assert "status" in table.columns
    assert isinstance(table.columns["status"].type, String)
    assert table.columns["status"].type.length == 50
    assert table.columns["status"].nullable is False
    assert table.columns["status"].server_default.arg == "pending"

    # Timestamps
    assert "created_at" in table.columns
    assert isinstance(table.columns["created_at"].type, DateTime)
    assert table.columns["created_at"].type.timezone is True
    assert table.columns["created_at"].nullable is False

    assert "updated_at" in table.columns
    assert isinstance(table.columns["updated_at"].type, DateTime)
    assert table.columns["updated_at"].type.timezone is True
    assert table.columns["updated_at"].nullable is False


def test_project_instance_defaults():
    """Verify default values when instantiating a Project model instance."""
    project = Project(
        name="MindMesh Core",
        source_type="github",
    )

    assert isinstance(project.id, uuid.UUID)
    assert project.name == "MindMesh Core"
    assert project.source_type == "github"
    assert project.source_url is None
    assert project.status == "pending"
    assert isinstance(project.created_at, datetime)
    assert isinstance(project.updated_at, datetime)


def test_project_custom_attributes():
    """Verify custom attributes assignment on Project model instance."""
    custom_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    project = Project(
        id=custom_id,
        name="Custom Service",
        source_type="gitlab",
        source_url="https://gitlab.com/example/repo",
        status="active",
        created_at=now,
        updated_at=now,
    )

    assert project.id == custom_id
    assert project.name == "Custom Service"
    assert project.source_type == "gitlab"
    assert project.source_url == "https://gitlab.com/example/repo"
    assert project.status == "active"
    assert project.created_at == now
    assert project.updated_at == now


def test_project_repr():
    """Verify string representation of Project model."""
    project_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    project = Project(
        id=project_id,
        name="Test Project",
        source_type="local",
        status="pending",
    )
    assert repr(project) == f"<Project(id={project_id}, name='Test Project', status='pending')>"


@pytest.mark.asyncio
async def test_project_async_database_lifecycle():
    """Verify Project ORM lifecycle (insert, query, update, delete) with async session."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        # Create
        async with session_factory() as session:
            new_project = Project(
                name="MindMesh Ingest",
                source_type="github",
                source_url="https://github.com/Priyanshu878-ai/MindMesh",
            )
            session.add(new_project)
            await session.commit()
            project_id = new_project.id

        # Query
        async with session_factory() as session:
            stmt = select(Project).where(Project.id == project_id)
            result = await session.execute(stmt)
            fetched = result.scalar_one_or_none()

            assert fetched is not None
            assert fetched.id == project_id
            assert fetched.name == "MindMesh Ingest"
            assert fetched.source_type == "github"
            assert fetched.source_url == "https://github.com/Priyanshu878-ai/MindMesh"
            assert fetched.status == "pending"

            # Update
            fetched.status = "indexed"
            await session.commit()

        # Verify update
        async with session_factory() as session:
            stmt = select(Project).where(Project.id == project_id)
            result = await session.execute(stmt)
            updated = result.scalar_one()
            assert updated.status == "indexed"

    finally:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()
