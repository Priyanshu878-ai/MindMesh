from typing import List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ParameterResponse(BaseModel):
    """Schema representing a parameter in a callable code symbol."""

    name: str = Field(description="Parameter name")
    type_annotation: Optional[str] = Field(default=None, description="Type annotation string if declared")
    default_value: Optional[str] = Field(default=None, description="Default value representation if provided")

    model_config = ConfigDict(from_attributes=True)


class ImportItemResponse(BaseModel):
    """Schema representing an imported identifier."""

    name: str = Field(description="Imported identifier name")
    alias: Optional[str] = Field(default=None, description="Local alias name if aliased with 'as'")

    model_config = ConfigDict(from_attributes=True)


class ImportStatementResponse(BaseModel):
    """Schema representing an import statement."""

    module: Optional[str] = Field(default=None, description="Imported module path")
    names: List[ImportItemResponse] = Field(default_factory=list, description="Imported identifier items")
    is_from: bool = Field(default=False, description="True for 'from ... import' statements")
    level: int = Field(default=0, description="Relative import level (0 for absolute, >0 for relative dots)")
    line_number: int = Field(default=1, description="Source line number")

    model_config = ConfigDict(from_attributes=True)


class CodeSymbolResponse(BaseModel):
    """Schema representing an extracted code symbol (class, function, method)."""

    name: str = Field(description="Symbol name")
    kind: str = Field(description="Symbol classification (class, function, method, async_function)")
    start_line: int = Field(description="Starting line in source file")
    end_line: int = Field(description="Ending line in source file")
    docstring: Optional[str] = Field(default=None, description="Extracted docstring if present")
    decorators: List[str] = Field(default_factory=list, description="List of decorators applied to the symbol")
    parameters: List[ParameterResponse] = Field(default_factory=list, description="Parameters if symbol is callable")
    return_type: Optional[str] = Field(default=None, description="Return type annotation if declared")
    complexity: int = Field(default=1, description="Cyclomatic complexity score")
    children: List["CodeSymbolResponse"] = Field(default_factory=list, description="Nested child symbols")
    base_classes: List[str] = Field(default_factory=list, description="Base classes inherited by this class")

    model_config = ConfigDict(from_attributes=True)


class ParseErrorResponse(BaseModel):
    """Schema representing a syntax or decoding failure during parsing."""

    file_path: str = Field(description="Path to the file that failed to parse")
    line_number: Optional[int] = Field(default=None, description="Line number of syntax error if known")
    error_message: str = Field(description="Descriptive error message")

    model_config = ConfigDict(from_attributes=True)


class ParsedFileResponse(BaseModel):
    """Schema representing parsed AST code intelligence for a single file."""

    path: str = Field(description="Normalized relative POSIX path from project root")
    language: str = Field(description="Programming language")
    symbols_count: int = Field(ge=0, description="Total number of top-level and nested symbols")
    imports_count: int = Field(ge=0, description="Total number of import statements")
    symbols: List[CodeSymbolResponse] = Field(default_factory=list, description="Extracted code symbols")
    imports: List[ImportStatementResponse] = Field(default_factory=list, description="Extracted imports")
    errors: List[ParseErrorResponse] = Field(default_factory=list, description="Encountered parse errors")
    total_lines: int = Field(ge=0, description="Total line count")

    model_config = ConfigDict(from_attributes=True)


class ProjectParseSummaryResponse(BaseModel):
    """Schema representing aggregated AST parse results for a project."""

    project_id: uuid.UUID = Field(description="Identifier of the project")
    status: str = Field(description="Current project status")
    parsed_files_count: int = Field(ge=0, description="Number of files parsed")
    total_symbols_count: int = Field(ge=0, description="Total symbols extracted across all files")
    total_imports_count: int = Field(ge=0, description="Total import statements extracted across all files")
    error_files_count: int = Field(ge=0, description="Number of files that encountered parse errors")
    files: List[ParsedFileResponse] = Field(default_factory=list, description="List of parsed file intelligence")
    duration_ms: float = Field(ge=0, description="Parse duration in milliseconds")

    model_config = ConfigDict(from_attributes=True)
