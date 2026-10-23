/**
 * API client module for ScholarSwarm AI backend communication.
 * Communicates with FastAPI backend over relative /api endpoints proxied via Vite.
 */

import type {
  HealthResponse,
  PipelineEvent,
  ResearchStartResponse,
  SessionRecord,
  SOPDraft,
  VerifiedOpportunity,
} from './types';
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const data = await res.json();
      if (data && typeof data === 'object') {
        errorDetail = data.detail || data.message || JSON.stringify(data);
      }
    } catch {
      // Non-JSON error body
    }
    throw new ApiError(errorDetail || `HTTP error ${res.status}`, res.status);
  }
  return res.json();
}

/** Check backend health and SQLite connection status */
export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health`);
  return handleResponse<HealthResponse>(res);
}

export interface ProfilePreviewResponse {
  name: string | null;
  email: string | null;
  current_degree: string | null;
  cgpa: number | null;
  cgpa_scale: number | null;
  cgpa_source: string | null;
  cgpa_evidence: string | null;
  is_ambiguous: boolean;
  ambiguity_reason: string | null;
  ielts_score: number | null;
  toefl_score: number | null;
  gre_score: number | null;
  work_experience_years: number | null;
  skills: string[];
  warnings: string[];
  document_filename: string | null;
}

/** Extract preview profile data from uploaded resume/transcript for student verification */
export async function extractProfilePreview(formData: FormData): Promise<ProfilePreviewResponse> {
  const res = await fetch(`${API_BASE}/api/profile/extract-preview`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<ProfilePreviewResponse>(res);
}

/** Create research session with documents (FormData) or direct profile (JSON) */
export async function createSession(payload: FormData | object): Promise<SessionRecord> {
  const isFormData = payload instanceof FormData;
  const options: RequestInit = {
    method: 'POST',
    body: isFormData ? payload : JSON.stringify(payload),
    headers: isFormData ? undefined : { 'Content-Type': 'application/json' },
  };

  const res = await fetch(`${API_BASE}/api/sessions`, options);
  return handleResponse<SessionRecord>(res);
}

/** Fetch existing session record and validated StudentProfile */
export async function getSession(sessionId: string): Promise<SessionRecord> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`);
  return handleResponse<SessionRecord>(res);
}

/** Poll chronological pipeline events for live UI progress */
export async function getEvents(sessionId: string, sinceId?: string): Promise<PipelineEvent[]> {
  const query = sinceId ? `?since_id=${encodeURIComponent(sinceId)}` : '';
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/events${query}`);
  return handleResponse<PipelineEvent[]>(res);
}

/** Trigger multi-agent research execution (ORA -> EEVA -> MRA -> ASA) */
export async function startResearch(sessionId: string): Promise<ResearchStartResponse> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/research`, {
    method: 'POST',
  });
  return handleResponse<ResearchStartResponse>(res);
}

/** Retrieve evaluated and ranked scholarship opportunities */
export async function getOpportunities(
  sessionId: string,
  tier?: string,
  resultGroup?: string
): Promise<VerifiedOpportunity[]> {
  const params = new URLSearchParams();
  if (tier) params.append('tier', tier);
  if (resultGroup) params.append('result_group', resultGroup);

  const qs = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/opportunities${qs}`);
  return handleResponse<VerifiedOpportunity[]>(res);
}

/** Retrieve synthesized Statement of Purpose draft and application guidance */
export async function getSop(sessionId: string, opportunityId?: string): Promise<SOPDraft> {
  const qs = opportunityId ? `?opportunity_id=${encodeURIComponent(opportunityId)}` : '';
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/sop${qs}`);
  return handleResponse<SOPDraft>(res);
}
