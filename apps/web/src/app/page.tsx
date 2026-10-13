'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { fetchProjects, ProjectSummary } from '../services/api';

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [customId, setCustomId] = useState('');

  useEffect(() => {
    fetchProjects()
      .then((data) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-sky-500 selection:text-white">
      {/* Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur-md px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-sky-500 flex items-center justify-center font-bold text-white shadow-md shadow-sky-500/20">
            M
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-white">MindMesh</h1>
            <p className="text-[11px] text-zinc-400">AI Codebase Intelligence & Architecture</p>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-6 py-12 flex flex-col gap-10">
        {/* Hero Section */}
        <div className="space-y-3">
          <h2 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Interactive Codebase Architecture
          </h2>
          <p className="text-sm text-zinc-400 max-w-2xl leading-relaxed">
            Analyze repositories, explore AST-level code intelligence, inspect semantic dependency
            graphs, and visualize software architecture in immersive 3D.
          </p>
        </div>

        {/* Quick Launch by Project ID */}
        <div className="p-6 rounded-2xl bg-zinc-900/80 border border-zinc-800 shadow-xl space-y-4">
          <h3 className="text-sm font-semibold text-zinc-200">
            Explore 3D Architecture by Project UUID
          </h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (customId.trim()) {
                router.push(`/projects/${encodeURIComponent(customId.trim())}/architecture`);
              }
            }}
            className="flex flex-col sm:flex-row gap-2.5 max-w-xl"
          >
            <input
              type="text"
              placeholder="Enter Project UUID (e.g. 550e8400-e29b-41d4-a716-446655440000)"
              value={customId}
              onChange={(e) => setCustomId(e.target.value)}
              className="flex-1 px-3.5 py-2 text-xs bg-zinc-950 border border-zinc-700 rounded-lg text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500 font-mono"
            />
            <button
              type="submit"
              disabled={!customId.trim()}
              className="px-5 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition disabled:opacity-50 shrink-0 shadow-md shadow-sky-600/20"
            >
              Open 3D Graph &rarr;
            </button>
          </form>
        </div>

        {/* Registered Projects List */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-zinc-200">Registered Projects</h3>
            <span className="text-xs text-zinc-500">{projects.length} available</span>
          </div>

          {loading ? (
            <div className="p-8 rounded-xl bg-zinc-900/40 border border-zinc-800 text-center text-xs text-zinc-500">
              Loading projects from backend API...
            </div>
          ) : projects.length === 0 ? (
            <div className="p-8 rounded-xl bg-zinc-900/40 border border-zinc-800 text-center space-y-2">
              <p className="text-xs text-zinc-400">No projects registered yet.</p>
              <p className="text-[11px] text-zinc-500">
                Register projects via the API or specify an existing Project UUID above.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {projects.map((proj) => (
                <div
                  key={proj.id}
                  className="p-5 rounded-xl bg-zinc-900/80 border border-zinc-800 hover:border-zinc-700 transition flex flex-col justify-between gap-4 group"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="font-semibold text-sm text-zinc-100 group-hover:text-sky-300 transition truncate">
                        {proj.name}
                      </h4>
                      <span
                        className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${
                          proj.status === 'indexed'
                            ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-300'
                            : 'bg-amber-950/80 border-amber-500/40 text-amber-300'
                        }`}
                      >
                        {proj.status}
                      </span>
                    </div>
                    {proj.source_url && (
                      <p className="text-xs text-zinc-400 truncate font-mono">
                        {proj.source_url}
                      </p>
                    )}
                    <p className="text-[10px] text-zinc-500 font-mono">ID: {proj.id}</p>
                  </div>

                  <div className="pt-2 border-t border-zinc-800/80 flex items-center justify-between">
                    <span className="text-[11px] text-zinc-500">Type: {proj.source_type}</span>
                    <Link
                      href={`/projects/${proj.id}/architecture`}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-sky-400 hover:text-sky-300 transition"
                    >
                      View 3D Graph &rarr;
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
