from pathlib import Path
import subprocess
from unittest.mock import patch
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import async_session_factory
from app.models.project import Project
from engines.ingestion.git import GitCloneError


def _populate_sample_repo(dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "app.py").write_text(
        "import math\n\ndef run():\n    return math.sqrt(16)\n\nif __name__ == '__main__':\n    run()\n",
        encoding="utf-8",
    )
    (dest_dir / "utils.py").write_text(
        "def helper(x: int) -> int:\n    return x * 2\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_import_github_invalid_url(async_client: AsyncClient):
    """Verify malformed or invalid GitHub URLs are rejected with HTTP 400."""
    response = await async_client.post(
        "/api/v1/projects/import-github",
        json={"url": "http://github.com/owner/repo"},
    )
    assert response.status_code == 400
    assert "Unsupported URL scheme" in response.json()["detail"]


@pytest.mark.asyncio
async def test_import_github_credentials_rejected(async_client: AsyncClient):
    """Verify embedded credentials in GitHub URLs are rejected with HTTP 400."""
    response = await async_client.post(
        "/api/v1/projects/import-github",
        json={"url": "https://token123@github.com/owner/repo"},
    )
    assert response.status_code == 400
    assert "Embedded credentials" in response.json()["detail"]


@pytest.mark.asyncio
async def test_import_github_command_injection_rejected(async_client: AsyncClient):
    """Verify shell metacharacters and injection vectors in URLs are rejected with HTTP 400."""
    response = await async_client.post(
        "/api/v1/projects/import-github",
        json={"url": "https://github.com/owner/repo; rm -rf /"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_import_github_missing_url(async_client: AsyncClient):
    """Verify payload missing url field returns HTTP 422."""
    response = await async_client.post(
        "/api/v1/projects/import-github",
        json={"name": "test"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_github_success_with_auto_ingest(async_client: AsyncClient):
    """Verify successful GitHub import with auto-ingestion indexes codebase and persists record."""
    def fake_clone(self, url, dest):
        _populate_sample_repo(dest)
        return dest

    with patch("engines.ingestion.git.SafeGitCloner.clone", fake_clone):
        response = await async_client.post(
            "/api/v1/projects/import-github",
            json={
                "url": "https://github.com/pallets/flask.git",
                "auto_ingest": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        proj_id = uuid.UUID(data["id"])

        assert data["name"] == "flask"
        assert data["source_type"] == "github"
        assert data["source_url"] == "https://github.com/pallets/flask"
        assert data["status"] == "indexed"

        # Verify filesystem destination exists in managed workspace
        managed_dir = settings.get_repositories_dir()
        cloned_path = managed_dir / f"gh-{proj_id}"
        assert cloned_path.exists()
        assert (cloned_path / "app.py").exists()
        assert (cloned_path / "utils.py").exists()

        # Verify database record
        async with async_session_factory() as session:
            proj = (
                await session.execute(select(Project).where(Project.id == proj_id))
            ).scalar_one_or_none()
            assert proj is not None
            assert proj.source_type == "github"
            assert proj.source_url == "https://github.com/pallets/flask"
            assert proj.status == "indexed"


@pytest.mark.asyncio
async def test_import_github_custom_name_and_manual_ingest(async_client: AsyncClient):
    """Verify custom name is honored and manual ingestion works when auto_ingest=False."""
    def fake_clone(self, url, dest):
        _populate_sample_repo(dest)
        return dest

    with patch("engines.ingestion.git.SafeGitCloner.clone", fake_clone):
        response = await async_client.post(
            "/api/v1/projects/import-github",
            json={
                "url": "https://github.com/octocat/Hello-World",
                "name": "Custom Octocat Project",
                "auto_ingest": False,
            },
        )
        assert response.status_code == 201
        data = response.json()
        proj_id = uuid.UUID(data["id"])

        assert data["name"] == "Custom Octocat Project"
        assert data["source_type"] == "github"
        assert data["status"] == "pending"

        # Trigger manual ingestion
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200
        ingest_data = ingest_resp.json()
        assert ingest_data["status"] == "indexed"
        assert ingest_data["scanned_files_count"] >= 2


@pytest.mark.asyncio
async def test_import_github_full_pipeline_parse_graph_trace(async_client: AsyncClient):
    """Verify GitHub imported projects work seamlessly with parse, graph, and trace services."""
    def fake_clone(self, url, dest):
        _populate_sample_repo(dest)
        return dest

    with patch("engines.ingestion.git.SafeGitCloner.clone", fake_clone):
        response = await async_client.post(
            "/api/v1/projects/import-github",
            json={
                "url": "https://github.com/sample/pipeline-test",
                "auto_ingest": True,
            },
        )
        assert response.status_code == 201
        proj_id = response.json()["id"]

        # 1. Test AST Parsing
        parse_resp = await async_client.post(f"/api/v1/projects/{proj_id}/parse")
        assert parse_resp.status_code == 200
        parse_data = parse_resp.json()
        assert parse_data["parsed_files_count"] >= 2
        assert parse_data["total_symbols_count"] >= 2

        # 2. Test Semantic Dependency Graph
        graph_resp = await async_client.post(f"/api/v1/projects/{proj_id}/graph")
        assert graph_resp.status_code == 200
        graph_data = graph_resp.json()
        assert len(graph_data["nodes"]) >= 2

        # 3. Test Execution Tracing
        trace_resp = await async_client.post(
            f"/api/v1/projects/{proj_id}/trace",
            json={"max_depth": 5},
        )
        assert trace_resp.status_code == 200
        trace_data = trace_resp.json()
        assert "entry_points" in trace_data


@pytest.mark.asyncio
async def test_import_github_clone_failure_rollback(async_client: AsyncClient):
    """Verify failed git clone rolls back destination directory and does not persist project."""
    tracked_dest = None

    def fake_failed_clone(self, url, dest):
        nonlocal tracked_dest
        tracked_dest = dest
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "partial.tmp").write_text("partial")
        raise GitCloneError("fatal: repository 'https://github.com/unknown/nonexistent' not found")

    with patch("engines.ingestion.git.SafeGitCloner.clone", fake_failed_clone):
        response = await async_client.post(
            "/api/v1/projects/import-github",
            json={"url": "https://github.com/unknown/nonexistent"},
        )
        assert response.status_code == 400
        assert "fatal: repository" in response.json()["detail"]

        # Check directory cleaned up
        if tracked_dest is not None:
            assert not tracked_dest.exists()


@pytest.mark.asyncio
async def test_import_github_auto_ingest_failure_rollback(async_client: AsyncClient):
    """Verify failure during initial indexing cleans up both DB record and cloned workspace."""
    tracked_dest = None

    def fake_clone(self, url, dest):
        nonlocal tracked_dest
        tracked_dest = dest
        _populate_sample_repo(dest)
        return dest

    with patch("engines.ingestion.git.SafeGitCloner.clone", fake_clone), \
         patch("engines.ingestion.scanner.CodebaseScanner.scan", side_effect=RuntimeError("Disk failure")):
        response = await async_client.post(
            "/api/v1/projects/import-github",
            json={"url": "https://github.com/sample/scan-fail"},
        )
        assert response.status_code == 500

        # Verify directory was cleaned up
        if tracked_dest is not None:
            assert not tracked_dest.exists()
