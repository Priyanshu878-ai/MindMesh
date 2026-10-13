from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.graph import DependencyGraphResponse
from app.schemas.ingestion import IngestionSummaryResponse
from app.schemas.parsing import ProjectParseSummaryResponse
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.graph import GraphService
from app.services.ingestion import IngestionService
from app.services.parsing import ParsingService
from app.services.projects import ProjectService

router = APIRouter()


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    project_in: ProjectCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    """Create a new codebase project record."""
    service = ProjectService(session)
    project = await service.create_project(project_in)
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    status_code=status.HTTP_200_OK,
    summary="List projects",
)
async def list_projects(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Maximum number of items to return (1-100)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Number of items to skip (>= 0)",
        ),
    ] = 0,
) -> PaginatedResponse[ProjectResponse]:
    """Retrieve a paginated collection of projects."""
    service = ProjectService(session)
    projects, total = await service.list_projects(limit=limit, offset=offset)
    return PaginatedResponse[ProjectResponse](
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get project by ID",
)
async def get_project(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    """Retrieve details for a specific project by UUID."""
    service = ProjectService(session)
    project = await service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update project partially",
)
async def update_project(
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    """Partially update project attributes by UUID."""
    service = ProjectService(session)
    project = await service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    updated_project = await service.update_project(project, project_in)
    return ProjectResponse.model_validate(updated_project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete a project record by UUID."""
    service = ProjectService(session)
    project = await service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    await service.delete_project(project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/ingest",
    response_model=IngestionSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest codebase for project",
)
async def ingest_project(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionSummaryResponse:
    """Trigger codebase ingestion scan for a local project."""
    service = IngestionService(session)
    return await service.ingest_project(project_id)


@router.post(
    "/{project_id}/parse",
    response_model=ProjectParseSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse AST code intelligence for project",
)
async def parse_project(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectParseSummaryResponse:
    """Parse codebase AST to extract classes, functions, methods, imports, and metrics."""
    service = ParsingService(session)
    return await service.parse_project(project_id)


@router.post(
    "/{project_id}/graph",
    response_model=DependencyGraphResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate semantic dependency graph for project",
)
async def generate_project_graph(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DependencyGraphResponse:
    """Generate semantic dependency graph with import, containment, and inheritance edges."""
    service = GraphService(session)
    return await service.build_project_graph(project_id)
