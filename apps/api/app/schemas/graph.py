from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class GraphNodeResponse(BaseModel):
    """Schema representing a vertex in the dependency graph."""

    id: str = Field(description="Unique node identifier")
    name: str = Field(description="Display or symbol name of the node")
    node_type: str = Field(description="Node type classification (e.g. file, class, function, external_package)")
    file_path: Optional[str] = Field(default=None, description="Relative POSIX path of source file if applicable")
    line_number: Optional[int] = Field(default=None, description="Source line number if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional node metadata")

    model_config = ConfigDict(from_attributes=True)


class GraphEdgeResponse(BaseModel):
    """Schema representing a directed relationship in the dependency graph."""

    source_id: str = Field(description="Identifier of source node")
    target_id: str = Field(description="Identifier of target node")
    edge_type: str = Field(description="Edge type (imports, contains, inherits_from, calls_or_references)")
    weight: float = Field(default=1.0, description="Edge weight")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional edge metadata")

    model_config = ConfigDict(from_attributes=True)


class GraphMetricsResponse(BaseModel):
    """Schema representing graph topological and degree metrics."""

    total_nodes: int = Field(ge=0, description="Total number of nodes")
    total_edges: int = Field(ge=0, description="Total number of edges")
    node_counts_by_type: Dict[str, int] = Field(default_factory=dict, description="Node distribution by type")
    edge_counts_by_type: Dict[str, int] = Field(default_factory=dict, description="Edge distribution by type")
    in_degrees: Dict[str, int] = Field(default_factory=dict, description="In-degree map by node ID")
    out_degrees: Dict[str, int] = Field(default_factory=dict, description="Out-degree map by node ID")
    isolated_nodes_count: int = Field(ge=0, description="Count of nodes with zero degree")

    model_config = ConfigDict(from_attributes=True)


class DependencyGraphResponse(BaseModel):
    """Schema representing the complete semantic dependency graph response."""

    project_id: uuid.UUID = Field(description="Identifier of the project")
    status: str = Field(description="Current project status")
    nodes: List[GraphNodeResponse] = Field(default_factory=list, description="List of graph nodes")
    edges: List[GraphEdgeResponse] = Field(default_factory=list, description="List of directed edges")
    metrics: GraphMetricsResponse = Field(description="Graph metrics and degree distributions")
    cycles: List[List[str]] = Field(default_factory=list, description="List of detected dependency cycles")
    duration_ms: float = Field(ge=0, description="Graph construction duration in milliseconds")

    model_config = ConfigDict(from_attributes=True)
