from pathlib import Path
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.project import Project


@pytest.mark.asyncio
async def test_parse_project_success(async_client, tmp_path: Path):
    """Verify POST /api/v1/projects/{project_id}/parse extracts symbols and imports from an indexed project."""
    # Create sample codebase
    (tmp_path / "math_utils.py").write_text(
        '''
import math
from typing import List

class Calculator:
    """A simple arithmetic utility."""

    def add(self, a: int, b: int = 0) -> int:
        """Add two numbers."""
        return a + b

def average(numbers: List[float]) -> float:
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)
''',
        encoding="utf-8",
    )

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Parse Test {uuid.uuid4().hex[:6]}",
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

        # Now trigger AST parse
        parse_resp = await async_client.post(f"/api/v1/projects/{proj_id}/parse")
        assert parse_resp.status_code == 200
        data = parse_resp.json()

        assert data["project_id"] == proj_id
        assert data["status"] == "indexed"
        assert data["parsed_files_count"] >= 1
        assert data["total_symbols_count"] >= 3  # Calculator, add, average
        assert data["total_imports_count"] >= 2  # math, typing
        assert data["error_files_count"] == 0

        # Verify file structure
        math_file = next(f for f in data["files"] if f["path"] == "math_utils.py")
        assert math_file["language"] == "Python"
        assert len(math_file["imports"]) == 2

        # Verify class and method hierarchy
        symbols = math_file["symbols"]
        calc_sym = next(s for s in symbols if s["name"] == "Calculator")
        assert calc_sym["kind"] == "class"
        assert calc_sym["docstring"] == "A simple arithmetic utility."
        assert len(calc_sym["children"]) == 1

        method = calc_sym["children"][0]
        assert method["name"] == "add"
        assert method["kind"] == "method"
        assert len(method["parameters"]) == 3  # self, a, b
        param_names = [p["name"] for p in method["parameters"]]
        assert param_names == ["self", "a", "b"]

        avg_sym = next(s for s in symbols if s["name"] == "average")
        assert avg_sym["kind"] == "function"
        assert avg_sym["return_type"] == "float"
        assert avg_sym["complexity"] >= 2  # base 1 + if branch

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_parse_project_requires_indexed_status(async_client, tmp_path: Path):
    """Verify parsing a project with status != 'indexed' returns 400 Bad Request."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Pending Parse Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # Status is 'pending' (not indexed yet)
        parse_resp = await async_client.post(f"/api/v1/projects/{proj_id}/parse")
        assert parse_resp.status_code == 400
        assert "must be indexed before parsing" in parse_resp.json()["detail"]

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_parse_missing_project(async_client):
    """Verify parsing a non-existent project returns 404 Not Found."""
    random_id = str(uuid.uuid4())
    resp = await async_client.post(f"/api/v1/projects/{random_id}/parse")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Project not found"


@pytest.mark.asyncio
async def test_parse_project_unsupported_source_type(async_client, tmp_path: Path):
    """Verify parsing a non-local project returns 400."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Remote Project {uuid.uuid4().hex[:6]}",
            "source_type": "gitlab",
            "source_url": "https://gitlab.com/example/repo",
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Manually transition status to 'indexed' in DB to test source_type check specifically
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
        db_proj = (await session.execute(stmt)).scalar_one()
        db_proj.status = "indexed"
        await session.commit()

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/parse")
        assert resp.status_code == 400
        assert "source types are supported" in resp.json()["detail"]

    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_parse_project_with_syntax_errors(async_client, tmp_path: Path):
    """Verify parsing continues across files even if one file has invalid syntax."""
    (tmp_path / "valid.py").write_text("def valid(): pass\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(x: return\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Syntax Error Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # Ingest first
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200

        # Parse AST
        parse_resp = await async_client.post(f"/api/v1/projects/{proj_id}/parse")
        assert parse_resp.status_code == 200
        data = parse_resp.json()

        assert data["parsed_files_count"] == 2
        assert data["error_files_count"] == 1
        assert data["total_symbols_count"] == 1  # only 'valid' extracted

        broken_file = next(f for f in data["files"] if f["path"] == "broken.py")
        assert len(broken_file["errors"]) == 1
        assert "SyntaxError" in broken_file["errors"][0]["error_message"]

        valid_file = next(f for f in data["files"] if f["path"] == "valid.py")
        assert len(valid_file["symbols"]) == 1
        assert valid_file["symbols"][0]["name"] == "valid"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")
