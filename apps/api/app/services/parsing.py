import asyncio
from pathlib import Path
import time
from typing import List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, settings as app_settings
from app.schemas.parsing import (
    CodeSymbolResponse,
    ImportItemResponse,
    ImportStatementResponse,
    ParameterResponse,
    ParseErrorResponse,
    ParsedFileResponse,
    ProjectParseSummaryResponse,
)
from app.services.ingestion import IngestionService
from app.services.projects import ProjectService
from engines.ingestion import CodebaseScanner
from engines.parsing import (
    CodeParser,
    CodeSymbol,
    ImportStatement,
    ParsedFileResult,
)


def _count_symbols(symbols: List[CodeSymbol]) -> int:
    """Recursively count all symbols including nested children."""
    count = 0
    for s in symbols:
        count += 1 + _count_symbols(s.children)
    return count


def _symbol_to_response(sym: CodeSymbol) -> CodeSymbolResponse:
    """Recursively convert CodeSymbol dataclass to Pydantic response schema."""
    return CodeSymbolResponse(
        name=sym.name,
        kind=sym.kind.value if hasattr(sym.kind, "value") else str(sym.kind),
        start_line=sym.start_line,
        end_line=sym.end_line,
        docstring=sym.docstring,
        decorators=sym.decorators,
        parameters=[
            ParameterResponse(
                name=p.name,
                type_annotation=p.type_annotation,
                default_value=p.default_value,
            )
            for p in sym.parameters
        ],
        return_type=sym.return_type,
        complexity=sym.complexity,
        children=[_symbol_to_response(c) for c in sym.children],
        base_classes=getattr(sym, "base_classes", []),
    )


def _import_to_response(imp: ImportStatement) -> ImportStatementResponse:
    """Convert ImportStatement dataclass to Pydantic response schema."""
    return ImportStatementResponse(
        module=imp.module,
        names=[
            ImportItemResponse(name=item.name, alias=item.alias)
            for item in imp.names
        ],
        is_from=imp.is_from,
        level=imp.level,
        line_number=imp.line_number,
    )


def _execute_file_parsing(
    project_path: Path,
    relative_file_paths: List[str],
) -> Tuple[List[ParsedFileResult], float]:
    """Worker function executed in thread pool for CPU-bound AST parsing."""
    start = time.perf_counter()
    parser = CodeParser()
    results: List[ParsedFileResult] = []

    for rel_path in relative_file_paths:
        full_path = project_path / rel_path
        results.append(parser.parse_file(full_path, relative_path=rel_path))

    duration_ms = (time.perf_counter() - start) * 1000.0
    return results, duration_ms


class ParsingService:
    """Coordinates AST parsing and code intelligence extraction for projects."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        self.session = session
        self.settings = settings or app_settings
        self.allowed_roots = allowed_roots

    async def parse_project(
        self,
        project_id: uuid.UUID,
    ) -> ProjectParseSummaryResponse:
        """Parse source files of an indexed project and extract AST code intelligence.

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
                detail=f"Project must be indexed before parsing. Current status: '{project.status}'",
            )

        if project.source_type != "local":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only 'local' source_type is supported for codebase parsing, got '{project.source_type}'",
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

        # Execute AST parsing in thread pool
        parsed_results, duration_ms = await asyncio.to_thread(
            _execute_file_parsing,
            project_path,
            relative_paths,
        )

        total_symbols = 0
        total_imports = 0
        error_files_count = 0
        file_responses: List[ParsedFileResponse] = []

        for res in parsed_results:
            symbols_count = _count_symbols(res.symbols)
            imports_count = len(res.imports)
            total_symbols += symbols_count
            total_imports += imports_count
            if res.errors:
                error_files_count += 1

            file_responses.append(
                ParsedFileResponse(
                    path=res.file_path,
                    language=res.language,
                    symbols_count=symbols_count,
                    imports_count=imports_count,
                    symbols=[_symbol_to_response(s) for s in res.symbols],
                    imports=[_import_to_response(i) for i in res.imports],
                    errors=[
                        ParseErrorResponse(
                            file_path=err.file_path,
                            line_number=err.line_number,
                            error_message=err.error_message,
                        )
                        for err in res.errors
                    ],
                    total_lines=res.total_lines,
                )
            )

        return ProjectParseSummaryResponse(
            project_id=project.id,
            status=project.status,
            parsed_files_count=len(file_responses),
            total_symbols_count=total_symbols,
            total_imports_count=total_imports,
            error_files_count=error_files_count,
            files=file_responses,
            duration_ms=round(duration_ms, 2),
        )
