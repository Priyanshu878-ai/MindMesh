import asyncio
from pathlib import Path
import time
from typing import List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, settings as app_settings
from app.schemas.graph import (
    DependencyGraphResponse,
    GraphEdgeResponse,
    GraphMetricsResponse,
    GraphNodeResponse,
)
from app.services.ingestion import IngestionService
from app.services.projects import ProjectService
from engines.graph import DependencyGraph, GraphBuilder
from engines.ingestion import CodebaseScanner
from engines.parsing import CodeParser, ParsedFileResult


def _execute_graph_building(
    project_id_str: str,
    project_path: Path,
    relative_file_paths: List[str],
) -> Tuple[DependencyGraph, float]:
    """Worker function executed in thread pool for CPU-bound AST parsing and graph building."""
    start = time.perf_counter()
    parser = CodeParser()
    parsed_results: List[ParsedFileResult] = []

    for rel_path in relative_file_paths:
        full_path = project_path / rel_path
        parsed_results.append(parser.parse_file(full_path, relative_path=rel_path))

    builder = GraphBuilder(project_id=project_id_str)
    graph = builder.build(parsed_results, all_relative_paths=relative_file_paths)
    duration_ms = (time.perf_counter() - start) * 1000.0
    return graph, duration_ms


class GraphService:
    """Coordinates codebase dependency graph construction and topological analysis."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        self.session = session
        self.settings = settings or app_settings
        self.allowed_roots = allowed_roots

    async def build_project_graph(
        self,
        project_id: uuid.UUID,
    ) -> DependencyGraphResponse:
        """Construct semantic dependency graph for an indexed project.

        Raises:
            HTTPException (404): If project does not exist.
            HTTPException (400): If project status is not 'indexed', source_type is not 'local',
                                or source path is invalid/inaccessible.
        """
        project_service = ProjectService(self.session)
        project = await project_service.get_project(project_id)

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Enforce that project must already be indexed
        if project.status != "indexed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Project must be indexed before generating dependency graph. Current status: '{project.status}'",
            )

        if project.source_type != "local":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' source_type is supported for dependency graph generation, got '{project.source_type}'",
            )

        # Validate path containment against trusted roots
        ingestion_service = IngestionService(
            self.session,
            settings=self.settings,
            allowed_roots=self.allowed_roots,
        )
        project_path = ingestion_service.resolve_trusted_path(project.source_url)

        # Discover source files within the project
        scanner = CodebaseScanner()
        scan_summary = await asyncio.to_thread(scanner.scan, project_path)

        relative_paths = [f.path for f in scan_summary.files]

        # Execute AST parsing and graph generation in thread pool
        graph, duration_ms = await asyncio.to_thread(
            _execute_graph_building,
            str(project.id),
            project_path,
            relative_paths,
        )

        node_responses = [
            GraphNodeResponse(
                id=n.id,
                name=n.name,
                node_type=n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type),
                file_path=n.file_path,
                line_number=n.line_number,
                metadata=n.metadata,
            )
            for n in graph.nodes
        ]

        edge_responses = [
            GraphEdgeResponse(
                source_id=e.source_id,
                target_id=e.target_id,
                edge_type=e.edge_type.value if hasattr(e.edge_type, "value") else str(e.edge_type),
                weight=e.weight,
                metadata=e.metadata,
            )
            for e in graph.edges
        ]

        if graph.metrics:
            metrics_response = GraphMetricsResponse(
                total_nodes=graph.metrics.total_nodes,
                total_edges=graph.metrics.total_edges,
                node_counts_by_type=graph.metrics.node_counts_by_type,
                edge_counts_by_type=graph.metrics.edge_counts_by_type,
                in_degrees=graph.metrics.in_degrees,
                out_degrees=graph.metrics.out_degrees,
                isolated_nodes_count=graph.metrics.isolated_nodes_count,
            )
        else:
            metrics_response = GraphMetricsResponse(
                total_nodes=len(node_responses),
                total_edges=len(edge_responses),
                node_counts_by_type={},
                edge_counts_by_type={},
                in_degrees={},
                out_degrees={},
                isolated_nodes_count=0,
            )

        return DependencyGraphResponse(
            project_id=project.id,
            status=project.status,
            nodes=node_responses,
            edges=edge_responses,
            metrics=metrics_response,
            cycles=graph.cycles,
            duration_ms=round(duration_ms, 2),
        )
