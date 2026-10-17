import asyncio
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import List, Optional
import uuid

from fastapi import HTTPException, Request, UploadFile, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, settings as app_settings
from app.models.project import Project
from app.schemas.ingestion import DiscoveredFileResponse, IngestionSummaryResponse
from app.schemas.project import ProjectCreate
from app.services.projects import ProjectService
from engines.ingestion import (
    ArchiveConfig,
    ArchiveExtractionError,
    CodebaseScanner,
    GitCloneConfig,
    GitCloneError,
    IngestionConfig,
    SafeGitCloner,
    SafeZipExtractor,
    validate_github_url,
)



class IngestionService:
    """Coordinates local repository scanning and project lifecycle updates."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        self.session = session
        self.settings = settings or app_settings
        self.allowed_roots = allowed_roots

    def resolve_trusted_path(self, source_url: Optional[str]) -> Path:
        """Validate and resolve source_url against trusted local directory roots.

        Canonicalizes paths, enforces strict containment within approved roots,
        and prevents directory traversal and symlink escapes.

        Raises:
            HTTPException (400): If source_url is missing, outside trusted roots,
                                or not an existing directory.
        """
        if not source_url or not source_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project does not have a configured local source directory",
            )

        raw_path = Path(source_url.strip())
        managed_workspace = self.settings.get_repositories_dir(create=True)

        # Determine allowed roots
        allowed: list[Path] = []
        if self.allowed_roots is not None:
            # Explicit override provided by caller (e.g. test isolation)
            allowed.extend([p.resolve() for p in self.allowed_roots])
        else:
            if self.settings.allowed_repo_roots:
                for p in self.settings.allowed_repo_roots:
                    cand = Path(p)
                    if cand.is_absolute():
                        allowed.append(cand.resolve())
                    else:
                        allowed.append((self.settings.project_root / cand).resolve())

            if self.settings.local_projects_root:
                cand = Path(self.settings.local_projects_root)
                if cand.is_absolute():
                    allowed.append(cand.resolve())
                else:
                    allowed.append((self.settings.project_root / cand).resolve())

            # Always register dedicated managed repository workspace
            allowed.append(managed_workspace)

        if not allowed:
            allowed.append(managed_workspace)

        # Resolve path
        if not raw_path.is_absolute():
            resolved_path = None

            # 1. Check relative to managed workspace
            cand_managed = (managed_workspace / raw_path).resolve()
            if cand_managed.exists() and (cand_managed == managed_workspace or cand_managed.is_relative_to(managed_workspace)):
                resolved_path = cand_managed

            # 2. Check relative to any configured root
            if resolved_path is None:
                for root in allowed:
                    candidate = (root / raw_path).resolve()
                    if candidate.exists() and (candidate == root or candidate.is_relative_to(root)):
                        resolved_path = candidate
                        break

            # 3. Check relative to project root
            if resolved_path is None:
                cand_project = (self.settings.project_root / raw_path).resolve()
                for root in allowed:
                    if cand_project.exists() and (cand_project == root or cand_project.is_relative_to(root)):
                        resolved_path = cand_project
                        break

            # 4. Fallback to candidate inside primary root
            if resolved_path is None:
                primary_root = allowed[0]
                resolved_path = (primary_root / raw_path).resolve()
        else:
            resolved_path = raw_path.resolve()

        # Check containment within any allowed root
        is_safe = False
        for root in allowed:
            try:
                if resolved_path == root or resolved_path.is_relative_to(root):
                    is_safe = True
                    break
            except (ValueError, TypeError):
                continue

        if not is_safe:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Path '{source_url}' is outside the trusted local directory roots",
            )

        if not resolved_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Configured project path does not exist: {source_url}",
            )

        if not resolved_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Configured project path is not a directory: {source_url}",
            )

        return resolved_path

    def resolve_project_path(self, project: Project) -> Path:
        """Resolve and validate the local directory path for a project against trusted roots.

        Supports both 'local' projects (resolved via project.source_url) and 'github'
        projects (resolved via the dedicated workspace directory gh-{project.id} or source_url).
        """
        if project.source_type not in ("local", "github"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' and 'github' source types are supported for codebase ingestion, got '{project.source_type}'",
            )

        if project.source_type == "github":
            # If source_url is a GitHub URL (or not a local directory), use managed workspace directory
            if not project.source_url or project.source_url.startswith(("http://", "https://")):
                base_workspace = (
                    self.allowed_roots[0]
                    if self.allowed_roots
                    else self.settings.get_repositories_dir(create=True)
                )
                gh_dir = (base_workspace / f"gh-{project.id}").resolve()
                return self.resolve_trusted_path(str(gh_dir))

        return self.resolve_trusted_path(project.source_url)

    async def ingest_project(
        self,
        project_id: uuid.UUID,
        config: Optional[IngestionConfig] = None,
    ) -> IngestionSummaryResponse:
        """Execute ingestion scan for a project and update status.

        Status transitions:
            pending/indexed/failed -> ingesting -> indexed (on complete success)
            pending/indexed/failed -> ingesting -> failed (on scan failure or truncation)

        Raises:
            HTTPException (404): If project does not exist.
            HTTPException (400): If project source_type is unsupported or path is invalid.
            HTTPException (409): If project is already currently ingesting.
            HTTPException (422): If scan is truncated due to limit thresholds.
            HTTPException (500): If scan encounters unhandled runtime failure.
        """
        project_service = ProjectService(self.session)
        project = await project_service.get_project(project_id)

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        if project.source_type not in ("local", "github"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' and 'github' source types are supported for codebase ingestion, got '{project.source_type}'",
            )

        # Preliminary concurrency check
        if project.status == "ingesting":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project ingestion is already in progress",
            )

        # Validate path before altering project state (leaves status unchanged on invalid paths)
        project_path = self.resolve_project_path(project)

        # Atomic database-level state claiming:
        # Prevents race conditions from simultaneous requests claiming the same project.
        claim_stmt = (
            update(Project)
            .where(Project.id == project_id, Project.status != "ingesting")
            .values(status="ingesting", updated_at=datetime.now(timezone.utc))
            .returning(Project)
        )
        claim_result = await self.session.execute(claim_stmt)
        claimed_project = claim_result.scalar_one_or_none()
        await self.session.commit()

        if claimed_project is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project ingestion is already in progress",
            )

        project = claimed_project
        scanner = CodebaseScanner(config=config)
        try:
            # Run scanner in worker thread to prevent event loop blocking
            summary = await asyncio.to_thread(scanner.scan, project_path)

            if summary.is_truncated:
                # Never silently label an incomplete scan as fully indexed
                # Only update to failed if project is still in 'ingesting' status
                truncate_stmt = (
                    update(Project)
                    .where(Project.id == project_id, Project.status == "ingesting")
                    .values(status="failed", updated_at=datetime.now(timezone.utc))
                    .returning(Project)
                )
                await self.session.execute(truncate_stmt)
                await self.session.commit()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Ingestion scan was truncated because it exceeded maximum file limit (10,000 files). Status set to failed.",
                )

            # Complete successful scan only if still in 'ingesting' status
            success_stmt = (
                update(Project)
                .where(Project.id == project_id, Project.status == "ingesting")
                .values(status="indexed", updated_at=datetime.now(timezone.utc))
                .returning(Project)
            )
            success_result = await self.session.execute(success_stmt)
            updated_proj = success_result.scalar_one_or_none()
            await self.session.commit()

            final_status = updated_proj.status if updated_proj else "indexed"

            return IngestionSummaryResponse(
                project_id=project.id,
                status=final_status,
                scanned_files_count=summary.scanned_files_count,
                included_files_count=summary.included_files_count,
                skipped_files_count=summary.skipped_files_count,
                total_size_bytes=summary.total_size_bytes,
                total_lines=summary.total_lines,
                total_code_lines=summary.total_code_lines,
                total_blank_lines=summary.total_blank_lines,
                is_truncated=summary.is_truncated,
                languages=summary.languages,
                files=[
                    DiscoveredFileResponse(
                        path=f.path,
                        name=f.name,
                        extension=f.extension,
                        language=f.language,
                        size_bytes=f.size_bytes,
                        total_lines=f.total_lines,
                        code_lines=f.code_lines,
                        blank_lines=f.blank_lines,
                        sha256=f.sha256,
                    )
                    for f in summary.files
                ],
                duration_ms=summary.duration_ms,
            )

        except HTTPException:
            # Re-raise explicit HTTP exceptions
            raise
        except Exception as exc:
            # On unexpected scan failures, mark failed only if still in 'ingesting' status
            fail_stmt = (
                update(Project)
                .where(Project.id == project_id, Project.status == "ingesting")
                .values(status="failed", updated_at=datetime.now(timezone.utc))
            )
            await self.session.execute(fail_stmt)
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ingestion scan failed: {str(exc)}",
            )

    async def upload_zip_project(
        self,
        file: UploadFile,
        name: Optional[str] = None,
        auto_ingest: bool = True,
        request: Optional[Request] = None,
    ) -> Project:
        """Validate, safely extract, and register a project from an uploaded ZIP archive.

        Security protections:
        - Rejects non-ZIP files and corrupted archives.
        - Enforces resource limits (archive size, total uncompressed size, single file size, entry count).
        - Prevents zip bombs by enforcing compression ratio limits.
        - Defends against Zip Slip by rejecting traversal and absolute paths.
        - Rejects symlinks, special files, and path collisions.
        - Extracts to a unique directory under the managed repositories workspace.
        - Cleans up partial extractions on any validation or extraction failure.
        - Seamlessly triggers initial codebase indexing if auto_ingest is enabled.
        """
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .zip archives are supported",
            )

        # Check Content-Length header early if provided in request or multipart part
        cl_str: Optional[str] = None
        if request and "content-length" in request.headers:
            cl_str = request.headers["content-length"]
        elif file.headers and "content-length" in file.headers:
            cl_str = file.headers["content-length"]

        if cl_str:
            try:
                if int(cl_str) > self.settings.max_zip_upload_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Upload size exceeds maximum allowed limit of {self.settings.max_zip_upload_size_bytes} bytes",
                    )
            except ValueError:
                pass

        # Derive project name
        if name and name.strip():
            project_name = name.strip()
        else:
            raw_stem = Path(file.filename).stem.strip()
            project_name = raw_stem if raw_stem else "uploaded-project"

        # Determine target workspace root
        if self.allowed_roots:
            base_workspace = self.allowed_roots[0]
        else:
            base_workspace = self.settings.get_repositories_dir(create=True)

        safe_slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in project_name)[:40].strip("_")
        if not safe_slug:
            safe_slug = "project"
        unique_folder = f"{safe_slug}-{uuid.uuid4().hex[:8]}"
        dest_dir = base_workspace / unique_folder

        archive_config = ArchiveConfig(
            max_archive_size_bytes=self.settings.max_zip_upload_size_bytes,
            max_total_uncompressed_size_bytes=self.settings.max_zip_extracted_size_bytes,
            max_file_count=self.settings.max_zip_file_count,
            max_single_file_size_bytes=self.settings.max_zip_single_file_size_bytes,
            max_compression_ratio=self.settings.max_zip_compression_ratio,
        )
        extractor = SafeZipExtractor(config=archive_config)

        try:
            await asyncio.to_thread(extractor.extract, file.file, dest_dir)
        except ArchiveExtractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Archive extraction failed: {str(exc)}",
            )
        except Exception as exc:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process archive: {str(exc)}",
            )

        project_service = ProjectService(self.session)
        project_in = ProjectCreate(
            name=project_name,
            source_type="local",
            source_url=str(dest_dir.resolve()),
            status="pending",
        )
        try:
            project = await project_service.create_project(project_in)
        except Exception:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise

        if auto_ingest:
            try:
                await self.ingest_project(project.id)
                refreshed = await project_service.get_project(project.id)
                if refreshed is not None:
                    project = refreshed
            except Exception:
                # Cleanup project record and extracted directory on indexing failure
                try:
                    await project_service.delete_project(project)
                except Exception:
                    pass
                if dest_dir.exists():
                    shutil.rmtree(dest_dir, ignore_errors=True)
                raise
        return project

    async def import_github_project(
        self,
        url: str,
        name: Optional[str] = None,
        auto_ingest: bool = True,
    ) -> Project:
        """Validate GitHub URL, clone into managed workspace, and register project.

        Security protections:
        - Validates GitHub URL against strict allowlist schema.
        - Rejects credentials, traversal, command injection, non-https schemes, and unsupported hosts.
        - Executes git clone using argument lists with shell=False.
        - Clones shallow (--depth 1 --single-branch --no-tags) with disabled interactive prompts.
        - Enforces timeout, file count, and repository size limits.
        - Detects and rejects escaping symlinks.
        - Clones into a unique directory in the managed repository workspace.
        - Performs atomic cleanup of directory and database record on any failure.
        - Triggers initial codebase indexing if auto_ingest is enabled.
        """
        try:
            canonical_url, owner, repo = validate_github_url(url)
        except GitCloneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        # Derive project name
        if name and name.strip():
            project_name = name.strip()
        else:
            project_name = repo

        project_id = uuid.uuid4()

        # Determine target workspace root
        if self.allowed_roots:
            base_workspace = self.allowed_roots[0]
        else:
            base_workspace = self.settings.get_repositories_dir(create=True)

        dest_dir = (base_workspace / f"gh-{project_id}").resolve()

        clone_config = GitCloneConfig(
            clone_timeout_seconds=self.settings.git_clone_timeout_seconds,
            max_clone_size_bytes=self.settings.max_git_clone_size_bytes,
            max_file_count=self.settings.max_git_clone_file_count,
        )
        cloner = SafeGitCloner(config=clone_config)

        try:
            await asyncio.to_thread(cloner.clone, canonical_url, dest_dir)
        except GitCloneError as exc:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"GitHub clone failed: {str(exc)}",
            )
        except Exception as exc:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to clone repository: {str(exc)}",
            )

        project_service = ProjectService(self.session)
        project = Project(
            id=project_id,
            name=project_name,
            source_type="github",
            source_url=canonical_url,
            status="pending",
        )
        try:
            self.session.add(project)
            await self.session.commit()
            await self.session.refresh(project)
        except Exception:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise

        if auto_ingest:
            try:
                await self.ingest_project(project.id)
                refreshed = await project_service.get_project(project.id)
                if refreshed is not None:
                    project = refreshed
            except Exception:
                # Cleanup project record and cloned directory on indexing failure
                try:
                    await project_service.delete_project(project)
                except Exception:
                    pass
                if dest_dir.exists():
                    shutil.rmtree(dest_dir, ignore_errors=True)
                raise

        return project
