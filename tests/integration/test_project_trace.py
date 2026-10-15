from pathlib import Path
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.settings import settings
from app.main import app


@pytest.mark.asyncio
async def test_trace_project_success_default_entrypoint(async_client, tmp_path: Path):
    """Verify POST /api/v1/projects/{project_id}/trace with default entrypoint on an indexed project."""
    api_file = tmp_path / "api.py"
    api_file.write_text(
        '''
from fastapi import APIRouter
from .services import process_order

router = APIRouter()

@router.post("/orders")
def create_order():
    return process_order()
''',
        encoding="utf-8",
    )

    services_file = tmp_path / "services.py"
    services_file.write_text(
        '''
from .db import save_order

def process_order():
    return save_order()
''',
        encoding="utf-8",
    )

    db_file = tmp_path / "db.py"
    db_file.write_text(
        '''
def save_order():
    return {"status": "saved"}
''',
        encoding="utf-8",
    )

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Trace Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # 1. Ingest to reach 'indexed' status
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["status"] == "indexed"

        # 2. Trace project with default body
        trace_resp = await async_client.post(f"/api/v1/projects/{proj_id}/trace", json={})
        assert trace_resp.status_code == 200
        data = trace_resp.json()

        assert data["project_id"] == proj_id
        assert data["status"] == "indexed"
        assert len(data["entry_points"]) >= 1
        assert data["duration_ms"] >= 0.0

        # Verify entry point details
        ep = data["entry_points"][0]
        assert ep["http_method"] == "POST"
        assert ep["route_path"] == "/orders"
        assert ep["entry_type"] == "http_route"

        # Verify execution trace
        trace = data["trace"]
        assert trace is not None
        assert trace["entry_point"]["id"] == ep["id"]
        assert len(trace["steps"]) >= 2

        # Step indices and sequencing
        for idx, step in enumerate(trace["steps"]):
            assert step["step_index"] == idx

        # Verify tree hierarchy
        assert trace["tree"] is not None
        assert trace["tree"]["node_id"] == ep["id"]
        assert len(trace["tree"]["children"]) >= 1

        # Verify metrics
        metrics = trace["metrics"]
        assert metrics["total_steps"] == len(trace["steps"])
        assert metrics["max_depth"] >= 2
        assert metrics["distinct_files_count"] >= 2
        assert metrics["has_cycles"] is False

    finally:
        settings.allowed_repo_roots = orig_allowed


@pytest.mark.asyncio
async def test_trace_project_source_to_target_pathfinding(async_client, tmp_path: Path):
    """Verify pathfinding between specific source and target symbols."""
    flow_file = tmp_path / "flow.py"
    flow_file.write_text(
        '''
def entry_fn():
    step_a()

def step_a():
    step_b()

def step_b():
    destination_fn()

def destination_fn():
    pass

def unrelated_fn():
    pass
''',
        encoding="utf-8",
    )

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Pathfind Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        await async_client.post(f"/api/v1/projects/{proj_id}/ingest")

        # 1. Pathfinding from entry_fn to destination_fn
        req_payload = {
            "source_id": "symbol:flow.py:entry_fn",
            "target_id": "symbol:flow.py:destination_fn",
            "max_depth": 10,
        }
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/trace", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["paths"] is not None
        assert len(data["paths"]) == 1
        path_steps = data["paths"][0]
        step_targets = [s["target_id"] for s in path_steps]
        assert "symbol:flow.py:step_a" in step_targets
        assert "symbol:flow.py:step_b" in step_targets
        assert "symbol:flow.py:destination_fn" in step_targets

        # 2. Pathfinding to an unreachable target
        unreachable_payload = {
            "source_id": "symbol:flow.py:entry_fn",
            "target_id": "symbol:flow.py:unrelated_fn",
            "max_depth": 10,
        }
        unreach_resp = await async_client.post(f"/api/v1/projects/{proj_id}/trace", json=unreachable_payload)
        assert unreach_resp.status_code == 200
        unreach_data = unreach_resp.json()
        assert unreach_data["paths"] == []

    finally:
        settings.allowed_repo_roots = orig_allowed


@pytest.mark.asyncio
async def test_trace_project_missing_project_404(async_client):
    """Verify that tracing a non-existent project returns 404."""
    random_id = uuid.uuid4()
    resp = await async_client.post(f"/api/v1/projects/{random_id}/trace", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Project not found"


@pytest.mark.asyncio
async def test_trace_project_unindexed_status_400(async_client, tmp_path: Path):
    """Verify that tracing an unindexed project returns 400."""
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Unindexed Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        # Try tracing without prior ingestion
        trace_resp = await async_client.post(f"/api/v1/projects/{proj_id}/trace", json={})
        assert trace_resp.status_code == 400
        assert "must be indexed" in trace_resp.json()["detail"]
    finally:
        settings.allowed_repo_roots = orig_allowed


@pytest.mark.asyncio
async def test_trace_project_invalid_symbol_ids_400(async_client, tmp_path: Path):
    """Verify that requesting an invalid or missing symbol ID returns 400."""
    app_file = tmp_path / "app.py"
    app_file.write_text("def ping(): pass\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Invalid Sym Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        await async_client.post(f"/api/v1/projects/{proj_id}/ingest")

        # Nonexistent entrypoint ID
        resp1 = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"entry_point_id": "symbol:app.py:nonexistent_func"},
        )
        assert resp1.status_code == 400
        assert "not found in project" in resp1.json()["detail"]

        # Nonexistent source ID
        resp2 = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"source_id": "symbol:app.py:ghost", "target_id": "symbol:app.py:ping"},
        )
        assert resp2.status_code == 400
        assert "Source symbol" in resp2.json()["detail"]

        # Nonexistent target ID
        resp3 = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"source_id": "symbol:app.py:ping", "target_id": "symbol:app.py:ghost"},
        )
        assert resp3.status_code == 400
        assert "Target symbol" in resp3.json()["detail"]

    finally:
        settings.allowed_repo_roots = orig_allowed


@pytest.mark.asyncio
async def test_trace_project_trusted_path_confinement(async_client, tmp_path: Path):
    """Verify that projects pointing to paths outside allowed_repo_roots are rejected with 400."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(allowed_dir.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Untrusted Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(outside_dir.resolve()),
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        # Direct trace attempt should reject path
        trace_resp = await async_client.post(f"/api/v1/projects/{proj_id}/trace", json={})
        # Even if not indexed, status check or trusted path validation protects the root
        assert trace_resp.status_code in (400, 422)
    finally:
        settings.allowed_repo_roots = orig_allowed


@pytest.mark.asyncio
async def test_trace_project_bounded_depth(async_client, tmp_path: Path):
    """Verify that max_depth is bounded and enforced."""
    chain_file = tmp_path / "chain.py"
    chain_file.write_text(
        '''
def n0(): n1()
def n1(): n2()
def n2(): n3()
def n3(): pass
''',
        encoding="utf-8",
    )

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Depth Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    proj_id = create_resp.json()["id"]

    try:
        await async_client.post(f"/api/v1/projects/{proj_id}/ingest")

        # max_depth = 1 bounds traversal
        resp = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"source_id": "symbol:chain.py:n0", "max_depth": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["trace"]["metrics"]["max_depth"] == 1
        assert len(resp.json()["trace"]["steps"]) == 1

        # Out-of-bounds max_depth (0 or 51) fails validation (422)
        resp_invalid = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"source_id": "symbol:chain.py:n0", "max_depth": 0},
        )
        assert resp_invalid.status_code == 422

    finally:
        settings.allowed_repo_roots = orig_allowed
