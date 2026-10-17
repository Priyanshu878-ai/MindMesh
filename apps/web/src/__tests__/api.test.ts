import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  ApiError,
  fetchProject,
  fetchProjects,
  importGithubProject,
  triggerIngestion,
  uploadZipProject,
} from '../services/api.ts';

describe('Frontend API Client Service', () => {
  const fakeBaseUrl = 'http://test-api.local';

  it('ApiError creates formatted error with status and detail', () => {
    const err = new ApiError(400, 'Invalid repository URL');
    assert.equal(err.status, 400);
    assert.equal(err.detail, 'Invalid repository URL');
    assert.equal(err.message, 'API Error 400: Invalid repository URL');
    assert.equal(err.name, 'ApiError');
  });

  it('fetchProjects handles paginated object response format', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), 'http://test-api.local/api/v1/projects');
      assert.equal(options?.method, 'GET');
      return {
        ok: true,
        json: async () => ({
          items: [
            { id: '1', name: 'Project 1', source_type: 'local', status: 'indexed', created_at: '', updated_at: '' },
          ],
          total: 1,
        }),
      } as unknown as Response;
    };

    try {
      const projects = await fetchProjects(fakeBaseUrl);
      assert.equal(projects.length, 1);
      assert.equal(projects[0].name, 'Project 1');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('fetchProjects throws ApiError on failure', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ detail: 'Database connection failed' }),
    } as unknown as Response);

    try {
      await assert.rejects(
        async () => fetchProjects(fakeBaseUrl),
        (err: unknown) => err instanceof ApiError && err.status === 500 && err.detail === 'Database connection failed'
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('fetchProject fetches single project by UUID', async () => {
    const originalFetch = globalThis.fetch;
    const testId = '550e8400-e29b-41d4-a716-446655440000';
    globalThis.fetch = async (url) => {
      assert.equal(String(url), `http://test-api.local/api/v1/projects/${testId}`);
      return {
        ok: true,
        json: async () => ({
          id: testId,
          name: 'My Project',
          source_type: 'github',
          source_url: 'https://github.com/foo/bar',
          status: 'indexed',
          created_at: '',
          updated_at: '',
        }),
      } as unknown as Response;
    };

    try {
      const proj = await fetchProject(testId, fakeBaseUrl);
      assert.equal(proj.id, testId);
      assert.equal(proj.name, 'My Project');
      assert.equal(proj.source_type, 'github');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('importGithubProject sends formatted JSON payload and returns ProjectSummary', async () => {
    const originalFetch = globalThis.fetch;
    let recordedBody: Record<string, unknown> | null = null;

    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), 'http://test-api.local/api/v1/projects/import-github');
      assert.equal(options?.method, 'POST');
      assert.equal((options?.headers as Record<string, string>)['Content-Type'], 'application/json');
      recordedBody = JSON.parse(options?.body as string) as Record<string, unknown>;

      return {
        ok: true,
        json: async () => ({
          id: 'gh-uuid-1234',
          name: 'flask',
          source_type: 'github',
          source_url: 'https://github.com/pallets/flask',
          status: 'indexed',
          created_at: '2026-10-18T00:00:00Z',
          updated_at: '2026-10-18T00:00:00Z',
        }),
      } as unknown as Response;
    };

    try {
      const result = await importGithubProject(
        'https://github.com/pallets/flask.git',
        'flask',
        true,
        fakeBaseUrl
      );
      assert.ok(recordedBody !== null);
      const body = recordedBody as Record<string, unknown>;
      assert.equal(body.url, 'https://github.com/pallets/flask.git');
      assert.equal(body.name, 'flask');
      assert.equal(body.auto_ingest, true);
      assert.equal(result.id, 'gh-uuid-1234');
      assert.equal(result.source_type, 'github');
      assert.equal(result.status, 'indexed');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('importGithubProject throws ApiError on validation failure', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      json: async () => ({ detail: 'Unsupported URL scheme' }),
    } as unknown as Response);

    try {
      await assert.rejects(
        async () => importGithubProject('http://insecure.com', undefined, true, fakeBaseUrl),
        (err: unknown) => err instanceof ApiError && err.status === 400 && err.detail === 'Unsupported URL scheme'
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('uploadZipProject sends FormData and returns ProjectSummary', async () => {
    const originalFetch = globalThis.fetch;
    let recordedFormData: FormData | null = null;

    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), 'http://test-api.local/api/v1/projects/upload-zip');
      assert.equal(options?.method, 'POST');
      recordedFormData = options?.body as FormData;

      return {
        ok: true,
        json: async () => ({
          id: 'zip-uuid-5678',
          name: 'My Archive',
          source_type: 'local',
          source_url: '/data/repo/my_archive',
          status: 'indexed',
          created_at: '2026-10-18T00:00:00Z',
          updated_at: '2026-10-18T00:00:00Z',
        }),
      } as unknown as Response;
    };

    try {
      const fakeFile = new File(['dummy zip binary'], 'archive.zip', { type: 'application/zip' });
      const result = await uploadZipProject(fakeFile, 'My Archive', true, fakeBaseUrl);

      assert.ok(recordedFormData);
      assert.equal(result.id, 'zip-uuid-5678');
      assert.equal(result.name, 'My Archive');
      assert.equal(result.status, 'indexed');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('triggerIngestion sends POST to project ingest endpoint', async () => {
    const originalFetch = globalThis.fetch;
    const testId = '12345';
    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), `http://test-api.local/api/v1/projects/${testId}/ingest`);
      assert.equal(options?.method, 'POST');
      return {
        ok: true,
        json: async () => ({ status: 'indexed' }),
      } as unknown as Response;
    };

    try {
      const res = await triggerIngestion(testId, fakeBaseUrl);
      assert.equal(res.status, 'indexed');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
