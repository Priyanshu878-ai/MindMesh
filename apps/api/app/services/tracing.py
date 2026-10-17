import asyncio
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, settings as app_settings
from app.schemas.tracing import (
    EntryPointResponse,
    ExecutionTraceResponse,
    ProjectTraceRequest,
    ProjectTraceResponse,
    TraceMetricsResponse,
    TraceStepResponse,
    TraceTreeResponse,
)
from app.services.ingestion import IngestionService
from app.services.projects import ProjectService
from engines.analysis import (
    EntryPoint,
    EntryPointDetector,
    ExecutionTrace,
    ExecutionTracer,
    TraceStep,
    TraceTree,
)
from engines.graph import DependencyGraph, GraphBuilder
from engines.ingestion import CodebaseScanner
from engines.parsing import CodeParser, CodeSymbol, ParsedFileResult


def _convert_tree(tree_node: Optional[TraceTree]) -> Optional[TraceTreeResponse]:
    """Recursively convert engine TraceTree dataclass to Pydantic TraceTreeResponse."""
    if not tree_node:
        return None
    return TraceTreeResponse(
        node_id=tree_node.node_id,
        name=tree_node.name,
        depth=tree_node.depth,
        children=[_convert_tree(c) for c in tree_node.children if c is not None],
        metadata=tree_node.metadata,
    )


def _convert_step(step: TraceStep) -> TraceStepResponse:
    """Convert engine TraceStep dataclass to Pydantic TraceStepResponse."""
    return TraceStepResponse(
        step_index=step.step_index,
        source_id=step.source_id,
        target_id=step.target_id,
        call_type=step.call_type,
        file_path=step.file_path,
        line_number=step.line_number,
        metadata=step.metadata,
    )


def _convert_entrypoint(ep: EntryPoint) -> EntryPointResponse:
    """Convert engine EntryPoint dataclass to Pydantic EntryPointResponse."""
    return EntryPointResponse(
        id=ep.id,
        name=ep.name,
        file_path=ep.file_path,
        line_number=ep.line_number,
        entry_type=ep.entry_type.value if hasattr(ep.entry_type, "value") else str(ep.entry_type),
        symbol_id=ep.symbol_id,
        route_path=ep.route_path,
        http_method=ep.http_method,
        metadata=ep.metadata,
    )


def _execute_tracing_worker(
    project_id_str: str,
    project_path: Path,
    relative_file_paths: List[str],
    req: ProjectTraceRequest,
) -> Tuple[List[EntryPoint], Optional[ExecutionTrace], Optional[List[List[TraceStep]]], float]:
    """Worker function executed in thread pool for CPU-bound parsing, AST extraction, and tracing."""
    start = time.perf_counter()
    parser = CodeParser()
    parsed_results: List[ParsedFileResult] = []
    source_codes: Dict[str, str] = {}

    # 1. Parse codebase files and collect source codes
    for rel_path in relative_file_paths:
        full_path = project_path / rel_path
        if rel_path.endswith(".py"):
            try:
                code_text = full_path.read_text(encoding="utf-8", errors="replace")
                source_codes[rel_path] = code_text
                parsed_results.append(parser.parse_source(code_text, file_path=rel_path))
            except Exception:
                parsed_results.append(parser.parse_file(full_path, relative_path=rel_path))
        else:
            parsed_results.append(parser.parse_file(full_path, relative_path=rel_path))

    # 2. Build DependencyGraph
    builder = GraphBuilder(project_id=project_id_str)
    graph = builder.build(parsed_results, all_relative_paths=relative_file_paths)

    # 3. Detect application entrypoints
    detector = EntryPointDetector()
    entry_points = detector.detect_all(parsed_results, source_codes=source_codes)

    # 4. Collect known identifiers for symbol validation
    known_ids: Set[str] = set()
    for ep in entry_points:
        known_ids.add(ep.id)
        if ep.symbol_id:
            known_ids.add(ep.symbol_id)

    for node in graph.nodes:
        known_ids.add(node.id)

    for pf in parsed_results:
        known_ids.add(f"file:{pf.file_path}")

        def _collect_symbols(sym: CodeSymbol, prefix: str = "") -> None:
            scoped = f"{prefix}.{sym.name}" if prefix else sym.name
            known_ids.add(f"symbol:{pf.file_path}:{scoped}")
            known_ids.add(f"symbol:{pf.file_path}:{sym.name}")
            for ch in sym.children:
                _collect_symbols(ch, scoped)

        for s in pf.symbols:
            _collect_symbols(s)

    # 5. Validate requested IDs
    if req.entry_point_id and req.entry_point_id not in known_ids:
        raise ValueError(f"Entry point or symbol '{req.entry_point_id}' not found in project")

    if req.source_id and req.source_id not in known_ids:
        raise ValueError(f"Source symbol '{req.source_id}' not found in project")

    if req.target_id and req.target_id not in known_ids:
        raise ValueError(f"Target symbol '{req.target_id}' not found in project")

    # 6. Initialize ExecutionTracer
    tracer = ExecutionTracer(
        graph=graph,
        parsed_files=parsed_results,
        source_codes=source_codes,
        entry_points=entry_points,
    )

    # 7. Pathfinding if source and target are provided
    paths: Optional[List[List[TraceStep]]] = None
    if req.source_id and req.target_id:
        paths = tracer.find_execution_paths(req.source_id, req.target_id, max_depth=req.max_depth)

    # 8. Hierarchical execution tracing
    trace: Optional[ExecutionTrace] = None
    if req.entry_point_id:
        ep_match = next((ep for ep in entry_points if ep.id == req.entry_point_id), None)
        trace_target = ep_match or req.entry_point_id
        trace = tracer.trace_execution(trace_target, max_depth=req.max_depth)
    elif req.source_id and not req.target_id:
        trace = tracer.trace_execution(req.source_id, max_depth=req.max_depth)
    elif not req.source_id and not req.target_id:
        if entry_points:
            trace = tracer.trace_execution(entry_points[0], max_depth=req.max_depth)

    duration_ms = (time.perf_counter() - start) * 1000.0
    return entry_points, trace, paths, duration_ms


