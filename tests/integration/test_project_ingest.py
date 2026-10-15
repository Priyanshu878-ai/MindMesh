import asyncio
from pathlib import Path
import time
import uuid
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.project import Project
from engines.ingestion.models import IngestionConfig
from engines.ingestion.scanner import CodebaseScanner


@pytest.mark.asyncio
async def test_ingest_project_success(async_client, tmp_path: Path):
    """Verify POST /api/v1/projects/{project_id}/ingest successfully ingests a local repository."""
    # Set up sample repository in tmp_path
    (tmp_path / "main.py").write_text("print('hello')\n\nprint('world')\n", encoding="utf-8")
    (tmp_path / "utils.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"key": "value"}\n', encoding="utf-8")

    # Add ignored file
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignore me", encoding="utf-8")

    # Add binary file
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    # Register tmp_path as trusted root in settings
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    # Create project
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Local Ingest Test {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # Trigger ingestion
        ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert ingest_resp.status_code == 200
        data = ingest_resp.json()

        assert data["project_id"] == proj_id
        assert data["status"] == "indexed"
        assert data["is_truncated"] is False
        assert data["duration_ms"] >= 0.0

        cataloged_paths = [f["path"] for f in data["files"]]
        assert "main.py" in cataloged_paths
        assert "utils.ts" in cataloged_paths
        assert "data.json" in cataloged_paths
        assert ".gitignore" in cataloged_paths
        assert "ignored.txt" not in cataloged_paths
        assert "logo.png" not in cataloged_paths

        # Verify file contents are NOT in the response
        for f in data["files"]:
            assert "content" not in f
            assert "raw_content" not in f

        # Verify languages breakdown
        assert data["languages"].get("Python") == 1
        assert data["languages"].get("TypeScript") == 1
        assert data["languages"].get("JSON") == 1

        # Check DB state
        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
            db_proj = (await session.execute(stmt)).scalar_one()
            assert db_proj.status == "indexed"
            assert db_proj.updated_at >= db_proj.created_at

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_missing_project(async_client):
    """Verify ingest on non-existent project returns 404."""
    random_id = str(uuid.uuid4())
    resp = await async_client.post(f"/api/v1/projects/{random_id}/ingest")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Project not found"


@pytest.mark.asyncio
async def test_ingest_unsupported_source_type(async_client):
    """Verify ingest on non-local project returns 400 and preserves pending status."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Remote Project {uuid.uuid4().hex[:6]}",
            "source_type": "github",
            "source_url": "https://github.com/example/repo",
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 400
        assert "Only 'local' source_type is supported" in resp.json()["detail"]

        # Status remains pending
        get_resp = await async_client.get(f"/api/v1/projects/{proj_id}")
        assert get_resp.json()["status"] == "pending"

    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_missing_or_invalid_source_url(async_client):
    """Verify ingest on project without source_url returns 400."""
    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"No URL Project {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": None,
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 400
        assert "does not have a configured local source directory" in resp.json()["detail"]

    finally:
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_path_outside_trusted_root(async_client, tmp_path: Path):
    """Verify ingest on directory outside allowed roots returns 400."""
    outside_dir = tmp_path / "outside_untrusted"
    outside_dir.mkdir()

    # Configure only another directory as trusted
    trusted_dir = tmp_path / "trusted_root"
    trusted_dir.mkdir()
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(trusted_dir.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Untrusted Path {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(outside_dir.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 400
        assert "outside the trusted local directory roots" in resp.json()["detail"]

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_concurrency_conflict(async_client, tmp_path: Path):
    """Verify ingest on project currently with 'ingesting' status returns 409."""
    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Concurrent Project {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Manually transition status to 'ingesting' in DB
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
        db_proj = (await session.execute(stmt)).scalar_one()
        db_proj.status = "ingesting"
        await session.commit()

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_truncation_sets_failed_status(async_client, tmp_path: Path):
    """Verify truncated scan marks project as failed and returns 422."""
    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Truncated Ingest {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        # Patch scanner default to have max_total_files=2
        with patch("app.services.ingestion.CodebaseScanner") as mock_scanner_cls:
            from engines.ingestion.scanner import CodebaseScanner as RealScanner

            mock_scanner_cls.side_effect = lambda config=None: RealScanner(
                config=IngestionConfig(max_total_files=2)
            )

            resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
            assert resp.status_code == 422
            assert "truncated" in resp.json()["detail"]

            # Confirm project status in DB transitioned to 'failed'
            async with async_session_factory() as session:
                stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
                db_proj = (await session.execute(stmt)).scalar_one()
                assert db_proj.status == "failed"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_concurrent_simultaneous_ingest_race(tmp_path: Path):
    """Verify simultaneous ingestion requests on the same project are race-free.

    One request claims the row and proceeds to completion (200), while the
    concurrent request receives 409 Conflict without duplicate scans occurring.
    """
    (tmp_path / "app.py").write_text("print('test')\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={
                "name": f"Concurrent Race Test {uuid.uuid4().hex[:6]}",
                "source_type": "local",
                "source_url": str(tmp_path.resolve()),
            },
        )
        assert create_resp.status_code == 201
        proj_id = create_resp.json()["id"]

        try:
            orig_scan = CodebaseScanner.scan

            def slow_scan(self, path):
                time.sleep(0.15)
                return orig_scan(self, path)

            with patch.object(CodebaseScanner, "scan", slow_scan):
                # Issue two simultaneous requests concurrently
                res1, res2 = await asyncio.gather(
                    client.post(f"/api/v1/projects/{proj_id}/ingest"),
                    client.post(f"/api/v1/projects/{proj_id}/ingest"),
                )

            statuses = {res1.status_code, res2.status_code}
            assert statuses == {200, 409}, (
                f"Expected one 200 and one 409, got {res1.status_code} and {res2.status_code}"
            )

            conflict_resp = res1 if res1.status_code == 409 else res2
            success_resp = res1 if res1.status_code == 200 else res2

            assert "already in progress" in conflict_resp.json()["detail"]
            assert success_resp.json()["status"] == "indexed"

            # Check DB state after both complete
            async with async_session_factory() as session:
                stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
                db_proj = (await session.execute(stmt)).scalar_one()
                assert db_proj.status == "indexed"

        finally:
            settings.allowed_repo_roots = orig_allowed
            await client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_concurrent_database_state_claim_atomicity():
    """Verify that atomic database-level update prevents two sessions from claiming the same project."""
    from datetime import datetime, timezone
    from sqlalchemy import update

    proj_id = uuid.uuid4()
    async with async_session_factory() as session:
        proj = Project(
            id=proj_id,
            name=f"Atomicity Test {proj_id.hex[:6]}",
            source_type="local",
            source_url="dummy",
            status="pending",
        )
        session.add(proj)
        await session.commit()

    try:
        async with async_session_factory() as session1, async_session_factory() as session2:
            claim_stmt = (
                update(Project)
                .where(Project.id == proj_id, Project.status != "ingesting")
                .values(status="ingesting", updated_at=datetime.now(timezone.utc))
                .returning(Project)
            )

            # Session 1 claims the row
            res1 = await session1.execute(claim_stmt)
            claimed1 = res1.scalar_one_or_none()
            await session1.commit()

            # Session 2 attempts to claim the row while status is now 'ingesting'
            res2 = await session2.execute(claim_stmt)
            claimed2 = res2.scalar_one_or_none()
            await session2.commit()

            assert claimed1 is not None
            assert claimed1.status == "ingesting"
            # Session 2 must observe 0 updated rows because status is 'ingesting'
            assert claimed2 is None

    finally:
        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == proj_id)
            p = (await session.execute(stmt)).scalar_one_or_none()
            if p:
                await session.delete(p)
                await session.commit()


@pytest.mark.asyncio
async def test_ingest_path_traversal_rejected(async_client, tmp_path: Path):
    """Verify relative traversal escaping trusted roots is rejected and status remains pending."""
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(trusted.resolve())]

    # Path attempting to traverse out of trusted
    traversal_path = str(trusted / ".." / "outside")

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Traversal Project {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": traversal_path,
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 400
        assert "outside the trusted local directory roots" in resp.json()["detail"]

        # Status must remain pending
        get_resp = await async_client.get(f"/api/v1/projects/{proj_id}")
        assert get_resp.json()["status"] == "pending"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_file_not_directory_rejected(async_client, tmp_path: Path):
    """Verify source_url pointing to a file instead of a directory is rejected with 400."""
    target_file = tmp_path / "file.txt"
    target_file.write_text("not a directory", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"File Not Dir {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(target_file.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 400
        assert "not a directory" in resp.json()["detail"]

        get_resp = await async_client.get(f"/api/v1/projects/{proj_id}")
        assert get_resp.json()["status"] == "pending"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_reingest_previously_failed_project(async_client, tmp_path: Path):
    """Verify a project in 'failed' status can be re-ingested successfully to 'indexed'."""
    (tmp_path / "fixed.py").write_text("x = 1\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Retry Project {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Manually transition status to 'failed'
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
        db_proj = (await session.execute(stmt)).scalar_one()
        db_proj.status = "failed"
        await session.commit()

    try:
        resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
        assert resp.status_code == 200
        assert resp.json()["status"] == "indexed"

        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
            db_proj = (await session.execute(stmt)).scalar_one()
            assert db_proj.status == "indexed"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")


@pytest.mark.asyncio
async def test_ingest_unhandled_failure_sets_failed_status(async_client, tmp_path: Path):
    """Verify unexpected scanner exceptions mark project status as failed and return 500."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")

    orig_allowed = settings.allowed_repo_roots
    settings.allowed_repo_roots = [str(tmp_path.resolve())]

    create_resp = await async_client.post(
        "/api/v1/projects",
        json={
            "name": f"Crash Project {uuid.uuid4().hex[:6]}",
            "source_type": "local",
            "source_url": str(tmp_path.resolve()),
        },
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    try:
        with patch.object(
            CodebaseScanner,
            "scan",
            side_effect=RuntimeError("Simulated scanner catastrophic crash"),
        ):
            resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
            assert resp.status_code == 500
            assert "Ingestion scan failed: Simulated scanner catastrophic crash" in resp.json()["detail"]

            async with async_session_factory() as session:
                stmt = select(Project).where(Project.id == uuid.UUID(proj_id))
                db_proj = (await session.execute(stmt)).scalar_one()
                assert db_proj.status == "failed"

    finally:
        settings.allowed_repo_roots = orig_allowed
        await async_client.delete(f"/api/v1/projects/{proj_id}")
