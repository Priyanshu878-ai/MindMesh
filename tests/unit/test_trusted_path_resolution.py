import os
from pathlib import Path
import pytest
from fastapi import HTTPException

from app.core.settings import Settings
from app.services.ingestion import IngestionService


def test_missing_or_empty_source_url():
    service = IngestionService(session=None)
    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path(None)
    assert exc_info.value.status_code == 400
    assert "configured local source directory" in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path("   ")
    assert exc_info.value.status_code == 400


def test_valid_managed_workspace_relative_path(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    sample_repo = repos_dir / "my_project"
    sample_repo.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    # Relative path by name inside managed workspace
    resolved = service.resolve_trusted_path("my_project")
    assert resolved == sample_repo.resolve()


def test_valid_managed_workspace_absolute_path(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    sample_repo = repos_dir / "my_project"
    sample_repo.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    resolved = service.resolve_trusted_path(str(sample_repo))
    assert resolved == sample_repo.resolve()


def test_outside_root_rejection(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    outside_dir = tmp_path / "outside_project"
    outside_dir.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path(str(outside_dir))
    assert exc_info.value.status_code == 400
    assert "outside the trusted local directory roots" in exc_info.value.detail


def test_path_traversal_rejection(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    outside_target = tmp_path / "outside_target"
    outside_target.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    # Attempt directory traversal to escape the workspace
    traversal_path = f"../{outside_target.name}"
    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path(traversal_path)
    assert exc_info.value.status_code == 400
    assert "outside the trusted local directory roots" in exc_info.value.detail


def test_symlink_escape_rejection(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir()

    symlink_path = repos_dir / "symlink_repo"
    try:
        symlink_path.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted on this environment/platform.")

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    # Symlink points outside trusted roots; resolve() must detect escape
    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path("symlink_repo")
    assert exc_info.value.status_code == 400
    assert "outside the trusted local directory roots" in exc_info.value.detail


def test_configuration_override_allowed_roots(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    custom_root = tmp_path / "custom_root"
    custom_root.mkdir()
    custom_proj = custom_root / "proj_a"
    custom_proj.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    # Explicit allowed_roots override supplied to service instance
    service = IngestionService(
        session=None,
        settings=settings,
        allowed_roots=[custom_root],
    )

    resolved = service.resolve_trusted_path(str(custom_proj))
    assert resolved == custom_proj.resolve()

    # The default managed workspace should now be disallowed when allowed_roots is explicitly restricted
    managed_proj = repos_dir / "managed_proj"
    managed_proj.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path(str(managed_proj))
    assert exc_info.value.status_code == 400


def test_configuration_allowed_repo_roots_settings(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    extra_root = tmp_path / "extra"
    extra_root.mkdir()
    proj = extra_root / "extra_proj"
    proj.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        allowed_repo_roots=[str(extra_root)],
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    resolved = service.resolve_trusted_path(str(proj))
    assert resolved == proj.resolve()


def test_non_existent_directory_rejection(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path("does_not_exist")
    assert exc_info.value.status_code == 400
    assert "does not exist" in exc_info.value.detail


def test_file_instead_of_directory_rejection(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    file_path = repos_dir / "some_file.txt"
    file_path.write_text("not a directory")

    settings = Settings(
        repositories_root=str(repos_dir),
        _env_file=None,
    )
    service = IngestionService(session=None, settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        service.resolve_trusted_path("some_file.txt")
    assert exc_info.value.status_code == 400
    assert "is not a directory" in exc_info.value.detail