class TracingService:
    """Coordinates execution flow tracing, entrypoint discovery, and pathfinding."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        self.session = session
        self.settings = settings or app_settings
        self.allowed_roots = allowed_roots

    async def trace_project(
        self,
        project_id: uuid.UUID,
        request: Optional[ProjectTraceRequest] = None,
    ) -> ProjectTraceResponse:
        """Trace execution hierarchy or find execution paths in an indexed project.

        Raises:
            HTTPException (404): If project does not exist.
            HTTPException (400): If project is not indexed, source_type is not local,
                                source path escapes trusted root, or symbol IDs are invalid.
        """
        req = request or ProjectTraceRequest()

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
                detail=f"Project must be indexed before tracing execution flows. Current status: '{project.status}'",
            )

        if project.source_type not in ("local", "github"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' and 'github' source types are supported for execution tracing, got '{project.source_type}'",
            )

        # Validate path containment against trusted roots
        ingestion_service = IngestionService(
            self.session,
            settings=self.settings,
            allowed_roots=self.allowed_roots,
        )
        project_path = ingestion_service.resolve_project_path(project)

        # Scan codebase files
        scanner = CodebaseScanner()
        scan_summary = await asyncio.to_thread(scanner.scan, project_path)
        relative_paths = [f.path for f in scan_summary.files]

        # Execute analysis and tracing in thread pool
        try:
            entry_points, trace, paths, duration_ms = await asyncio.to_thread(
                _execute_tracing_worker,
                str(project.id),
                project_path,
                relative_paths,
                req,
            )
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            )

        # Format entry points response
        ep_responses = [_convert_entrypoint(ep) for ep in entry_points]

        # Format trace response
        trace_response: Optional[ExecutionTraceResponse] = None
        if trace:
            step_responses = [_convert_step(s) for s in trace.steps]
            tree_response = _convert_tree(trace.tree)
            metrics_response = TraceMetricsResponse(
                total_steps=trace.metrics.total_steps,
                max_depth=trace.metrics.max_depth,
                branching_factor=trace.metrics.branching_factor,
                distinct_files_count=trace.metrics.distinct_files_count,
                has_cycles=trace.metrics.has_cycles,
            )
            trace_response = ExecutionTraceResponse(
                entry_point=_convert_entrypoint(trace.entry_point),
                steps=step_responses,
                tree=tree_response,
                metrics=metrics_response,
            )

        # Format paths response
        paths_response: Optional[List[List[TraceStepResponse]]] = None
        if paths is not None:
            paths_response = [[_convert_step(s) for s in p] for p in paths]

        return ProjectTraceResponse(
            project_id=project.id,
            status=project.status,
            entry_points=ep_responses,
            trace=trace_response,
            paths=paths_response,
            duration_ms=round(duration_ms, 2),
        )
