from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from engines.graph.models import EdgeType, GraphEdge, GraphMetrics, GraphNode


class GraphAnalyzer:
    """Analyzes dependency graphs to compute degrees, metrics, and cycle diagnostics."""

    @staticmethod
    def calculate_metrics(nodes: List[GraphNode], edges: List[GraphEdge]) -> GraphMetrics:
        """Compute degree metrics, structural distributions, and isolation counts."""
        node_counts: Dict[str, int] = defaultdict(int)
        for n in nodes:
            kind_str = n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type)
            node_counts[kind_str] += 1

        edge_counts: Dict[str, int] = defaultdict(int)
        in_degrees: Dict[str, int] = {n.id: 0 for n in nodes}
        out_degrees: Dict[str, int] = {n.id: 0 for n in nodes}

        for e in edges:
            kind_str = e.edge_type.value if hasattr(e.edge_type, "value") else str(e.edge_type)
            edge_counts[kind_str] += 1

            if e.source_id in out_degrees:
                out_degrees[e.source_id] += 1
            else:
                out_degrees[e.source_id] = 1

            if e.target_id in in_degrees:
                in_degrees[e.target_id] += 1
            else:
                in_degrees[e.target_id] = 1

        isolated_count = sum(
            1 for n in nodes if in_degrees.get(n.id, 0) == 0 and out_degrees.get(n.id, 0) == 0
        )

        return GraphMetrics(
            total_nodes=len(nodes),
            total_edges=len(edges),
            node_counts_by_type=dict(sorted(node_counts.items())),
            edge_counts_by_type=dict(sorted(edge_counts.items())),
            in_degrees=in_degrees,
            out_degrees=out_degrees,
            isolated_nodes_count=isolated_count,
        )

    @staticmethod
    def detect_cycles(
        edges: List[GraphEdge],
        edge_types: Optional[Set[EdgeType]] = None,
    ) -> List[List[str]]:
        """Detect circular dependencies deterministically using depth-first search.

        Filters edges by type (defaults to EdgeType.IMPORTS).
        Normalizes and deduplicates cycles so that cycle rotations map to a unique canonical form.
        """
        allowed_types = edge_types or {EdgeType.IMPORTS}

        adj: Dict[str, List[str]] = defaultdict(list)
        for e in edges:
            if e.edge_type in allowed_types:
                adj[e.source_id].append(e.target_id)

        # Sort adjacencies for deterministic traversal
        for u in adj:
            adj[u].sort()

        all_nodes = sorted(adj.keys())

        visited: Set[str] = set()
        rec_stack: Dict[str, int] = {}  # node -> index in current path
        current_path: List[str] = []
        unique_cycles: Set[Tuple[str, ...]] = set()

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack[node] = len(current_path)
            current_path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor in rec_stack:
                    # Found a cycle from neighbor to node and back
                    cycle_start_idx = rec_stack[neighbor]
                    raw_cycle_body = current_path[cycle_start_idx:]
                    canonical_cycle = GraphAnalyzer._canonicalize_cycle(raw_cycle_body)
                    unique_cycles.add(canonical_cycle)
                elif neighbor not in visited:
                    dfs(neighbor)

            current_path.pop()
            del rec_stack[node]

        for n in all_nodes:
            if n not in visited:
                dfs(n)

        # Convert canonical cycles back to closed path lists [A, B, C, A]
        result: List[List[str]] = []
        for c in sorted(unique_cycles):
            closed_cycle = list(c) + [c[0]]
            result.append(closed_cycle)

        return result

    @staticmethod
    def _canonicalize_cycle(cycle_body: List[str]) -> Tuple[str, ...]:
        """Normalize a cycle path to its lexicographically smallest rotation."""
        if not cycle_body:
            return ()
        n = len(cycle_body)
        rotations = [tuple(cycle_body[i:] + cycle_body[:i]) for i in range(n)]
        return min(rotations)
