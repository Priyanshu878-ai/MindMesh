'use client';

import React from 'react';
import {
  EdgeType,
  GraphFilterOptions,
  GraphMetrics,
  NodeType,
} from '../../types/graph';
import {
  EDGE_TYPE_COLORS,
  NODE_TYPE_COLORS,
} from '../../lib/graph-layout';

export interface GraphHUDProps {
  projectName?: string;
  projectStatus?: string;
  metrics?: GraphMetrics;
  cyclesCount?: number;
  filters: GraphFilterOptions;
  onFiltersChange: (newFilters: GraphFilterOptions) => void;
  className?: string;
}

const ALL_NODE_TYPES: { type: NodeType; label: string }[] = [
  { type: 'file', label: 'File' },
  { type: 'class', label: 'Class' },
  { type: 'function', label: 'Function' },
  { type: 'method', label: 'Method' },
  { type: 'external_package', label: 'External' },
];

const ALL_EDGE_TYPES: { type: EdgeType; label: string }[] = [
  { type: 'imports', label: 'Imports' },
  { type: 'contains', label: 'Contains' },
  { type: 'inherits_from', label: 'Inherits' },
  { type: 'calls_or_references', label: 'References' },
];

export function GraphHUD({
  projectName,
  projectStatus,
  metrics,
  cyclesCount = 0,
  filters,
  onFiltersChange,
  className = '',
}: GraphHUDProps) {
  const visibleNodeTypes = filters.visibleNodeTypes;
  const visibleEdgeTypes = filters.visibleEdgeTypes;
  const cyclesOnly = Boolean(filters.highlightCyclesOnly);

  const toggleNodeType = (type: NodeType) => {
    const current = visibleNodeTypes
      ? new Set(visibleNodeTypes)
      : new Set(ALL_NODE_TYPES.map((n) => n.type));

    if (current.has(type)) {
      current.delete(type);
    } else {
      current.add(type);
    }

    onFiltersChange({
      ...filters,
      visibleNodeTypes: current,
    });
  };

  const toggleEdgeType = (type: EdgeType) => {
    const current = visibleEdgeTypes
      ? new Set(visibleEdgeTypes)
      : new Set(ALL_EDGE_TYPES.map((e) => e.type));

    if (current.has(type)) {
      current.delete(type);
    } else {
      current.add(type);
    }

    onFiltersChange({
      ...filters,
      visibleEdgeTypes: current,
    });
  };

  const toggleCyclesOnly = () => {
    onFiltersChange({
      ...filters,
      highlightCyclesOnly: !cyclesOnly,
    });
  };

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFiltersChange({
      ...filters,
      searchQuery: e.target.value,
    });
  };

  const resetAllFilters = () => {
    onFiltersChange({
      visibleNodeTypes: undefined,
      visibleEdgeTypes: undefined,
      searchQuery: '',
      highlightCyclesOnly: false,
    });
  };

  const isNodeTypeActive = (type: NodeType) => {
    return !visibleNodeTypes || visibleNodeTypes.has(type);
  };

  const isEdgeTypeActive = (type: EdgeType) => {
    return !visibleEdgeTypes || visibleEdgeTypes.has(type);
  };

  return (
    <div
      className={`flex flex-col gap-3 p-4 bg-zinc-900/90 border border-zinc-800 rounded-xl shadow-2xl backdrop-blur-md text-zinc-100 ${className}`}
    >
      {/* Top Header Row */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="font-bold text-base tracking-tight text-zinc-50">
            {projectName || 'Architecture Graph'}
          </span>
          {projectStatus && (
            <span
              className={`text-[11px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border ${
                projectStatus === 'indexed'
                  ? 'bg-emerald-950/80 border-emerald-500/30 text-emerald-300'
                  : 'bg-amber-950/80 border-amber-500/30 text-amber-300'
              }`}
            >
              {projectStatus}
            </span>
          )}
        </div>

        {/* Metrics Overview Badges */}
        {metrics && (
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded bg-zinc-800 text-zinc-300 border border-zinc-700/60 font-mono">
              Nodes: <strong className="text-zinc-100">{metrics.total_nodes}</strong>
            </span>
            <span className="px-2 py-1 rounded bg-zinc-800 text-zinc-300 border border-zinc-700/60 font-mono">
              Edges: <strong className="text-zinc-100">{metrics.total_edges}</strong>
            </span>
            {cyclesCount > 0 ? (
              <span className="px-2 py-1 rounded bg-red-950/80 text-red-300 border border-red-500/40 font-mono font-medium">
                Cycles: <strong>{cyclesCount}</strong>
              </span>
            ) : (
              <span className="px-2 py-1 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60 font-mono">
                Acyclic
              </span>
            )}
          </div>
        )}
      </div>

      {/* Search and Action Bar */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search nodes by symbol or path..."
            value={filters.searchQuery || ''}
            onChange={handleSearchChange}
            className="w-full pl-3 pr-8 py-1.5 text-xs bg-zinc-950 border border-zinc-700 rounded-lg text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 transition"
          />
          {filters.searchQuery && (
            <button
              type="button"
              onClick={() => onFiltersChange({ ...filters, searchQuery: '' })}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-200 text-xs"
              title="Clear search"
            >
              x
            </button>
          )}
        </div>

        {/* Cycle Isolation Toggle */}
        <button
          type="button"
          onClick={toggleCyclesOnly}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
            cyclesOnly
              ? 'bg-red-600 text-white border-red-500 shadow-sm'
              : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700/80'
          }`}
          title="Isolate circular dependencies"
        >
          <span
            className={`w-2 h-2 rounded-full ${cyclesOnly ? 'bg-white' : 'bg-red-400'}`}
          />
          Cycles Only {cyclesCount > 0 && `(${cyclesCount})`}
        </button>

        {/* Reset Filters */}
        <button
          type="button"
          onClick={resetAllFilters}
          className="px-2.5 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 bg-zinc-800/60 hover:bg-zinc-800 rounded-lg border border-zinc-700/60 transition"
          title="Reset all filters"
        >
          Reset
        </button>
      </div>

      {/* Filter Toggles Row */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs pt-1">
        {/* Node Types */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-zinc-400 font-medium mr-1">Nodes:</span>
          {ALL_NODE_TYPES.map(({ type, label }) => {
            const active = isNodeTypeActive(type);
            const color = NODE_TYPE_COLORS[type];
            return (
              <button
                key={type}
                type="button"
                onClick={() => toggleNodeType(type)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border transition ${
                  active
                    ? 'bg-zinc-800 border-zinc-700 text-zinc-100'
                    : 'bg-zinc-950 border-zinc-800 text-zinc-500 opacity-60'
                }`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                {label}
              </button>
            );
          })}
        </div>

        {/* Edge Types */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-zinc-400 font-medium mr-1">Edges:</span>
          {ALL_EDGE_TYPES.map(({ type, label }) => {
            const active = isEdgeTypeActive(type);
            const color = EDGE_TYPE_COLORS[type];
            return (
              <button
                key={type}
                type="button"
                onClick={() => toggleEdgeType(type)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border transition ${
                  active
                    ? 'bg-zinc-800 border-zinc-700 text-zinc-100'
                    : 'bg-zinc-950 border-zinc-800 text-zinc-500 opacity-60'
                }`}
              >
                <span
                  className="w-2 h-0.5 rounded shrink-0"
                  style={{ backgroundColor: color }}
                />
                {label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default GraphHUD;
