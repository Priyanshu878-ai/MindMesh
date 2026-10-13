import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, settings as app_settings
from app.models.project import Project
from app.schemas.ingestion import DiscoveredFileResponse, IngestionSummaryResponse
from app.services.projects import ProjectService
from engines.ingestion import CodebaseScanner, IngestionConfig


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

        # Determine allowed roots
        allowed: list[Path] = []
        if self.allowed_roots:
            allowed.extend([p.resolve() for p in self.allowed_roots])
        if self.settings.allowed_repo_roots:
            allowed.extend([Path(p).resolve() for p in self.settings.allowed_repo_roots])
        if self.settings.local_projects_root:
            allowed.append(Path(self.settings.local_projects_root).resolve())

        # If no specific roots are configured, default to current working directory
        if not allowed:
            allowed.append(Path.cwd().resolve())

        # Resolve path
        if not raw_path.is_absolute():
            resolved_path = None
            for root in allowed:
                candidate = (root / raw_path).resolve()
                if candidate.exists() and (candidate == root or candidate.is_relative_to(root)):
                    resolved_path = candidate
                    break
            if resolved_path is None:
                resolved_path = (allowed[0] / raw_path).resolve()
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

    async def ingest_project(
        self,
        project_id: uuid.UUID,
        config: Optional[IngestionConfig] = None,
    ) -> IngestionSummaryResponse:
        """Execute ingestion scan for a local project and update status.

        Status transitions:
            pending/indexed/failed -> ingesting -> indexed (on complete success)
            pending/indexed/failed -> ingesting -> failed (on scan failure or truncation)

        Raises:
            HTTPException (404): If project does not exist.
            HTTPException (400): If project source_type is not 'local' or path is invalid.
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

        if project.source_type != "local":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' source_type is supported for codebase ingestion, got '{project.source_type}'",
            )

        # Preliminary concurrency check
        if project.status == "ingesting":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project ingestion is already in progress",
            )

        # Validate local path before altering project state (leaves status unchanged on invalid paths)
        project_path = self.resolve_trusted_path(project.source_url)

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
