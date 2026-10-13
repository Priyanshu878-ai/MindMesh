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
