from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    """Classification of graph nodes in the codebase dependency graph."""

    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    EXTERNAL_PACKAGE = "external_package"


class EdgeType(str, Enum):
    """Classification of directed dependency relationships."""

    IMPORTS = "imports"
    CONTAINS = "contains"
    INHERITS_FROM = "inherits_from"
    CALLS_OR_REFERENCES = "calls_or_references"


@dataclass
class GraphNode:
    """A vertex in the semantic dependency graph."""

    id: str
    name: str
    node_type: NodeType
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A directed edge representing a dependency or structural relationship."""

    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphMetrics:
    """Statistical and degree metrics computed for the dependency graph."""

    total_nodes: int
    total_edges: int
    node_counts_by_type: Dict[str, int]
    edge_counts_by_type: Dict[str, int]
    in_degrees: Dict[str, int]
    out_degrees: Dict[str, int]
    isolated_nodes_count: int


@dataclass
class DependencyGraph:
    """Complete semantic dependency graph containing nodes, edges, metrics, and cycles."""

    project_id: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    metrics: Optional[GraphMetrics] = None
    cycles: List[List[str]] = field(default_factory=list)
