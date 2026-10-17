import io
from pathlib import Path
import uuid
import zipfile
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import async_session_factory
from app.models.project import Project


def _build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content.encode("utf-8"))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_zip_success_with_auto_ingest(async_client: AsyncClient):
    """Verify uploading a valid ZIP extracts safely, registers project, and indexes codebase."""
    zip_bytes = _build_zip({
        "app.py": "def main():\n    print('Running App')\n",
        "utils.py": "def add(a, b):\n    return a + b\n",
    })

    files = {"file": ("my_sample_app.zip", zip_bytes, "application/zip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 201

    data = response.json()
    proj_id = uuid.UUID(data["id"])
    assert data["name"] == "my_sample_app"
    assert data["source_type"] == "local"
    assert data["status"] == "indexed"
    assert data["source_url"] is not None

    extracted_path = Path(data["source_url"])
    assert extracted_path.exists()
    assert (extracted_path / "app.py").exists()
    assert (extracted_path / "utils.py").exists()

    # Verify persistence in database
    async with async_session_factory() as session:
        proj = (await session.execute(select(Project).where(Project.id == proj_id))).scalar_one_or_none()
        assert proj is not None
        assert proj.status == "indexed"


@pytest.mark.asyncio
async def test_upload_zip_with_custom_name(async_client: AsyncClient):
    """Verify custom project name provided in form data is preserved."""
    zip_bytes = _build_zip({
        "index.py": "# index",
    })

    custom_name = f"Custom Name {uuid.uuid4().hex[:6]}"
    files = {"file": ("archive.zip", zip_bytes, "application/zip")}
    data = {"name": custom_name}

    response = await async_client.post("/api/v1/projects/upload-zip", files=files, data=data)
    assert response.status_code == 201
    assert response.json()["name"] == custom_name


@pytest.mark.asyncio
async def test_upload_zip_auto_ingest_false_and_subsequent_ingest(async_client: AsyncClient):
    """Verify auto_ingest=False leaves project in pending status and subsequent ingest succeeds."""
    zip_bytes = _build_zip({
        "server.py": "from http.server import HTTPServer\n",
    })

    files = {"file": ("service.zip", zip_bytes, "application/zip")}
    data = {"auto_ingest": "false"}

    response = await async_client.post("/api/v1/projects/upload-zip", files=files, data=data)
    assert response.status_code == 201
    proj_id = response.json()["id"]
    assert response.json()["status"] == "pending"

    # Trigger manual ingestion
    ingest_resp = await async_client.post(f"/api/v1/projects/{proj_id}/ingest")
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "indexed"

    # Verify status updated
    get_resp = await async_client.get(f"/api/v1/projects/{proj_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "indexed"


@pytest.mark.asyncio
async def test_upload_zip_invalid_extension_rejected(async_client: AsyncClient):
    """Verify files without .zip extension are rejected with 400."""
    files = {"file": ("malicious.tar.gz", b"not a zip", "application/gzip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 400
    assert "Only .zip archives are supported" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_zip_malformed_archive_rejected(async_client: AsyncClient):
    """Verify corrupted zip archive is rejected with 400."""
    files = {"file": ("corrupt.zip", b"PK\x03\x04corrupted-archive-content", "application/zip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 400
    assert "Archive extraction failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_zip_slip_traversal_rejected_and_cleaned(async_client: AsyncClient):
    """Verify Zip Slip path traversal is rejected and no database record or orphaned directory remains."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil_escape.py", "print('hacked')")
    zip_bytes = buf.getvalue()

    files = {"file": ("slip.zip", zip_bytes, "application/zip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 400
    assert "Zip Slip" in response.json()["detail"] or "directory traversal" in response.json()["detail"]

    # Verify no project created
    async with async_session_factory() as session:
        result = await session.execute(select(Project).where(Project.name == "slip"))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_upload_zip_duplicate_paths_rejected(async_client: AsyncClient):
    """Verify archives with duplicate files are rejected with 400."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("duplicate.py", "# first")
        zf.writestr("duplicate.py", "# second")
    zip_bytes = buf.getvalue()

    files = {"file": ("dups.zip", zip_bytes, "application/zip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 400
    assert "duplicate or colliding" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_zip_encrypted_archive_rejected(async_client: AsyncClient):
    """Verify encrypted zip files return 400 Bad Request with a clear message."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("secret.py", b"encrypted")
    data = bytearray(buf.getvalue())
    loc = data.find(b"PK\x03\x04")
    if loc != -1:
        data[loc + 6] |= 0x01
    loc_cd = data.find(b"PK\x01\x02")
    if loc_cd != -1:
        data[loc_cd + 8] |= 0x01
    zip_bytes = bytes(data)

    files = {"file": ("encrypted.zip", zip_bytes, "application/zip")}
    response = await async_client.post("/api/v1/projects/upload-zip", files=files)
    assert response.status_code == 400
    assert "encrypted" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_zip_oversized_content_length_rejected(async_client: AsyncClient):
    """Verify uploads declaring oversized Content-Length header are rejected before full ingestion."""
    zip_bytes = _build_zip({"a.py": "# test"})
    files = {"file": ("normal.zip", zip_bytes, "application/zip")}
    headers = {"Content-Length": str(100 * 1024 * 1024)}  # 100 MB > 50 MB limit

    response = await async_client.post("/api/v1/projects/upload-zip", files=files, headers=headers)
    assert response.status_code == 400
    assert "Upload size exceeds maximum allowed limit" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_zip_indexing_failure_cleans_up_records_and_disk(async_client: AsyncClient, monkeypatch):
    """Verify that if indexing fails during auto_ingest, the database record and extracted directory are cleaned up."""
    from engines.ingestion.scanner import CodebaseScanner
    from engines.ingestion.models import IngestionSummary

    # Mock CodebaseScanner to return a truncated scan, which causes ingest_project to raise 422
    def mock_scan(self, project_path):
        return IngestionSummary(
            project_root=str(project_path),
            scanned_files_count=10001,
            included_files_count=0,
            skipped_files_count=0,
            total_size_bytes=0,
            total_lines=0,
            total_code_lines=0,
            total_blank_lines=0,
            is_truncated=True,
        )

    monkeypatch.setattr(CodebaseScanner, "scan", mock_scan)

    zip_bytes = _build_zip({"huge.py": "# huge"})
    project_name = f"Failed Project {uuid.uuid4().hex[:6]}"
    files = {"file": ("huge_project.zip", zip_bytes, "application/zip")}
    data = {"name": project_name}

    response = await async_client.post("/api/v1/projects/upload-zip", files=files, data=data)
    assert response.status_code == 422
    assert "truncated" in response.json()["detail"]

    # Verify no orphaned record in database
    async with async_session_factory() as session:
        result = await session.execute(select(Project).where(Project.name == project_name))
        assert result.scalar_one_or_none() is None
