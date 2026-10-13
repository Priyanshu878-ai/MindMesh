from typing import Dict, List
import uuid

from pydantic import BaseModel, ConfigDict, Field


class DiscoveredFileResponse(BaseModel):
    """Schema representing a discovered file within the ingested codebase."""

    path: str = Field(description="Normalized relative POSIX path from project root")
    name: str = Field(description="File name with extension")
    extension: str = Field(description="File extension including leading dot")
    language: str = Field(description="Detected programming language or format")
    size_bytes: int = Field(ge=0, description="Size in bytes")
    total_lines: int = Field(ge=0, description="Total number of lines")
    code_lines: int = Field(ge=0, description="Number of non-blank lines")
    blank_lines: int = Field(ge=0, description="Number of blank lines")
    sha256: str = Field(description="SHA-256 hexadecimal hash of file content")

    model_config = ConfigDict(from_attributes=True)


class IngestionSummaryResponse(BaseModel):
    """Schema representing project ingestion scan results and catalog."""

    project_id: uuid.UUID = Field(description="Identifier of the ingested project")
    status: str = Field(description="Project status after ingestion")
    scanned_files_count: int = Field(ge=0, description="Total files encountered during traversal")
    included_files_count: int = Field(ge=0, description="Source files cataloged")
    skipped_files_count: int = Field(ge=0, description="Files skipped (ignored, binary, unreadable, etc.)")
    total_size_bytes: int = Field(ge=0, description="Total size in bytes of included files")
    total_lines: int = Field(ge=0, description="Total lines across all included files")
    total_code_lines: int = Field(ge=0, description="Total code lines across all included files")
    total_blank_lines: int = Field(ge=0, description="Total blank lines across all included files")
    is_truncated: bool = Field(description="Whether the scan was truncated due to configured limits")
    languages: Dict[str, int] = Field(description="Language distribution by file count")
    files: List[DiscoveredFileResponse] = Field(description="Catalog of discovered source files")
    duration_ms: float = Field(ge=0, description="Ingestion scan duration in milliseconds")

    model_config = ConfigDict(from_attributes=True)
