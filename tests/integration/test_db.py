import pytest
from sqlalchemy import text

from app.db.session import async_session_factory, engine, get_db


@pytest.mark.asyncio
async def test_db_connectivity():
    """Verify async PostgreSQL connection and query execution with SQLAlchemy 2.0."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_async_session_factory():
    """Verify async session factory creates sessions that execute queries."""
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_get_db_dependency():
    """Verify get_db dependency yields a valid active session."""
    db_gen = get_db()
    session = await anext(db_gen)
    try:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        await db_gen.aclose()
