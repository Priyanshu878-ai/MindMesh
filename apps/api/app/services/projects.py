from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    """Domain service handling CRUD operations for Project entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_project(self, project_in: ProjectCreate) -> Project:
        """Create and persist a new project."""
        project = Project(
            name=project_in.name,
            source_type=project_in.source_type,
            source_url=project_in.source_url,
            status=project_in.status,
        )
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get_project(self, project_id: uuid.UUID) -> Optional[Project]:
        """Retrieve a project by its UUID identifier."""
        stmt = select(Project).where(Project.id == project_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_projects(
        self, limit: int = 20, offset: int = 0
    ) -> Tuple[Sequence[Project], int]:
        """Retrieve a paginated list of projects with total count."""
        count_stmt = select(func.count()).select_from(Project)
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = (
            select(Project)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        projects = result.scalars().all()
        return projects, total

    async def update_project(
        self, project: Project, update_in: ProjectUpdate
    ) -> Project:
        """Apply partial updates to an existing project entity."""
        update_data = update_in.model_dump(exclude_unset=True)
        if not update_data:
            return project

        for field, value in update_data.items():
            setattr(project, field, value)

        project.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete_project(self, project: Project) -> None:
        """Delete an existing project entity from database."""
        await self.session.delete(project)
        await self.session.commit()
