'use client';

import type { StudioErrorPayload } from './errors';
import type {
  CreditsResponse,
  GenerateRequest,
  GenerateResponse,
  PredictionResult,
  UploadResponse,
} from './types';

/** Everything thrown at the client is already a StudioErrorPayload. */
export class ApiError extends Error {
  readonly payload: StudioErrorPayload;
  constructor(payload: StudioErrorPayload) {
    super(payload.message);
    this.name = 'ApiError';
    this.payload = payload;
  }
}

async function unwrap<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }

  if (!res.ok) {
    const payload = body as Partial<StudioErrorPayload> | null;
    throw new ApiError({
      code: payload?.code ?? 'Unknown',
      message: payload?.message ?? `Request failed with ${res.status}.`,
      fix: payload?.fix,
      retryable: payload?.retryable ?? res.status >= 500,
      retryAfter: payload?.retryAfter,
      predictionId: payload?.predictionId,
    });
  }

  return body as T;
}

function asApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError({
    code: 'NetworkError',
    message: 'The request never reached the server.',
    fix: 'Check your connection. Nothing you uploaded was lost.',
    retryable: true,
  });
}

export interface UploadOptions {
  slot: 'product' | 'model';
  privacy: boolean;
  lossless?: boolean;
  crop?: { x: number; y: number; width: number; height: number } | null;
  signal?: AbortSignal;
}

export async function uploadImage(file: File, options: UploadOptions): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('slot', options.slot);
  form.append('privacy', String(options.privacy));
  if (options.lossless) form.append('lossless', 'true');
  if (options.crop) form.append('crop', JSON.stringify(options.crop));

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: form,
      signal: options.signal,
    });
    return await unwrap<UploadResponse>(res);
  } catch (err) {
    throw asApiError(err);
  }
}

export async function requestGeneration(body: GenerateRequest): Promise<GenerateResponse> {
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await unwrap<GenerateResponse>(res);
  } catch (err) {
    throw asApiError(err);
  }
}

export async function fetchStatus(id: string, signal?: AbortSignal): Promise<PredictionResult> {
  try {
    const res = await fetch(`/api/status/${encodeURIComponent(id)}`, {
      signal,
      cache: 'no-store',
    });
    return await unwrap<PredictionResult>(res);
  } catch (err) {
    throw asApiError(err);
  }
}

export async function fetchCredits(): Promise<CreditsResponse> {
  try {
    const res = await fetch('/api/credits', { cache: 'no-store' });
    return await unwrap<CreditsResponse>(res);
  } catch (err) {
    throw asApiError(err);
  }
}
