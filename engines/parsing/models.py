from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SymbolKind(str, Enum):
    """Classification of extracted code symbols."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"


@dataclass(frozen=True)
class ParameterInfo:
    """Metadata describing a function or method parameter."""

    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None


@dataclass(frozen=True)
class ImportItem:
    """An imported identifier and its optional local alias."""

    name: str
    alias: Optional[str] = None


@dataclass(frozen=True)
class ImportStatement:
    """Represents an import statement in source code."""

    module: Optional[str]
    names: List[ImportItem] = field(default_factory=list)
    is_from: bool = False
    level: int = 0  # 0 for absolute import, 1 for '.', 2 for '..', etc.
    line_number: int = 1


@dataclass
class CodeSymbol:
    """Extracted code construct (class, function, method)."""

    name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    parameters: List[ParameterInfo] = field(default_factory=list)
    return_type: Optional[str] = None
    complexity: int = 1
    children: List["CodeSymbol"] = field(default_factory=list)


@dataclass(frozen=True)
class ParseErrorRecord:
    """Record of a syntax or decoding failure encountered during parsing."""

    file_path: str
    line_number: Optional[int]
    error_message: str


@dataclass
class ParsedFileResult:
    """Aggregate symbol extraction and import analysis for a single source file."""

    file_path: str
    language: str
    symbols: List[CodeSymbol] = field(default_factory=list)
    imports: List[ImportStatement] = field(default_factory=list)
    errors: List[ParseErrorRecord] = field(default_factory=list)
    total_lines: int = 0
