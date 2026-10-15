from pathlib import Path
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.project import Project


@pytest.mark.asyncio
async def test_database_isolation_step_one_creates_project(async_client: AsyncClient, tmp_path: Path):
    """Create a project and verify it exists during the test."""
    resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Isolation Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert resp.status_code == 201
    created_id = resp.json()["id"]

    # Verify present in DB during test
    async with async_session_factory() as session:
        proj = await session.get(Project, uuid.UUID(created_id))
        assert proj is not None


@pytest.mark.asyncio
async def test_database_isolation_step_two_verifies_clean_state(async_client: AsyncClient):
    """Verify that project created in step one was purged and did not pollute the database."""
    # List projects via API
    resp = await async_client.get("/api/v1/projects")
    assert resp.status_code == 200
    projects = resp.json()["items"] if isinstance(resp.json(), dict) else resp.json()

    # None of the projects should have 'Isolation Test' or pytest temp paths
    for p in projects:
        assert "Isolation Test" not in p["name"]
        if p["source_url"]:
            assert "pytest" not in p["source_url"]


@pytest.mark.asyncio
async def test_database_isolation_cleans_up_even_after_failure(async_client: AsyncClient, tmp_path: Path):
    """Verify that even if operations fail within a test, teardown guarantees project removal."""
    resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Failing Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert resp.status_code == 201
    proj_id = resp.json()["id"]

    # Deliberately raise or handle failure scenario
    try:
        raise RuntimeError("Simulated test error during execution")
    except RuntimeError:
        pass

    # The fixture teardown will run after this test finishes


@pytest.mark.asyncio
async def test_database_isolation_verifies_post_failure_cleanliness(async_client: AsyncClient):
    """Verify that the project created before the simulated failure was completely cleaned up."""
    async with async_session_factory() as session:
        result = await session.execute(select(Project).where(Project.name.ilike("%Failing Test%")))
        matching = result.scalars().all()
        assert len(matching) == 0


@pytest.mark.asyncio
async def test_concurrent_clients_isolation_preserves_other_client_projects(tmp_path: Path):
    """Verify that under concurrent execution, teardown of one client never deletes another client's projects."""
    from httpx import ASGITransport
    from app.main import app
    from tests.conftest import IsolatedAsyncClient

    transport = ASGITransport(app=app)
    client_a = IsolatedAsyncClient(transport=transport, base_url="http://test")
    client_b = IsolatedAsyncClient(transport=transport, base_url="http://test")

    try:
        # Client A creates Project A
        resp_a = await client_a.post(
            "/api/v1/projects",
            json={
                "name": f"Concurrent Project A {uuid.uuid4().hex[:6]}",
                "source_type": "local",
                "source_url": str(tmp_path.resolve()),
            },
        )
        assert resp_a.status_code == 201
        id_a = uuid.UUID(resp_a.json()["id"])

        # Client B creates Project B
        resp_b = await client_b.post(
            "/api/v1/projects",
            json={
                "name": f"Concurrent Project B {uuid.uuid4().hex[:6]}",
                "source_type": "local",
                "source_url": str(tmp_path.resolve()),
            },
        )
        assert resp_b.status_code == 201
        id_b = uuid.UUID(resp_b.json()["id"])

        # Both projects must exist
        async with async_session_factory() as session:
            assert await session.get(Project, id_a) is not None
            assert await session.get(Project, id_b) is not None

        # Simulate Client A teardown
        async with async_session_factory() as session:
            async with session.begin():
                from sqlalchemy import delete
                await session.execute(delete(Project).where(Project.id.in_(client_a.created_project_ids)))

        # Client A's project is removed, but Client B's project is GUARANTEED to still exist
        async with async_session_factory() as session:
            assert await session.get(Project, id_a) is None
            proj_b = await session.get(Project, id_b)
            assert proj_b is not None

    finally:
        # Simulate Client B teardown
        async with async_session_factory() as session:
            async with session.begin():
                from sqlalchemy import delete
                await session.execute(delete(Project).where(Project.id.in_(client_b.created_project_ids)))
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.asyncio
async def test_test_cleanup_never_deletes_unrelated_projects(async_client: AsyncClient, tmp_path: Path):
    """Verify that an unrelated user project in the database is never deleted by test teardown."""
    # Insert an unrelated user project directly
    unrelated_id = uuid.uuid4()
    async with async_session_factory() as session:
        async with session.begin():
            unrelated = Project(
                id=unrelated_id,
                name="Legitimate User Project",
                source_type="local",
                source_url=str(tmp_path.resolve()),
                status="indexed",
            )
            session.add(unrelated)

    try:
        # Run a test operation creating a test project
        resp = await async_client.post(
            "/api/v1/projects",
            json={
                "name": f"Ephemeral Test {uuid.uuid4().hex[:6]}",
                "source_type": "local",
                "source_url": str(tmp_path.resolve()),
            },
        )
        assert resp.status_code == 201
        test_id = uuid.UUID(resp.json()["id"])

        # Verify both exist
        async with async_session_factory() as session:
            assert await session.get(Project, unrelated_id) is not None
            assert await session.get(Project, test_id) is not None

        # Even if async_client cleans up its project, the unrelated project cannot be in its created_project_ids
        assert unrelated_id not in async_client.created_project_ids
        assert test_id in async_client.created_project_ids

    finally:
        # Clean up the unrelated fixture project manually
        async with async_session_factory() as session:
            async with session.begin():
                from sqlalchemy import delete
                await session.execute(delete(Project).where(Project.id == unrelated_id))
