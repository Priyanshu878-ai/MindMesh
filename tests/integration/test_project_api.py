import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import async_session_factory
from app.main import app
from app.models.project import Project


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_create_project_success(async_client):
    """Verify POST /api/v1/projects creates a project and verifies database persistence."""
    payload = {
        "name": f"Test Project {uuid.uuid4().hex[:8]}",
        "source_type": "github",
        "source_url": "https://github.com/example/repo",
    }
    response = await async_client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert "id" in data
    proj_id = uuid.UUID(data["id"])
    assert data["name"] == payload["name"]
    assert data["source_type"] == "github"
    assert data["source_url"] == "https://github.com/example/repo"
    assert data["status"] == "pending"
    assert "created_at" in data
    assert "updated_at" in data

    # Verify directly in database via independent session
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == proj_id)
        db_proj = (await session.execute(stmt)).scalar_one_or_none()
        assert db_proj is not None
        assert db_proj.name == payload["name"]
        assert db_proj.source_type == "github"

    # Cleanup
    del_resp = await async_client.delete(f"/api/v1/projects/{data['id']}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_create_project_validation_errors(async_client):
    """Verify POST /api/v1/projects rejects invalid payloads with 422."""
    # Missing required source_type
    resp1 = await async_client.post("/api/v1/projects", json={"name": "No Source"})
    assert resp1.status_code == 422

    # Blank name
    resp2 = await async_client.post(
        "/api/v1/projects",
        json={"name": "   ", "source_type": "github"},
    )
    assert resp2.status_code == 422

    # Empty payload
    resp3 = await async_client.post("/api/v1/projects", json={})
    assert resp3.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_pagination(async_client):
    """Verify GET /api/v1/projects returns paginated results."""
    created_ids = []
    for i in range(2):
        resp = await async_client.post(
            "/api/v1/projects",
            json={
                "name": f"Pagination Project {i} {uuid.uuid4().hex[:6]}",
                "source_type": "local",
            },
        )
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    try:
        # Default pagination
        list_resp = await async_client.get("/api/v1/projects")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "items" in data
        assert "total" in data
        assert data["limit"] == 20
        assert data["offset"] == 0
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

        # Custom limit and offset
        paged_resp = await async_client.get("/api/v1/projects?limit=1&offset=0")
        assert paged_resp.status_code == 200
        paged_data = paged_resp.json()
        assert paged_data["limit"] == 1
        assert len(paged_data["items"]) == 1

        # Invalid pagination parameters
        assert (await async_client.get("/api/v1/projects?limit=0")).status_code == 422
        assert (await async_client.get("/api/v1/projects?limit=101")).status_code == 422
        assert (await async_client.get("/api/v1/projects?offset=-1")).status_code == 422
        assert (await async_client.get("/api/v1/projects?limit=notanumber")).status_code == 422

    finally:
        for pid in created_ids:
            await async_client.delete(f"/api/v1/projects/{pid}")


@pytest.mark.asyncio
async def test_get_project_by_id(async_client):
    """Verify GET /api/v1/projects/{project_id} returns 200, 404, or 422."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Fetch Test {uuid.uuid4().hex[:6]}",
            "source_type": "gitlab",
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        # Valid ID
        fetch_resp = await async_client.get(f"/api/v1/projects/{proj_id}")
        assert fetch_resp.status_code == 200
        assert fetch_resp.json()["id"] == proj_id
        assert fetch_resp.json()["source_type"] == "gitlab"

        # Non-existent UUID
        non_existent = str(uuid.uuid4())
        nf_resp = await async_client.get(f"/api/v1/projects/{non_existent}")
        assert nf_resp.status_code == 404
        assert nf_resp.json()["detail"] == "Project not found"

        # Invalid UUID format
        inv_resp = await async_client.get("/api/v1/projects/not-a-valid-uuid")
        assert inv_resp.status_code == 422

    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_patch_project(async_client):
    """Verify PATCH /api/v1/projects/{project_id} updates fields, handles edge cases, and refreshes updated_at."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Initial Name {uuid.uuid4().hex[:6]}",
            "source_type": "github",
            "source_url": "https://github.com/orig/repo",
        },
    )
    proj = create_resp.json()
    proj_id = proj["id"]

    try:
        # Empty patch payload is valid no-op
        empty_patch = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={},
        )
        assert empty_patch.status_code == 200
        assert empty_patch.json()["name"] == proj["name"]

        # Partial update: name and status
        patch_payload = {
            "name": "Updated Name",
            "status": "ready",
        }
        patch_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json=patch_payload,
        )
        assert patch_resp.status_code == 200
        updated = patch_resp.json()
        assert updated["name"] == "Updated Name"
        assert updated["status"] == "ready"
        assert updated["source_type"] == "github"  # Preserved
        assert updated["source_url"] == "https://github.com/orig/repo"  # Preserved
        assert updated["updated_at"] >= proj["updated_at"]

        # Clear source_url with explicit null
        clear_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"source_url": None},
        )
        assert clear_resp.status_code == 200
        assert clear_resp.json()["source_url"] is None

        # Rejection of null name
        null_name_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"name": None},
        )
        assert null_name_resp.status_code == 422

        # Rejection of null source_type
        null_source_type_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"source_type": None},
        )
        assert null_source_type_resp.status_code == 422

        # Rejection of null status
        null_status_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"status": None},
        )
        assert null_status_resp.status_code == 422

        # Rejection of blank name
        blank_name_resp = await async_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"name": "   "},
        )
        assert blank_name_resp.status_code == 422

        # Non-existent UUID
        random_id = str(uuid.uuid4())
        nf_resp = await async_client.patch(
            f"/api/v1/projects/{random_id}",
            json={"name": "Any"},
        )
        assert nf_resp.status_code == 404

        # Invalid UUID
        inv_resp = await async_client.patch(
            "/api/v1/projects/bad-id",
            json={"name": "Any"},
        )
        assert inv_resp.status_code == 422

    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_delete_project(async_client):
    """Verify DELETE /api/v1/projects/{project_id} deletes project with 204 and verifies database state."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"To Delete {uuid.uuid4().hex[:6]}",
            "source_type": "local",
        },
    )
    proj_id_str = create_resp.json()["id"]
    proj_id = uuid.UUID(proj_id_str)

    # Delete project
    del_resp = await async_client.delete(f"/api/v1/projects/{proj_id_str}")
    assert del_resp.status_code == 204

    # Confirm deletion via API
    get_resp = await async_client.get(f"/api/v1/projects/{proj_id_str}")
    assert get_resp.status_code == 404

    # Confirm deletion directly in database
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == proj_id)
        db_proj = (await session.execute(stmt)).scalar_one_or_none()
        assert db_proj is None

    # Delete again returns 404
    del_again = await async_client.delete(f"/api/v1/projects/{proj_id_str}")
    assert del_again.status_code == 404

    # Invalid UUID returns 422
    del_inv = await async_client.delete("/api/v1/projects/invalid-uuid")
    assert del_inv.status_code == 422
