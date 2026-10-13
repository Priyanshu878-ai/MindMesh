'use client';

import React from 'react';
import {
  Edge3D,
  Node3D,
} from '../../types/graph';
import {
  EDGE_TYPE_COLORS,
  NODE_TYPE_COLORS,
} from '../../lib/graph-layout';

export interface NodeInspectorProps {
  node: Node3D | null;
  edges: Edge3D[];
  nodeMap: Map<string, Node3D>;
  inDegree?: number;
  outDegree?: number;
  onSelectNode: (node: Node3D | null) => void;
  onClose: () => void;
  className?: string;
}

export function NodeInspector({
  node,
  edges,
  nodeMap,
  inDegree,
  outDegree,
  onSelectNode,
  onClose,
  className = '',
}: NodeInspectorProps) {
  if (!node) return null;

  // Outgoing dependencies: edge.source_id === node.id
  const outgoingConnections = edges
    .filter((e) => e.source_id === node.id)
    .map((e) => ({
      targetNode: nodeMap.get(e.target_id),
      edge: e,
    }))
    .filter((item) => Boolean(item.targetNode));

  // Incoming dependents: edge.target_id === node.id
  const incomingConnections = edges
    .filter((e) => e.target_id === node.id)
    .map((e) => ({
      sourceNode: nodeMap.get(e.source_id),
      edge: e,
    }))
    .filter((item) => Boolean(item.sourceNode));

  const metadata = node.metadata || {};
  const complexity = typeof metadata.complexity === 'number' ? metadata.complexity : undefined;
  const returnType = typeof metadata.return_type === 'string' ? metadata.return_type : undefined;
  const docstring = typeof metadata.docstring === 'string' ? metadata.docstring : undefined;
  const decorators = Array.isArray(metadata.decorators) ? (metadata.decorators as string[]) : [];

  return (
    <div
      className={`flex flex-col w-80 max-h-[85vh] bg-zinc-900/95 border border-zinc-800 rounded-xl shadow-2xl backdrop-blur-md text-zinc-100 overflow-hidden ${className}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-zinc-800 bg-zinc-900/60">
        <div className="flex flex-col gap-1 min-w-0 pr-2">
          <div className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: NODE_TYPE_COLORS[node.node_type] || '#94a3b8' }}
            />
            <h3 className="font-bold text-sm text-zinc-50 truncate" title={node.name}>
              {node.name}
            </h3>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-400">
            <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700/60 uppercase text-[10px] font-mono">
              {node.node_type}
            </span>
            {node.inCycle && (
              <span className="px-1.5 py-0.5 rounded bg-red-950 text-red-300 border border-red-500/40 text-[10px] font-medium">
                Cycle
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-zinc-400 hover:text-zinc-200 p-1 rounded hover:bg-zinc-800 transition"
          title="Close Inspector"
        >
          x
        </button>
      </div>

      {/* Scrollable Content Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {/* Location Section */}
        {node.file_path && (
          <div className="space-y-1">
            <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
              File Path
            </span>
            <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80 font-mono text-[11px] break-all text-zinc-300">
              {node.file_path}
              {node.line_number ? `:${node.line_number}` : ''}
            </div>
          </div>
        )}

        {/* Degree Metrics Section */}
        <div className="grid grid-cols-2 gap-2">
          <div className="p-2.5 rounded bg-zinc-950 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-medium">In-Degree</span>
            <span className="text-base font-bold text-zinc-100 font-mono">
              {inDegree ?? incomingConnections.length}
            </span>
          </div>
          <div className="p-2.5 rounded bg-zinc-950 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-medium">Out-Degree</span>
            <span className="text-base font-bold text-zinc-100 font-mono">
              {outDegree ?? outgoingConnections.length}
            </span>
          </div>
        </div>

        {/* Symbol Details (Complexity, Return Type, Decorators) */}
        {(complexity !== undefined || returnType || decorators.length > 0) && (
          <div className="space-y-2 p-2.5 rounded bg-zinc-950 border border-zinc-800/80">
            <span className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider block">
              Symbol Details
            </span>
            {complexity !== undefined && (
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-zinc-400">Cyclomatic Complexity:</span>
                <span className="font-mono text-zinc-200">{complexity}</span>
              </div>
            )}
            {returnType && (
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-zinc-400">Return Type:</span>
                <span className="font-mono text-sky-300">{returnType}</span>
              </div>
            )}
            {decorators.length > 0 && (
              <div className="space-y-1 pt-1">
                <span className="text-zinc-400 text-[11px]">Decorators:</span>
                <div className="flex flex-wrap gap-1">
                  {decorators.map((d, i) => (
                    <span
                      key={i}
                      className="px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-700 text-[10px] font-mono text-emerald-300"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Docstring */}
        {docstring && (
          <div className="space-y-1">
            <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
              Docstring
            </span>
            <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80 text-zinc-300 italic text-[11px] whitespace-pre-wrap max-h-32 overflow-y-auto">
              {docstring}
            </div>
          </div>
        )}

        {/* Outgoing Dependencies (What this node depends on) */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Dependencies ({outgoingConnections.length})</span>
          </span>
          {outgoingConnections.length === 0 ? (
            <p className="text-zinc-500 text-[11px] italic">No outgoing dependencies</p>
          ) : (
            <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
              {outgoingConnections.map(({ targetNode, edge }, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => targetNode && onSelectNode(targetNode)}
                  className="w-full flex items-center justify-between p-1.5 rounded bg-zinc-950 hover:bg-zinc-800 border border-zinc-800/60 hover:border-zinc-700 text-left transition text-[11px] group"
                >
                  <span className="truncate text-zinc-200 group-hover:text-sky-300">
                    {targetNode?.name}
                  </span>
                  <span
                    className="text-[9px] px-1 rounded uppercase font-mono shrink-0 ml-1"
                    style={{ color: EDGE_TYPE_COLORS[edge.edge_type] }}
                  >
                    {edge.edge_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Incoming Dependents (What depends on this node) */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Dependents ({incomingConnections.length})</span>
          </span>
          {incomingConnections.length === 0 ? (
            <p className="text-zinc-500 text-[11px] italic">No incoming dependents</p>
          ) : (
            <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
              {incomingConnections.map(({ sourceNode, edge }, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => sourceNode && onSelectNode(sourceNode)}
                  className="w-full flex items-center justify-between p-1.5 rounded bg-zinc-950 hover:bg-zinc-800 border border-zinc-800/60 hover:border-zinc-700 text-left transition text-[11px] group"
                >
                  <span className="truncate text-zinc-200 group-hover:text-sky-300">
                    {sourceNode?.name}
                  </span>
                  <span
                    className="text-[9px] px-1 rounded uppercase font-mono shrink-0 ml-1"
                    style={{ color: EDGE_TYPE_COLORS[edge.edge_type] }}
                  >
                    {edge.edge_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default NodeInspector;
