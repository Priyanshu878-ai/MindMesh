from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProjectTraceRequest(BaseModel):
    """Request payload for execution flow tracing and pathfinding."""

    entry_point_id: Optional[str] = Field(
        default=None,
        description="Optional entry point ID (e.g. entrypoint:file:GET:/users) or symbol ID to trace execution from",
    )
    source_id: Optional[str] = Field(
        default=None,
        description="Source symbol or node ID for pathfinding",
    )
    target_id: Optional[str] = Field(
        default=None,
        description="Target symbol or node ID for pathfinding",
    )
    max_depth: int = Field(
        default=15,
        ge=1,
        le=50,
        description="Maximum traversal depth (bounded between 1 and 50)",
    )

    model_config = ConfigDict(from_attributes=True)


class EntryPointResponse(BaseModel):
    """Schema representing an application entrypoint."""

    id: str = Field(description="Unique entrypoint identifier")
    name: str = Field(description="Entrypoint or function name")
    file_path: str = Field(description="File path where entrypoint is defined")
    line_number: int = Field(description="Starting line number")
    entry_type: str = Field(description="Entry point classification (http_route, cli_script, etc.)")
    symbol_id: Optional[str] = Field(default=None, description="Target handler symbol ID")
    route_path: Optional[str] = Field(default=None, description="HTTP route path if applicable")
    http_method: Optional[str] = Field(default=None, description="HTTP method if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata dictionary")

    model_config = ConfigDict(from_attributes=True)


class TraceStepResponse(BaseModel):
    """Schema representing a single execution hop or step in the call hierarchy."""

    step_index: int = Field(ge=0, description="Sequential step index in trace")
    source_id: str = Field(description="Caller node or symbol ID")
    target_id: str = Field(description="Callee node or symbol ID")
    call_type: str = Field(description="Type of invocation (direct_call, route_handler, cli_invocation, etc.)")
    file_path: Optional[str] = Field(default=None, description="Source file path if applicable")
    line_number: Optional[int] = Field(default=None, description="Call site line number if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Step metadata")

    model_config = ConfigDict(from_attributes=True)


class TraceTreeResponse(BaseModel):
    """Schema representing a recursive execution call hierarchy tree."""

    node_id: str = Field(description="Symbol or node identifier")
    name: str = Field(description="Symbol display name")
    depth: int = Field(ge=0, description="Nesting depth in call tree")
    children: List["TraceTreeResponse"] = Field(default_factory=list, description="Child call nodes")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Tree node metadata")

    model_config = ConfigDict(from_attributes=True)


class TraceMetricsResponse(BaseModel):
    """Schema representing topological metrics of an execution trace."""

    total_steps: int = Field(ge=0, description="Total execution steps traversed")
    max_depth: int = Field(ge=0, description="Maximum call depth reached")
    branching_factor: float = Field(ge=0.0, description="Average children per non-leaf node")
    distinct_files_count: int = Field(ge=0, description="Count of distinct files traversed")
    has_cycles: bool = Field(description="Whether cycles or recursive loops were detected")

    model_config = ConfigDict(from_attributes=True)


class ExecutionTraceResponse(BaseModel):
    """Schema representing an execution trace run."""

    entry_point: EntryPointResponse = Field(description="Entry point or execution root")
    steps: List[TraceStepResponse] = Field(default_factory=list, description="Linear sequence of trace steps")
    tree: Optional[TraceTreeResponse] = Field(default=None, description="Hierarchical call tree")
    metrics: TraceMetricsResponse = Field(description="Structural metrics of trace")

    model_config = ConfigDict(from_attributes=True)


class ProjectTraceResponse(BaseModel):
    """Complete response schema for project execution tracing."""

    project_id: uuid.UUID = Field(description="Project identifier")
    status: str = Field(description="Current project status")
    entry_points: List[EntryPointResponse] = Field(default_factory=list, description="All discovered entry points")
    trace: Optional[ExecutionTraceResponse] = Field(default=None, description="Trace execution result")
    paths: Optional[List[List[TraceStepResponse]]] = Field(default=None, description="Discovered paths between source and target")
    duration_ms: float = Field(ge=0.0, description="Execution and analysis duration in milliseconds")

    model_config = ConfigDict(from_attributes=True)
