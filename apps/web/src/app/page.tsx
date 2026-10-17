'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  fetchProjects,
  importGithubProject,
  uploadZipProject,
  ProjectSummary,
  ApiError,
} from '../services/api';

type ImportTab = 'github' | 'zip';

export default function Home() {
  const router = useRouter();

  // Project listing state
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listRefreshing, setListRefreshing] = useState(false);

  // Quick UUID lookup
  const [customId, setCustomId] = useState('');

  // Active import tab
  const [activeTab, setActiveTab] = useState<ImportTab>('github');

  // GitHub Import form state
  const [githubUrl, setGithubUrl] = useState('');
  const [githubName, setGithubName] = useState('');
  const [githubAutoIngest, setGithubAutoIngest] = useState(true);

  // ZIP Upload form state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [zipName, setZipName] = useState('');
  const [zipAutoIngest, setZipAutoIngest] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Submission & Feedback state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionProgress, setSubmissionProgress] = useState<string | null>(null);
  const [successProject, setSuccessProject] = useState<ProjectSummary | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Load registered projects
  const loadProjects = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setListRefreshing(true);
    }

    try {
      const data = await fetchProjects();
      setProjects(data);
    } catch {
      setProjects([]);
    } finally {
      setListLoading(false);
      setListRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    fetchProjects()
      .then((data) => {
        if (isMounted) setProjects(data);
      })
      .catch(() => {
        if (isMounted) setProjects([]);
      })
      .finally(() => {
        if (isMounted) setListLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Handle GitHub Import
  const handleGithubSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    setErrorMessage(null);
    setSuccessProject(null);

    const trimmedUrl = githubUrl.trim();
    if (!trimmedUrl) {
      setErrorMessage('Please enter a GitHub repository URL.');
      return;
    }

    // Client-side quick validation
    const lower = trimmedUrl.toLowerCase();
    if (!lower.startsWith('https://github.com/') && !lower.startsWith('https://www.github.com/')) {
      setErrorMessage(
        "Please provide a valid public HTTPS GitHub repository URL (e.g. 'https://github.com/owner/repo')."
      );
      return;
    }

    if (trimmedUrl.includes('@')) {
      setErrorMessage('Repository URLs with embedded credentials are not permitted for security.');
      return;
    }

    setIsSubmitting(true);
    setSubmissionProgress(
      githubAutoIngest
        ? 'Cloning repository and executing initial codebase analysis...'
        : 'Cloning repository into managed workspace...'
    );

    try {
      const project = await importGithubProject(
        trimmedUrl,
        githubName.trim() || undefined,
        githubAutoIngest
      );
      setSuccessProject(project);
      setGithubUrl('');
      setGithubName('');
      await loadProjects(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.detail || `Import failed with HTTP status ${err.status}`);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to import GitHub repository. Please check your URL and try again.');
      }
    } finally {
      setIsSubmitting(false);
      setSubmissionProgress(null);
    }
  };

  // Handle ZIP Upload
  const handleZipSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    setErrorMessage(null);
    setSuccessProject(null);

    if (!selectedFile) {
      setErrorMessage('Please select a .zip archive to upload.');
      return;
    }

    if (!selectedFile.name.toLowerCase().endsWith('.zip')) {
      setErrorMessage('Only .zip archive files are supported.');
      return;
    }

    const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
    if (selectedFile.size > MAX_FILE_SIZE) {
      setErrorMessage(
        `Selected archive size exceeds the maximum limit of 50 MB (${(selectedFile.size / (1024 * 1024)).toFixed(1)} MB).`
      );
      return;
    }

    setIsSubmitting(true);
    setSubmissionProgress(
      zipAutoIngest
        ? 'Extracting archive safely and indexing codebase intelligence...'
        : 'Extracting archive into managed workspace...'
    );

    try {
      const project = await uploadZipProject(
        selectedFile,
        zipName.trim() || undefined,
        zipAutoIngest
      );
      setSuccessProject(project);
      setSelectedFile(null);
      setZipName('');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      await loadProjects(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.detail || `Upload failed with HTTP status ${err.status}`);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to upload archive. Please check the ZIP file and try again.');
      }
    } finally {
      setIsSubmitting(false);
      setSubmissionProgress(null);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

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
            Import a public GitHub repository or upload a ZIP archive to analyze AST-level code
            intelligence, inspect semantic dependency graphs, and visualize software architecture in
            interactive 3D.
          </p>
        </div>

        {/* Global Feedback Banners */}
        {errorMessage && (
          <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800/80 text-rose-200 text-xs flex items-start justify-between gap-3 shadow-lg">
            <div className="flex items-start gap-2.5">
              <span className="font-bold text-rose-400 shrink-0">Error:</span>
              <span className="leading-relaxed">{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-400 hover:text-rose-200 font-bold px-1.5 py-0.5 rounded transition"
              title="Dismiss error"
            >
              &times;
            </button>
          </div>
        )}

        {successProject && (
          <div className="p-4 rounded-xl bg-emerald-950/60 border border-emerald-800/80 text-emerald-200 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-lg">
            <div className="space-y-1">
              <p className="font-semibold text-emerald-300">
                Project &ldquo;{successProject.name}&rdquo; imported successfully!
              </p>
              <p className="text-[11px] text-emerald-400/80 font-mono">
                Status: {successProject.status} | ID: {successProject.id}
              </p>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <Link
                href={`/projects/${successProject.id}/architecture`}
                className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-500 hover:bg-emerald-400 text-zinc-950 transition shadow-md shadow-emerald-500/20"
              >
                View 3D Graph &rarr;
              </Link>
              <button
                onClick={() => setSuccessProject(null)}
                className="text-emerald-400 hover:text-emerald-200 font-bold px-1.5 py-0.5 rounded transition"
                title="Dismiss message"
              >
                &times;
              </button>
            </div>
          </div>
        )}

        {/* Repository Ingestion Panel */}
        <div className="rounded-2xl bg-zinc-900/80 border border-zinc-800 shadow-xl overflow-hidden">
          {/* Tabs Navigation */}
          <div className="flex border-b border-zinc-800 bg-zinc-950/50">
            <button
              type="button"
              onClick={() => {
                setActiveTab('github');
                setErrorMessage(null);
              }}
              className={`flex-1 py-3.5 px-6 text-xs font-semibold transition border-b-2 flex items-center justify-center gap-2 ${
                activeTab === 'github'
                  ? 'border-sky-500 text-sky-400 bg-zinc-900/60'
                  : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30'
              }`}
            >
              <span>GitHub Repository</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab('zip');
                setErrorMessage(null);
              }}
              className={`flex-1 py-3.5 px-6 text-xs font-semibold transition border-b-2 flex items-center justify-center gap-2 ${
                activeTab === 'zip'
                  ? 'border-sky-500 text-sky-400 bg-zinc-900/60'
                  : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30'
              }`}
            >
              <span>Upload ZIP Archive</span>
            </button>
          </div>

          <div className="p-6">
            {/* GitHub Import Form */}
            {activeTab === 'github' && (
              <form onSubmit={handleGithubSubmit} className="space-y-4">
                <div className="space-y-1">
                  <label htmlFor="github-url-input" className="block text-xs font-medium text-zinc-300">
                    GitHub Repository URL <span className="text-rose-400">*</span>
                  </label>
                  <input
                    id="github-url-input"
                    type="url"
                    placeholder="https://github.com/pallets/flask"
                    value={githubUrl}
                    onChange={(e) => setGithubUrl(e.target.value)}
                    disabled={isSubmitting}
                    className="w-full px-3.5 py-2.5 text-xs bg-zinc-950 border border-zinc-700 rounded-lg text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500 font-mono disabled:opacity-50"
                  />
                  <p className="text-[11px] text-zinc-500">
                    Public HTTPS repository URL on github.com (e.g. https://github.com/owner/repo)
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-end">
                  <div className="space-y-1">
                    <label htmlFor="github-name-input" className="block text-xs font-medium text-zinc-300">
                      Project Name <span className="text-zinc-500">(Optional)</span>
                    </label>
                    <input
                      id="github-name-input"
                      type="text"
                      placeholder="Custom project display name"
                      value={githubName}
                      onChange={(e) => setGithubName(e.target.value)}
                      disabled={isSubmitting}
                      className="w-full px-3.5 py-2.5 text-xs bg-zinc-950 border border-zinc-700 rounded-lg text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:opacity-50"
                    />
                  </div>

                  <div className="flex items-center gap-2 pb-2">
                    <input
                      type="checkbox"
                      id="github-auto-ingest"
                      checked={githubAutoIngest}
                      onChange={(e) => setGithubAutoIngest(e.target.checked)}
                      disabled={isSubmitting}
                      className="rounded border-zinc-700 bg-zinc-950 text-sky-500 focus:ring-sky-500 w-4 h-4 cursor-pointer"
                    />
                    <label
                      htmlFor="github-auto-ingest"
                      className="text-xs text-zinc-400 select-none cursor-pointer"
                    >
                      Automatically analyze codebase upon import
                    </label>
                  </div>
                </div>

                <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-3">
                  <div className="text-xs text-zinc-400">
                    {submissionProgress && (
                      <span className="inline-flex items-center gap-2 text-sky-400">
                        <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                        {submissionProgress}
                      </span>
                    )}
                  </div>
                  <button
                    type="submit"
                    disabled={isSubmitting || !githubUrl.trim()}
                    className="w-full sm:w-auto px-6 py-2.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition disabled:opacity-50 shadow-md shadow-sky-600/20 shrink-0"
                  >
                    {isSubmitting ? 'Importing Repository...' : 'Import & Analyze Repository'}
                  </button>
                </div>
              </form>
            )}

            {/* ZIP Upload Form */}
            {activeTab === 'zip' && (
              <form onSubmit={handleZipSubmit} className="space-y-4">
                <div className="space-y-1">
                  <label htmlFor="zip-file-input" className="block text-xs font-medium text-zinc-300">
                    Codebase ZIP Archive <span className="text-rose-400">*</span>
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      id="zip-file-input"
                      ref={fileInputRef}
                      type="file"
                      accept=".zip"
                      onChange={(e) => {
                        const file = e.target.files?.[0] || null;
                        setSelectedFile(file);
                      }}
                      disabled={isSubmitting}
                      className="w-full text-xs text-zinc-400 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-zinc-800 file:text-zinc-200 hover:file:bg-zinc-700 file:cursor-pointer cursor-pointer border border-zinc-700 rounded-lg bg-zinc-950 p-1.5 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:opacity-50"
                    />
                  </div>
                  {selectedFile && (
                    <p className="text-[11px] text-zinc-400">
                      Selected: <span className="font-mono text-zinc-200">{selectedFile.name}</span> (
                      {formatFileSize(selectedFile.size)})
                    </p>
                  )}
                  <p className="text-[11px] text-zinc-500">
                    Maximum compressed archive size: 50 MB
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-end">
                  <div className="space-y-1">
                    <label htmlFor="zip-name-input" className="block text-xs font-medium text-zinc-300">
                      Project Name <span className="text-zinc-500">(Optional)</span>
                    </label>
                    <input
                      id="zip-name-input"
                      type="text"
                      placeholder="Derived from archive name if omitted"
                      value={zipName}
                      onChange={(e) => setZipName(e.target.value)}
                      disabled={isSubmitting}
                      className="w-full px-3.5 py-2.5 text-xs bg-zinc-950 border border-zinc-700 rounded-lg text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:opacity-50"
                    />
                  </div>

                  <div className="flex items-center gap-2 pb-2">
                    <input
                      type="checkbox"
                      id="zip-auto-ingest"
                      checked={zipAutoIngest}
                      onChange={(e) => setZipAutoIngest(e.target.checked)}
                      disabled={isSubmitting}
                      className="rounded border-zinc-700 bg-zinc-950 text-sky-500 focus:ring-sky-500 w-4 h-4 cursor-pointer"
                    />
                    <label
                      htmlFor="zip-auto-ingest"
                      className="text-xs text-zinc-400 select-none cursor-pointer"
                    >
                      Automatically analyze codebase upon extraction
                    </label>
                  </div>
                </div>

                <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-3">
                  <div className="text-xs text-zinc-400">
                    {submissionProgress && (
                      <span className="inline-flex items-center gap-2 text-sky-400">
                        <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                        {submissionProgress}
                      </span>
                    )}
                  </div>
                  <button
                    type="submit"
                    disabled={isSubmitting || !selectedFile}
                    className="w-full sm:w-auto px-6 py-2.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition disabled:opacity-50 shadow-md shadow-sky-600/20 shrink-0"
                  >
                    {isSubmitting ? 'Uploading Archive...' : 'Upload & Analyze Archive'}
                  </button>
                </div>
              </form>
            )}
          </div>
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
            <div>
              <h3 className="text-base font-semibold text-zinc-200">Registered Projects</h3>
              <p className="text-xs text-zinc-500">
                Manage and explore all codebases in MindMesh workspace
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-zinc-500">{projects.length} available</span>
              <button
                type="button"
                onClick={() => loadProjects(true)}
                disabled={listRefreshing}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition disabled:opacity-50 flex items-center gap-1.5"
                title="Refresh project list"
              >
                <span className={`inline-block ${listRefreshing ? 'animate-spin' : ''}`}>&#x21bb;</span>
                <span>Refresh</span>
              </button>
            </div>
          </div>

          {listLoading ? (
            <div className="p-8 rounded-xl bg-zinc-900/40 border border-zinc-800 text-center text-xs text-zinc-500">
              Loading projects from backend API...
            </div>
          ) : projects.length === 0 ? (
            <div className="p-8 rounded-xl bg-zinc-900/40 border border-zinc-800 text-center space-y-2">
              <p className="text-xs text-zinc-400">No projects registered yet.</p>
              <p className="text-[11px] text-zinc-500">
                Import a GitHub repository or upload a ZIP archive above to begin.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {projects.map((proj) => (
                <div
                  key={proj.id}
                  className="p-5 rounded-xl bg-zinc-900/80 border border-zinc-800 hover:border-zinc-700 transition flex flex-col justify-between gap-4 group"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="font-semibold text-sm text-zinc-100 group-hover:text-sky-300 transition truncate">
                        {proj.name}
                      </h4>
                      <span
                        className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border shrink-0 ${
                          proj.status === 'indexed'
                            ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-300'
                            : proj.status === 'ingesting'
                            ? 'bg-sky-950/80 border-sky-500/40 text-sky-300 animate-pulse'
                            : proj.status === 'failed'
                            ? 'bg-rose-950/80 border-rose-500/40 text-rose-300'
                            : 'bg-amber-950/80 border-amber-500/40 text-amber-300'
                        }`}
                      >
                        {proj.status}
                      </span>
                    </div>

                    {proj.source_url && (
                      <p
                        className="text-xs text-zinc-400 truncate font-mono"
                        title={proj.source_url}
                      >
                        {proj.source_url}
                      </p>
                    )}

                    <div className="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
                      <span>ID: {proj.id}</span>
                      <span>{new Date(proj.created_at).toLocaleDateString()}</span>
                    </div>

                    {proj.status !== 'indexed' && (
                      <div className="p-2 rounded bg-amber-950/40 border border-amber-800/40 text-[11px] text-amber-300/90 leading-tight">
                        {proj.status === 'pending'
                          ? 'Codebase not yet analyzed. Click View 3D Graph to trigger indexing.'
                          : proj.status === 'ingesting'
                          ? 'Analysis in progress... Graph will be available shortly.'
                          : 'Codebase analysis failed. Open architecture page to inspect or retry.'}
                      </div>
                    )}
                  </div>

                  <div className="pt-2 border-t border-zinc-800/80 flex items-center justify-between">
                    <span className="text-[11px] text-zinc-500">
                      Type:{' '}
                      <span className="font-semibold text-zinc-400 uppercase text-[10px]">
                        {proj.source_type}
                      </span>
                    </span>
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
