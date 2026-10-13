import type {
  DependencyGraphResponse,
  Edge3D,
  EdgeType,
  GraphEdge,
  GraphFilterOptions,
  GraphNode,
  GraphVisualizationData,
  Node3D,
  NodeType,
  Vector3D,
} from '../types/graph';

export const NODE_TYPE_COLORS: Record<NodeType, string> = {
  file: '#3b82f6', // blue
  module: '#60a5fa', // light blue
  class: '#a855f7', // purple
  function: '#10b981', // emerald
  async_function: '#06b6d4', // cyan
  method: '#f59e0b', // amber
  external_package: '#64748b', // slate
};

export const NODE_TYPE_SIZES: Record<NodeType, number> = {
  file: 12,
  module: 10,
  class: 10,
  function: 7,
  async_function: 7,
  method: 5,
  external_package: 10,
};

export const EDGE_TYPE_COLORS: Record<EdgeType, string> = {
  contains: '#94a3b8',
  imports: '#60a5fa',
  inherits_from: '#c084fc',
  calls_or_references: '#34d399',
};

export const CYCLE_HIGHLIGHT_COLOR = '#ef4444'; // bright red

export interface LayoutOptions {
  radius?: number;
  symbolOrbitRadius?: number;
  externalRadius?: number;
}

/**
 * Extract node IDs and edge directional keys that are part of circular dependencies.
 */
export function extractCycleElements(cycles: string[][]): {
  cycleNodeIds: Set<string>;
  cycleEdgeKeys: Set<string>;
} {
  const cycleNodeIds = new Set<string>();
  const cycleEdgeKeys = new Set<string>();

  for (const cycle of cycles) {
    if (!cycle || cycle.length < 2) continue;

    for (let i = 0; i < cycle.length - 1; i++) {
      const u = cycle[i];
      const v = cycle[i + 1];
      cycleNodeIds.add(u);
      cycleNodeIds.add(v);
      cycleEdgeKeys.add(`${u}->${v}`);
    }
  }

  return { cycleNodeIds, cycleEdgeKeys };
}

/**
 * Deterministically compute 3D positions for graph vertices.
 * Clusters symbols near their parent files and projects external dependencies into an outer shell.
 */
export function computeDeterministic3DLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: LayoutOptions = {}
): Map<string, Vector3D> {
  const baseRadius = options.radius ?? 180;
  const symbolOrbitRadius = options.symbolOrbitRadius ?? 28;
  const externalRadius = options.externalRadius ?? 320;

  const positions = new Map<string, Vector3D>();

  // 1. Separate file nodes, external packages, and symbols
  const fileNodes: GraphNode[] = [];
  const externalNodes: GraphNode[] = [];
  const symbolNodes: GraphNode[] = [];

  for (const node of nodes) {
    if (node.node_type === 'file') {
      fileNodes.push(node);
    } else if (node.node_type === 'external_package') {
      externalNodes.push(node);
    } else {
      symbolNodes.push(node);
    }
  }

  // Sort deterministically by id
  fileNodes.sort((a, b) => a.id.localeCompare(b.id));
  externalNodes.sort((a, b) => a.id.localeCompare(b.id));
  symbolNodes.sort((a, b) => a.id.localeCompare(b.id));

  // 2. Position file nodes using Fibonacci sphere for uniform, deterministic 3D dispersion
  const numFiles = fileNodes.length;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < numFiles; i++) {
    const file = fileNodes[i];
    let y = 0;
    let radiusAtY = 1.0;

    if (numFiles > 1) {
      y = 1 - (i / (numFiles - 1)) * 2; // from 1 to -1
      radiusAtY = Math.sqrt(Math.max(0, 1 - y * y));
    }

    const theta = goldenAngle * i;
    const x = Math.cos(theta) * radiusAtY;
    const z = Math.sin(theta) * radiusAtY;

    positions.set(file.id, {
      x: Math.round(x * baseRadius * 100) / 100,
      y: Math.round(y * baseRadius * 100) / 100,
      z: Math.round(z * baseRadius * 100) / 100,
    });
  }

  // 3. Position external nodes on an outer horizontal orbit
  const numExt = externalNodes.length;
  for (let i = 0; i < numExt; i++) {
    const ext = externalNodes[i];
    const angle = (2 * Math.PI * i) / (numExt || 1);
    positions.set(ext.id, {
      x: Math.round(Math.cos(angle) * externalRadius * 100) / 100,
      y: Math.round(((i % 2 === 0 ? 1 : -1) * 20) * 100) / 100,
      z: Math.round(Math.sin(angle) * externalRadius * 100) / 100,
    });
  }

  // 4. Position symbols orbiting their containing file or class
  // Map containing edges: parent -> children
  const parentOf = new Map<string, string>();
  for (const edge of edges) {
    if (edge.edge_type === 'contains') {
      parentOf.set(edge.target_id, edge.source_id);
    }
  }

  // Group symbols by their parent (or file_path if no contains edge)
  const symbolsByParent = new Map<string, GraphNode[]>();
  for (const sym of symbolNodes) {
    let parentId = parentOf.get(sym.id);
    if (!parentId && sym.file_path) {
      parentId = `file:${sym.file_path}`;
    }
    parentId = parentId || 'root';

    const group = symbolsByParent.get(parentId) || [];
    group.push(sym);
    symbolsByParent.set(parentId, group);
  }

  for (const [parentId, childSymbols] of symbolsByParent.entries()) {
    const parentPos = positions.get(parentId) || { x: 0, y: 0, z: 0 };
    const count = childSymbols.length;

    for (let j = 0; j < count; j++) {
      const child = childSymbols[j];
      const angle = (2 * Math.PI * j) / count;
      const verticalOffset = ((j % 3) - 1) * 8;

      positions.set(child.id, {
        x: Math.round((parentPos.x + Math.cos(angle) * symbolOrbitRadius) * 100) / 100,
        y: Math.round((parentPos.y + verticalOffset) * 100) / 100,
        z: Math.round((parentPos.z + Math.sin(angle) * symbolOrbitRadius) * 100) / 100,
      });
    }
  }

  return positions;
}

