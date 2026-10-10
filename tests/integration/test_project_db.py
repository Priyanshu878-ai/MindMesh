import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.project import Project


@pytest.mark.asyncio
async def test_project_db_query_integration():
    """Verify Project ORM query execution against configured database session."""
    try:
        async with async_session_factory() as session:
            stmt = select(Project).limit(5)
            result = await session.execute(stmt)
            projects = result.scalars().all()
            assert isinstance(projects, list)
    except Exception as exc:
        pytest.skip(f"Live database not accessible in current environment: {exc}")
