from pathlib import Path
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.project import Project


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_generate_project_graph_success(async_client, tmp_path: Path):
    """Verify POST /api/v1/projects/{project_id}/graph builds full dependency graph for indexed project."""
    # Create sample codebase with inheritance, imports, and containment
    models_file = tmp_path / "models.py"
    models_file.write_text(
        '''
class BaseEntity:
    pass

class User(BaseEntity):
    def get_id(self) -> int:
        return 1
''',
        encoding="utf-8",
    )

    service_file = tmp_path / "service.py"
    service_file.write_text(
        '''
import os
from .models import User

class UserService:
    def get_user(self) -> User:
        return User()
''',
        encoding="utf-8",
    )

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Graph Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # First ingest to reach 'indexed' status
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["status"] == "indexed"

        # Generate graph
        graph_resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert graph_resp.status_code == 200
        data = graph_resp.json()

        assert data["project_id"] == proj_id
        assert data["status"] == "indexed"
        assert len(data["nodes"]) > 0
        assert len(data["edges"]) > 0
        assert data["duration_ms"] >= 0.0

        # Verify node types present
        node_types = {n["node_type"] for n in data["nodes"]}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "external_package" in node_types

        # Verify edge types present
        edge_types = {e["edge_type"] for e in data["edges"]}
        assert "contains" in edge_types
        assert "imports" in edge_types
        assert "inherits_from" in edge_types

        # Verify metrics
        metrics = data["metrics"]
        assert metrics["total_nodes"] == len(data["nodes"])
        assert metrics["total_edges"] == len(data["edges"])
        assert "file" in metrics["node_counts_by_type"]
        assert "contains" in metrics["edge_counts_by_type"]
        assert isinstance(metrics["in_degrees"], dict)
        assert isinstance(metrics["out_degrees"], dict)

        # Acyclic codebase
        assert data["cycles"] == []

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_graph_requires_indexed_status(async_client, tmp_path: Path):
    """Verify generating dependency graph rejects project not in 'indexed' status with HTTP 400."""
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Pending Graph {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        graph_resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert graph_resp.status_code == 400
        assert "Project must be indexed before generating dependency graph" in graph_resp.json()["detail"]
    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_graph_missing_project(async_client):
    """Verify non-existent project returns HTTP 404."""
    non_existent = str(uuid.uuid4())
    resp = await async_client.post(f"/api/v1/projects/{non_existent}/graph")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Project not found"


@pytest.mark.asyncio
async def test_graph_wrong_source_type(async_client):
    """Verify generating dependency graph on non-local source_type returns HTTP 400."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Remote Graph {uuid.uuid4().hex[:6]}",
            "source_type": "github",
            "source_url": "https://github.com/example/repo",
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Transition status to 'indexed' in DB to test source_type guard
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
        db_proj = (await session.execute(stmt)).scalar_one()
        db_proj.status = "indexed"
        await session.commit()

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert resp.status_code == 400
        assert "Only 'local' source_type is supported" in resp.json()["detail"]
    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_graph_untrusted_source_path(async_client, tmp_path: Path):
    """Verify path outside allowed roots is rejected with HTTP 400."""
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = ["C:\\trusted\\root"]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Untrusted Graph {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Transition to 'indexed' in DB
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
        db_proj = (await session.execute(stmt)).scalar_one()
        db_proj.status = "indexed"
        await session.commit()

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert resp.status_code == 400
        assert "outside the trusted local directory roots" in resp.json()["detail"]
    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_graph_cycle_detection_integration(async_client, tmp_path: Path):
    """Verify dependency graph endpoint correctly detects circular imports."""
    mod_a = tmp_path / "mod_a.py"
    mod_a.write_text("import mod_b\n", encoding="utf-8")

    mod_b = tmp_path / "mod_b.py"
    mod_b.write_text("import mod_a\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Cycle Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200

        graph_resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert graph_resp.status_code == 200
        data = graph_resp.json()

        assert len(data["cycles"]) == 1
        cycle = data["cycles"][0]
        assert cycle == ["file:mod_a.py", "file:mod_b.py", "file:mod_a.py"]
    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")
