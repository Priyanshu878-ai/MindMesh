import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  computeDeterministic3DLayout,
  extractCycleElements,
  filterGraph,
  NODE_TYPE_COLORS,
  transformDependencyGraph,
  CYCLE_HIGHLIGHT_COLOR,
} from '../lib/graph-layout.ts';
import type {
  DependencyGraphResponse,
  GraphEdge,
  GraphNode,
} from '../types/graph.ts';
import { ApiError } from '../services/api.ts';

describe('Deterministic 3D Graph Layout & Utilities', () => {
  const sampleNodes: GraphNode[] = [
    {
      id: 'file:app/main.py',
      name: 'main.py',
      node_type: 'file',
      file_path: 'app/main.py',
      line_number: 1,
    },
    {
      id: 'file:app/utils.py',
      name: 'utils.py',
      node_type: 'file',
      file_path: 'app/utils.py',
      line_number: 1,
    },
    {
      id: 'symbol:app/main.py:AppClass',
      name: 'AppClass',
      node_type: 'class',
      file_path: 'app/main.py',
      line_number: 5,
    },
    {
      id: 'symbol:app/main.py:AppClass.run',
      name: 'run',
      node_type: 'method',
      file_path: 'app/main.py',
      line_number: 8,
    },
    {
      id: 'external:pydantic',
      name: 'pydantic',
      node_type: 'external_package',
    },
  ];

  const sampleEdges: GraphEdge[] = [
    {
      source_id: 'file:app/main.py',
      target_id: 'symbol:app/main.py:AppClass',
      edge_type: 'contains',
      weight: 1.0,
    },
    {
      source_id: 'symbol:app/main.py:AppClass',
      target_id: 'symbol:app/main.py:AppClass.run',
      edge_type: 'contains',
      weight: 1.0,
    },
    {
      source_id: 'file:app/main.py',
      target_id: 'file:app/utils.py',
      edge_type: 'imports',
      weight: 1.0,
    },
    {
      source_id: 'file:app/utils.py',
      target_id: 'file:app/main.py',
      edge_type: 'imports',
      weight: 1.0,
    },
    {
      source_id: 'file:app/main.py',
      target_id: 'external:pydantic',
      edge_type: 'imports',
      weight: 1.0,
    },
  ];

  const sampleRawGraph: DependencyGraphResponse = {
    project_id: '11111111-2222-3333-4444-555555555555',
    status: 'indexed',
    nodes: sampleNodes,
    edges: sampleEdges,
    metrics: {
      total_nodes: 5,
      total_edges: 5,
      node_counts_by_type: { file: 2, class: 1, method: 1, external_package: 1 },
      edge_counts_by_type: { contains: 2, imports: 3 },
      in_degrees: {},
      out_degrees: {},
      isolated_nodes_count: 0,
    },
    cycles: [
      ['file:app/main.py', 'file:app/utils.py', 'file:app/main.py'],
    ],
    duration_ms: 12.5,
  };

  it('computes deterministic positions and covers all nodes', () => {
    const layout1 = computeDeterministic3DLayout(sampleNodes, sampleEdges, {
      radius: 200,
      externalRadius: 400,
    });
    const layout2 = computeDeterministic3DLayout(sampleNodes, sampleEdges, {
      radius: 200,
      externalRadius: 400,
    });

    assert.equal(layout1.size, sampleNodes.length);

    for (const node of sampleNodes) {
      assert.ok(layout1.has(node.id));
      const pos1 = layout1.get(node.id)!;
      const pos2 = layout2.get(node.id)!;
      assert.deepEqual(pos1, pos2, `Position for ${node.id} must be strictly deterministic`);
    }

    // External package should be located on outer orbit
    const extPos = layout1.get('external:pydantic')!;
    const filePos = layout1.get('file:app/main.py')!;
    const extDistance = Math.hypot(extPos.x, extPos.z);
    const fileDistance = Math.hypot(filePos.x, filePos.y, filePos.z);

    assert.ok(
      extDistance > fileDistance,
      'External nodes must be positioned further out than internal files'
    );
  });

  it('extracts cycle node and edge sets accurately', () => {
    const cycles = [
      ['node:A', 'node:B', 'node:C', 'node:A'],
    ];

    const { cycleNodeIds, cycleEdgeKeys } = extractCycleElements(cycles);

    assert.equal(cycleNodeIds.size, 3);
    assert.ok(cycleNodeIds.has('node:A'));
    assert.ok(cycleNodeIds.has('node:B'));
    assert.ok(cycleNodeIds.has('node:C'));

    assert.equal(cycleEdgeKeys.size, 3);
    assert.ok(cycleEdgeKeys.has('node:A->node:B'));
    assert.ok(cycleEdgeKeys.has('node:B->node:C'));
    assert.ok(cycleEdgeKeys.has('node:C->node:A'));
  });

  it('transforms raw graph and marks cycle nodes & edges with highlight color', () => {
    const vizData = transformDependencyGraph(sampleRawGraph);

    assert.equal(vizData.nodes.length, 5);
    assert.equal(vizData.edges.length, 5);

    // Cycle nodes should be highlighted
    const mainNode = vizData.nodeMap.get('file:app/main.py')!;
    const utilsNode = vizData.nodeMap.get('file:app/utils.py')!;
    const classNode = vizData.nodeMap.get('symbol:app/main.py:AppClass')!;

    assert.equal(mainNode.inCycle, true);
    assert.equal(mainNode.color, CYCLE_HIGHLIGHT_COLOR);
    assert.equal(utilsNode.inCycle, true);
    assert.equal(utilsNode.color, CYCLE_HIGHLIGHT_COLOR);

    // Non-cycle nodes retain semantic color
    assert.equal(classNode.inCycle, false);
    assert.equal(classNode.color, NODE_TYPE_COLORS.class);

    // Cycle edges
    const cycleEdge = vizData.edges.find(
      (e) => e.source_id === 'file:app/main.py' && e.target_id === 'file:app/utils.py'
    )!;
    assert.equal(cycleEdge.inCycle, true);
    assert.equal(cycleEdge.color, CYCLE_HIGHLIGHT_COLOR);

    const nonCycleEdge = vizData.edges.find(
      (e) => e.source_id === 'file:app/main.py' && e.target_id === 'external:pydantic'
    )!;
    assert.equal(nonCycleEdge.inCycle, false);
  });

  it('filters graph by node types', () => {
    const vizData = transformDependencyGraph(sampleRawGraph);
    const filtered = filterGraph(vizData, {
      visibleNodeTypes: new Set(['file']),
    });

    assert.equal(filtered.nodes.length, 2);
    assert.ok(filtered.nodes.every((n) => n.node_type === 'file'));
    // Only file-to-file edges remain
    assert.equal(filtered.edges.length, 2);
    assert.ok(filtered.edges.every((e) => e.source_id.startsWith('file:') && e.target_id.startsWith('file:')));
  });

  it('filters graph by search query', () => {
    const vizData = transformDependencyGraph(sampleRawGraph);
    const filtered = filterGraph(vizData, {
      searchQuery: 'AppClass',
    });

    const nodeIds = filtered.nodes.map((n) => n.id);
    assert.ok(nodeIds.includes('symbol:app/main.py:AppClass'));
    assert.ok(nodeIds.includes('symbol:app/main.py:AppClass.run'));
    assert.ok(!nodeIds.includes('file:app/utils.py'));
  });

  it('filters graph by cycle isolation mode', () => {
    const vizData = transformDependencyGraph(sampleRawGraph);
    const filtered = filterGraph(vizData, {
      highlightCyclesOnly: true,
    });

    assert.equal(filtered.nodes.length, 2);
    assert.ok(filtered.nodes.every((n) => n.inCycle));
    assert.equal(filtered.edges.length, 2);
    assert.ok(filtered.edges.every((e) => e.inCycle));
  });

  it('ApiError encapsulates HTTP status and detail string', () => {
    const err = new ApiError(400, 'Project must be indexed before generating dependency graph');
    assert.equal(err.status, 400);
    assert.equal(err.detail, 'Project must be indexed before generating dependency graph');
    assert.ok(err.message.includes('API Error 400'));
  });
});
