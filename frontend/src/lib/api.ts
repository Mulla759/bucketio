/* The live backend: bucketio/api.py. Same-origin in production (bucketio
   serve); proxied to 127.0.0.1:8080 by the Vite dev server. */

import type {
  Company,
  Contact,
  ContactDetail,
  FetchResult,
  Health,
  ImportResult,
  LookupRecord,
  Report,
} from "./types";

export const FILE_MODE = typeof location !== "undefined" && location.protocol === "file:";

export const FILE_MODE_MESSAGE =
  "This page was opened straight from disk, so the directory cannot reach the bucket. " +
  "Run `bucketio serve` and open http://127.0.0.1:8080/ instead — the demo below still works.";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (FILE_MODE) throw new ApiError(FILE_MODE_MESSAGE, 0);

  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (error) {
    throw new ApiError(`Network error calling ${path}: ${describe(error)}`, 0);
  }

  let text = "";
  try {
    text = await response.text();
  } catch {
    text = "";
  }

  let json: unknown = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = null;
    }
  }

  if (!response.ok) {
    let detail = "";
    if (json && typeof json === "object" && "detail" in json) {
      detail = String((json as { detail: unknown }).detail ?? "");
    }
    if (!detail && text) detail = text.slice(0, 300);
    throw new ApiError(detail || `HTTP ${response.status} ${response.statusText}`.trim(), response.status);
  }

  return json as T;
}

/** Probe the server with a short leash so the offline demo starts fast. */
export async function probeHealth(timeoutMs = 2500): Promise<Health | null> {
  if (FILE_MODE) return null;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request<Health>("/health", { signal: controller.signal });
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

export interface ContactQuery {
  q?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),

  contacts: (query: ContactQuery = {}) => {
    const params = new URLSearchParams();
    if (query.q) params.set("q", query.q);
    if (query.status) params.set("status", query.status);
    params.set("limit", String(query.limit ?? 500));
    params.set("offset", String(query.offset ?? 0));
    return request<{ items: Contact[]; total: number }>(`/api/contacts?${params.toString()}`);
  },

  contact: (id: number) =>
    request<{ contact: ContactDetail; lookups: LookupRecord[] }>(`/api/contacts/${encodeURIComponent(id)}`),

  companies: (limit = 500) =>
    request<{ items: Company[]; total: number }>(`/api/companies?limit=${encodeURIComponent(limit)}`),

  report: (since?: string) =>
    request<Report>(`/api/report${since ? `?since=${encodeURIComponent(since)}` : ""}`),

  fetchPerson: (name: string, company: string, force = false) =>
    request<FetchResult>("/api/fetch", {
      method: "POST",
      body: JSON.stringify({ name, company, force }),
    }),

  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportResult>("/api/import", { method: "POST", body: form });
  },

  exportUrl: "/api/export",
};
