import type { DependencyGraphResponse } from '../types/graph';

export interface ProjectSummary {
  id: string;
  name: string;
  source_type: string;
  source_url?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Fetch the semantic dependency graph for an indexed project.
 *
 * @param projectId UUID of the project
 * @param baseUrl Optional override for API base URL
 * @returns Complete DependencyGraphResponse with nodes, edges, metrics, and cycles
 */
export async function fetchProjectGraph(
  projectId: string,
  baseUrl: string = DEFAULT_API_BASE
): Promise<DependencyGraphResponse> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}/graph`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep default statusText if JSON parsing fails
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}

/**
 * Fetch list of registered codebase projects.
 */
export async function fetchProjects(
  baseUrl: string = DEFAULT_API_BASE
): Promise<ProjectSummary[]> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep statusText fallback
    }
    throw new ApiError(response.status, detail);
  }

  const data = await response.json();
  return Array.isArray(data) ? data : data.items || [];
}

/**
 * Fetch a single project by ID.
 */
export async function fetchProject(
  projectId: string,
  baseUrl: string = DEFAULT_API_BASE
): Promise<ProjectSummary> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep statusText fallback
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}

/**
 * Trigger codebase ingestion for a project.
 */
export async function triggerIngestion(
  projectId: string,
  baseUrl: string = DEFAULT_API_BASE
): Promise<{ status: string }> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}/ingest`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep statusText fallback
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}

/**
 * Upload a ZIP archive containing a codebase project.
 *
 * @param file The ZIP File object to upload
 * @param name Optional custom project name
 * @param autoIngest Whether to immediately ingest & index the codebase (default true)
 * @param baseUrl Optional override for API base URL
 */
export async function uploadZipProject(
  file: File,
  name?: string,
  autoIngest: boolean = true,
  baseUrl: string = DEFAULT_API_BASE
): Promise<ProjectSummary> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects/upload-zip`;

  const formData = new FormData();
  formData.append('file', file);
  if (name && name.trim()) {
    formData.append('name', name.trim());
  }
  formData.append('auto_ingest', String(autoIngest));

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
    },
    body: formData,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep statusText fallback
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}

/**
 * Import a public GitHub repository by URL.
 *
 * @param githubUrl The public GitHub repository URL (e.g. https://github.com/owner/repo)
 * @param name Optional custom project name
 * @param autoIngest Whether to immediately ingest & index the codebase (default true)
 * @param baseUrl Optional override for API base URL
 */
export async function importGithubProject(
  githubUrl: string,
  name?: string,
  autoIngest: boolean = true,
  baseUrl: string = DEFAULT_API_BASE
): Promise<ProjectSummary> {
  const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/projects/import-github`;

  const payload: { url: string; name?: string; auto_ingest: boolean } = {
    url: githubUrl.trim(),
    auto_ingest: autoIngest,
  };
  if (name && name.trim()) {
    payload.name = name.trim();
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // Keep statusText fallback
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}
