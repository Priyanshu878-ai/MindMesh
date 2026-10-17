from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FileDescriptor:
    """Metadata describing a discovered and cataloged source code file."""

    path: str  # POSIX relative path from project root (e.g., "src/main.py")
    name: str  # File name with extension (e.g., "main.py")
    extension: str  # Extension with leading dot (e.g., ".py")
    language: str  # Detected programming language / format (e.g., "Python")
    size_bytes: int  # File size in bytes
    total_lines: int  # Total lines counted
    code_lines: int  # Non-blank lines
    blank_lines: int  # Blank or whitespace-only lines
    sha256: str  # SHA-256 hexadecimal hash of file content


@dataclass(frozen=True)
class SkippedFile:
    """Record of a file omitted during ingestion with explanation."""

    path: str
    reason: str  # "binary", "file_too_large", "ignored", "symlink_outside_root", "unreadable"


@dataclass
class IngestionConfig:
    """Configuration limits and options for repository ingestion."""

    max_file_size_bytes: int = 5 * 1024 * 1024  # 5 MiB per file limit
    max_total_files: int = 10_000  # Maximum total files to scan
    follow_symlinks: bool = False
    custom_ignore_patterns: List[str] = field(default_factory=list)


@dataclass
class IngestionSummary:
    """Aggregated scan results and metrics for an ingested repository."""

    project_root: str
    scanned_files_count: int
    included_files_count: int
    skipped_files_count: int
    total_size_bytes: int
    total_lines: int
    total_code_lines: int
    total_blank_lines: int
    is_truncated: bool
    languages: Dict[str, int] = field(default_factory=dict)
    files: List[FileDescriptor] = field(default_factory=list)
    skipped_files: List[SkippedFile] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class ArchiveConfig:
    """Security thresholds and limits for ZIP archive validation and extraction."""

    max_archive_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_total_uncompressed_size_bytes: int = 200 * 1024 * 1024  # 200 MB
    max_file_count: int = 10_000
    max_single_file_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_compression_ratio: float = 100.0


@dataclass(frozen=True)
class ArchiveExtractionResult:
    """Summary of safe archive extraction output."""

    destination_path: Path
    extracted_files_count: int
    total_uncompressed_bytes: int
