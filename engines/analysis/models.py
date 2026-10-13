from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EntryPointType(str, Enum):
    """Classification of application entry points."""

    HTTP_ROUTE = "http_route"
    CLI_SCRIPT = "cli_script"
    EVENT_HANDLER = "event_handler"
    GENERIC = "generic"


@dataclass
class EntryPoint:
    """An execution root such as an API endpoint, script entry, or event listener."""

    id: str
    name: str
    file_path: str
    line_number: int
    entry_type: EntryPointType
    symbol_id: Optional[str] = None
    route_path: Optional[str] = None
    http_method: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceStep:
    """A single hop or invocation within an execution path."""

    step_index: int
    source_id: str
    target_id: str
    call_type: str = "direct_call"
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceTree:
    """Hierarchical tree representation of an execution call hierarchy."""

    node_id: str
    name: str
    depth: int = 0
    children: List["TraceTree"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceMetrics:
    """Structural metrics computed for an execution trace."""

    total_steps: int
    max_depth: int
    branching_factor: float
    distinct_files_count: int
    has_cycles: bool


@dataclass
class ExecutionTrace:
    """Complete execution trace for an entry point or traversal run."""

    entry_point: EntryPoint
    steps: List[TraceStep] = field(default_factory=list)
    tree: Optional[TraceTree] = None
    metrics: Optional[TraceMetrics] = None