/**
 * Transform raw backend DependencyGraphResponse into structured 3D visualization objects.
 */
export function transformDependencyGraph(
  raw: DependencyGraphResponse,
  layoutOptions?: LayoutOptions
): GraphVisualizationData {
  const { cycleNodeIds, cycleEdgeKeys } = extractCycleElements(raw.cycles || []);
  const positions = computeDeterministic3DLayout(raw.nodes, raw.edges, layoutOptions);

  const nodeMap = new Map<string, Node3D>();
  const nodes3D: Node3D[] = [];

  for (const node of raw.nodes) {
    const pos = positions.get(node.id) || { x: 0, y: 0, z: 0 };
    const inCycle = cycleNodeIds.has(node.id);
    const color = inCycle
      ? CYCLE_HIGHLIGHT_COLOR
      : NODE_TYPE_COLORS[node.node_type] || '#94a3b8';
    const size = NODE_TYPE_SIZES[node.node_type] || 6;

    let cluster = 'internal';
    if (node.node_type === 'external_package') {
      cluster = 'external';
    } else if (node.file_path) {
      const parts = node.file_path.split('/');
      cluster = parts.length > 1 ? parts[0] : 'root';
    }

    const node3D: Node3D = {
      ...node,
      position: pos,
      color,
      size,
      cluster,
      inCycle,
    };

    nodeMap.set(node.id, node3D);
    nodes3D.push(node3D);
  }

  const edges3D: Edge3D[] = [];
  for (const edge of raw.edges) {
    const edgeKey = `${edge.source_id}->${edge.target_id}`;
    const inCycle = cycleEdgeKeys.has(edgeKey);
    const color = inCycle
      ? CYCLE_HIGHLIGHT_COLOR
      : EDGE_TYPE_COLORS[edge.edge_type] || '#94a3b8';
    const opacity = inCycle ? 0.95 : edge.edge_type === 'contains' ? 0.25 : 0.6;

    edges3D.push({
      ...edge,
      color,
      opacity,
      inCycle,
    });
  }

  return {
    nodes: nodes3D,
    edges: edges3D,
    nodeMap,
    metrics: raw.metrics,
    cycles: raw.cycles || [],
    cycleNodeIds,
    cycleEdgeKeys,
  };
}

/**
 * Filter graph nodes and edges according to interactive visibility preferences.
 */
export function filterGraph(
  data: GraphVisualizationData,
  filters: GraphFilterOptions
): GraphVisualizationData {
  const query = (filters.searchQuery || '').trim().toLowerCase();
  const visibleNodeTypes = filters.visibleNodeTypes;
  const visibleEdgeTypes = filters.visibleEdgeTypes;
  const cyclesOnly = Boolean(filters.highlightCyclesOnly);

  // 1. Filter nodes
  const filteredNodes = data.nodes.filter((node) => {
    if (cyclesOnly && !node.inCycle) {
      return false;
    }
    if (visibleNodeTypes && !visibleNodeTypes.has(node.node_type)) {
      return false;
    }
    if (query) {
      const matchName = node.name.toLowerCase().includes(query);
      const matchPath = node.file_path?.toLowerCase().includes(query) ?? false;
      const matchId = node.id.toLowerCase().includes(query);
      if (!matchName && !matchPath && !matchId) {
        return false;
      }
    }
    return true;
  });

  const keptNodeIds = new Set(filteredNodes.map((n) => n.id));
  const filteredNodeMap = new Map<string, Node3D>();
  for (const node of filteredNodes) {
    filteredNodeMap.set(node.id, node);
  }

  // 2. Filter edges (both endpoints must remain visible)
  const filteredEdges = data.edges.filter((edge) => {
    if (!keptNodeIds.has(edge.source_id) || !keptNodeIds.has(edge.target_id)) {
      return false;
    }
    if (cyclesOnly && !edge.inCycle) {
      return false;
    }
    if (visibleEdgeTypes && !visibleEdgeTypes.has(edge.edge_type)) {
      return false;
    }
    return true;
  });

  return {
    nodes: filteredNodes,
    edges: filteredEdges,
    nodeMap: filteredNodeMap,
    metrics: data.metrics,
    cycles: data.cycles,
    cycleNodeIds: data.cycleNodeIds,
    cycleEdgeKeys: data.cycleEdgeKeys,
  };
}
