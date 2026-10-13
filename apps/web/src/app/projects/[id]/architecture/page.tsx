'use client';

import React, { useEffect, useState, useMemo, useCallback, use } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';

import {
  DependencyGraphResponse,
  GraphFilterOptions,
} from '../../../../types/graph';
import {
  fetchProject,
  fetchProjectGraph,
  triggerIngestion,
  ProjectSummary,
  ApiError,
} from '../../../../services/api';
import {
  transformDependencyGraph,
  filterGraph,
} from '../../../../lib/graph-layout';
import { GraphHUD } from '../../../../components/graph/GraphHUD';
import { NodeInspector } from '../../../../components/graph/NodeInspector';

// Safe dynamic import for Three.js 3D canvas (strictly client-side)
const ArchitectureCanvas3D = dynamic(
  () => import('../../../../components/graph/ArchitectureCanvas3D'),
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-full flex items-center justify-center bg-zinc-950 text-zinc-500 text-sm">
        Initializing WebGL 3D Canvas...
      </div>
    ),
  }
);

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ProjectArchitecturePage({ params }: PageProps) {
  // Unwrap promise params in Next.js 15+
  const resolvedParams = use(params);
  const projectId = resolvedParams.id;

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [graphData, setGraphData] = useState<DependencyGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUnindexed, setIsUnindexed] = useState(false);

  // Filter state
  const [filters, setFilters] = useState<GraphFilterOptions>({});
  // Selected node
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Manual refresh / re-fetch callback
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setIsUnindexed(false);

    try {
      try {
        const projInfo = await fetchProject(projectId);
        setProject(projInfo);
      } catch {
        // Fallback
      }

      const graph = await fetchProjectGraph(projectId);
      setGraphData(graph);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400 && err.detail.toLowerCase().includes('indexed')) {
          setIsUnindexed(true);
        } else {
          setError(err.detail);
        }
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('An unexpected error occurred while loading graph data.');
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // Initial fetch on mount / projectId change without cascading renders
  useEffect(() => {
    let isMounted = true;

    const initialFetch = async () => {
      try {
        try {
          const projInfo = await fetchProject(projectId);
          if (isMounted) setProject(projInfo);
        } catch {
          // ignore
        }
        const graph = await fetchProjectGraph(projectId);
        if (isMounted) {
          setGraphData(graph);
          setError(null);
          setIsUnindexed(false);
        }
      } catch (err) {
        if (!isMounted) return;
        if (err instanceof ApiError) {
          if (err.status === 400 && err.detail.toLowerCase().includes('indexed')) {
            setIsUnindexed(true);
          } else {
            setError(err.detail);
          }
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError('An unexpected error occurred while loading graph data.');
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    initialFetch();

    return () => {
      isMounted = false;
    };
  }, [projectId]);

  // Handle triggering ingestion for unindexed project
  const handleTriggerIngest = async () => {
    setIngesting(true);
    setError(null);
    try {
      await triggerIngestion(projectId);
      // Reload after successful ingestion
      await loadData();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to trigger ingestion.');
      }
    } finally {
      setIngesting(false);
    }
  };

  // Process transformed visualization data
  const vizData = useMemo(() => {
    if (!graphData) return null;
    const transformed = transformDependencyGraph(graphData);
    return filterGraph(transformed, filters);
  }, [graphData, filters]);

  // Active selected Node3D object
  const activeSelectedNode = useMemo(() => {
    if (!vizData || !selectedNodeId) return null;
    return vizData.nodeMap.get(selectedNodeId) || null;
  }, [vizData, selectedNodeId]);

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <nav className="h-12 border-b border-zinc-800/80 bg-zinc-900/80 backdrop-blur-md px-4 flex items-center justify-between z-20 shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-xs text-zinc-400 hover:text-zinc-100 transition flex items-center gap-1 font-medium"
          >
            &larr; MindMesh
          </Link>
          <span className="text-zinc-600">/</span>
          <span className="text-xs font-semibold text-zinc-200 truncate max-w-xs">
            {project?.name || `Project ${projectId.slice(0, 8)}`}
          </span>
          <span className="text-zinc-600">/</span>
          <span className="text-xs text-sky-400 font-medium">3D Architecture</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadData}
            disabled={loading}
            className="px-2.5 py-1 text-xs font-medium rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition border border-zinc-700/60 disabled:opacity-50"
            title="Refresh graph data"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </nav>

      {/* Main Content Area */}
      <div className="relative flex-1 w-full h-full overflow-hidden">
        {/* Loading State */}
        {loading && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-zinc-950/80 backdrop-blur-sm">
            <div className="w-10 h-10 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-sm font-medium text-zinc-300">
              Loading codebase architecture graph...
            </p>
            <p className="text-xs text-zinc-500 mt-1">
              Analyzing AST symbols, module dependencies, and import cycles
            </p>
          </div>
        )}

        {/* Unindexed Project State */}
        {!loading && isUnindexed && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-6 bg-zinc-950">
            <div className="max-w-md w-full p-6 rounded-2xl bg-zinc-900 border border-zinc-800 text-center space-y-4 shadow-2xl">
              <div className="w-12 h-12 mx-auto rounded-full bg-amber-950/80 border border-amber-500/30 flex items-center justify-center text-amber-400 text-xl font-bold">
                !
              </div>
              <h2 className="text-lg font-bold text-zinc-100">Project Not Yet Indexed</h2>
              <p className="text-xs text-zinc-400 leading-relaxed">
                This project must be ingested and indexed before generating the 3D dependency
                architecture graph.
              </p>
              {project?.status && (
                <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80 text-xs font-mono text-zinc-300">
                  Current Status: <span className="text-amber-400 font-semibold">{project.status}</span>
                </div>
              )}
              <div className="pt-2 flex flex-col gap-2">
                <button
                  type="button"
                  onClick={handleTriggerIngest}
                  disabled={ingesting}
                  className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs transition disabled:opacity-50 shadow-md"
                >
                  {ingesting ? 'Scanning & Ingesting Codebase...' : 'Ingest & Index Codebase Now'}
                </button>
                <Link
                  href="/"
                  className="w-full py-2 px-4 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium text-xs transition"
                >
                  Return to Dashboard
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Error State */}
        {!loading && !isUnindexed && error && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-6 bg-zinc-950">
            <div className="max-w-md w-full p-6 rounded-2xl bg-zinc-900 border border-red-900/50 text-center space-y-4 shadow-2xl">
              <div className="w-12 h-12 mx-auto rounded-full bg-red-950/80 border border-red-500/30 flex items-center justify-center text-red-400 text-xl font-bold">
                ✕
              </div>
              <h2 className="text-lg font-bold text-zinc-100">Failed to Load Architecture</h2>
              <p className="text-xs text-red-300/90 leading-relaxed font-mono p-2.5 rounded bg-red-950/40 border border-red-900/30 break-words">
                {error}
              </p>
              <div className="pt-2 flex flex-col gap-2">
                <button
                  type="button"
                  onClick={loadData}
                  className="w-full py-2.5 px-4 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-100 font-medium text-xs transition border border-zinc-700"
                >
                  Retry Loading
                </button>
                <Link
                  href="/"
                  className="w-full py-2 px-4 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-400 font-medium text-xs transition border border-zinc-800"
                >
                  Return to Dashboard
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Empty Graph State */}
        {!loading && !isUnindexed && !error && graphData && graphData.nodes.length === 0 && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-6 bg-zinc-950">
            <div className="max-w-md w-full p-6 rounded-2xl bg-zinc-900 border border-zinc-800 text-center space-y-3">
              <h2 className="text-lg font-bold text-zinc-100">No Codebase Symbols Discovered</h2>
              <p className="text-xs text-zinc-400">
                The codebase scanner did not locate any recognized source files or symbols to build
                a dependency graph.
              </p>
            </div>
          </div>
        )}

        {/* 3D Canvas Visualization and Overlays */}
        {!isUnindexed && !error && graphData && (
          <>
            <ArchitectureCanvas3D
              graphData={graphData}
              filters={filters}
              selectedNodeId={selectedNodeId}
              onSelectNode={(node) => setSelectedNodeId(node ? node.id : null)}
              className="w-full h-full"
            />

            {/* Floating Top-Left HUD Controls */}
            <div className="absolute top-4 left-4 z-10 max-w-xl pointer-events-auto">
              <GraphHUD
                projectName={project?.name}
                projectStatus={project?.status || graphData.status}
                metrics={graphData.metrics}
                cyclesCount={graphData.cycles?.length || 0}
                filters={filters}
                onFiltersChange={setFilters}
              />
            </div>

            {/* Floating Top-Right Node Inspector Panel */}
            {activeSelectedNode && vizData && (
              <div className="absolute top-4 right-4 z-10 pointer-events-auto animate-in fade-in slide-in-from-right-4 duration-150">
                <NodeInspector
                  node={activeSelectedNode}
                  edges={vizData.edges}
                  nodeMap={vizData.nodeMap}
                  inDegree={graphData.metrics?.in_degrees?.[activeSelectedNode.id]}
                  outDegree={graphData.metrics?.out_degrees?.[activeSelectedNode.id]}
                  onSelectNode={(node) => setSelectedNodeId(node ? node.id : null)}
                  onClose={() => setSelectedNodeId(null)}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
