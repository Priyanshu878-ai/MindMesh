/**
 * Semantic Dependency Graph types matching backend Feature #7 API response contracts.
 */

export type NodeType =
  | 'file'
  | 'module'
  | 'class'
  | 'function'
  | 'async_function'
  | 'method'
  | 'external_package';

export type EdgeType =
  | 'imports'
  | 'contains'
  | 'inherits_from'
  | 'calls_or_references';

export interface GraphNode {
  id: string;
  name: string;
  node_type: NodeType;
  file_path?: string | null;
  line_number?: number | null;
  metadata?: Record<string, unknown>;
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  edge_type: EdgeType;
  weight: number;
  metadata?: Record<string, unknown>;
}

export interface GraphMetrics {
  total_nodes: number;
  total_edges: number;
  node_counts_by_type: Record<string, number>;
  edge_counts_by_type: Record<string, number>;
  in_degrees: Record<string, number>;
  out_degrees: Record<string, number>;
  isolated_nodes_count: number;
}

export interface DependencyGraphResponse {
  project_id: string;
  status: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  metrics: GraphMetrics;
  cycles: string[][];
  duration_ms: number;
}

export interface Vector3D {
  x: number;
  y: number;
  z: number;
}

export interface Node3D extends GraphNode {
  position: Vector3D;
  color: string;
  size: number;
  cluster: string;
  inCycle?: boolean;
}

export interface Edge3D extends GraphEdge {
  color: string;
  opacity: number;
  inCycle?: boolean;
}

export interface GraphVisualizationData {
  nodes: Node3D[];
  edges: Edge3D[];
  nodeMap: Map<string, Node3D>;
  metrics: GraphMetrics;
  cycles: string[][];
  cycleNodeIds: Set<string>;
  cycleEdgeKeys: Set<string>;
}

export interface GraphFilterOptions {
  visibleNodeTypes?: Set<NodeType>;
  visibleEdgeTypes?: Set<EdgeType>;
  searchQuery?: string;
  highlightCyclesOnly?: boolean;
}
