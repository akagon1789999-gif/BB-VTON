import 'server-only';
import { StudioError, toStudioError } from './errors';
import type { GenerationMode, OutputFormat, PredictionResult, PredictionStatus, Resolution } from './types';

/* -------------------------------------------------------------------------- */
/* Model inputs                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Every endpoint parameter lives inside `inputs`. None of these are top-level
 * fields on the request body -- that is the single most common way to get a
 * silently-ignored parameter out of this API.
 */
export interface TryOnMaxInputs {
  /** Required. Garment, accessory, shoes, hat, jewelry or bag. https URL or data URI. */
  product_image: string;
  /** Required. The person. Identity, pose and styling are preserved. */
  model_image: string;
  /** Optional styling nudge, e.g. "tuck in shirt". Defaults to empty. */
  prompt?: string;
  /** 1k ~ 1MP, 2k ~ 4MP, 4k ~ 16MP. Default 1k. */
  resolution?: Resolution;
  /** Omitting this bills as `balanced`. We always send it explicitly. */
  generation_mode?: GenerationMode;
  /** 0 .. 2^32 - 1. Default 42. Same seed + same inputs is reproducible. */
  seed?: number;
  /** 1 .. 4. Multiplies credit cost. */
  num_images?: number;
  output_format?: OutputFormat;
  /** true shortens retention to ~60 min and keeps outputs out of request history. */
  return_base64?: boolean;
}

export interface EditInputs {
  /** The image being edited -- in fabric mode, the person already wearing it. */
  image: string;
  /** The instruction. In fabric mode, an explicit retexture instruction. */
  prompt: string;
  /** Reference image the edit draws from -- the fabric swatch. */
  reference_image?: string;
  resolution?: Resolution;
  generation_mode?: GenerationMode;
  seed?: number;
  num_images?: number;
  output_format?: OutputFormat;
  return_base64?: boolean;
}

export interface ReframeInputs {
  image: string;
  /** Upscale/reframe target. */
  target_aspect_ratio?: '1:1' | '4:3' | '3:4' | '16:9' | '9:16';
  resolution?: Resolution;
  seed?: number;
  output_format?: OutputFormat;
  return_base64?: boolean;
}

export interface ImageToVideoInputs {
  image: string;
  prompt?: string;
  /** Seconds of footage. */
  duration?: 5 | 10;
  resolution?: '480p' | '720p' | '1080p';
  seed?: number;
  return_base64?: boolean;
}

export interface ModelSwapInputs {
  image: string;
  /** Describes the replacement model, e.g. "west african man, 30s, short hair". */
  prompt?: string;
  seed?: number;
  output_format?: OutputFormat;
  return_base64?: boolean;
}

export interface BackgroundChangeInputs {
  image: string;
  prompt: string;
  seed?: number;
  output_format?: OutputFormat;
  return_base64?: boolean;
}

export interface BackgroundRemoveInputs {
  image: string;
  output_format?: OutputFormat;
  return_base64?: boolean;
}

export type FashnModelName =
  | 'tryon-max'
  | 'edit'
  | 'reframe'
  | 'image-to-video'
  | 'model-swap'
  | 'background-change'
  | 'background-remove';

export interface FashnInputMap {
  'tryon-max': TryOnMaxInputs;
  edit: EditInputs;
  reframe: ReframeInputs;
  'image-to-video': ImageToVideoInputs;
  'model-swap': ModelSwapInputs;
  'background-change': BackgroundChangeInputs;
  'background-remove': BackgroundRemoveInputs;
}

export interface RunRequest<M extends FashnModelName = FashnModelName> {
  model_name: M;
  inputs: FashnInputMap[M];
}

export interface RunResponse {
  id: string;
  error: string | null;
}

export interface StatusResponse {
  id: string;
  status: PredictionStatus;
  output: string[] | null;
  error: string | { name?: string; message?: string } | null;
}

export interface CreditBalance {
  total: number;
  subscription: number;
  onDemand: number;
}

/* -------------------------------------------------------------------------- */
/* Client                                                                     */
/* -------------------------------------------------------------------------- */

const DEFAULT_BASE = 'https://api.fashn.ai/v1';
const MAX_ATTEMPTS = 3;

function apiKey(): string {
  const key = process.env.FASHN_API_KEY;
  if (!key) {
    throw new StudioError({
      code: 'Unauthorized',
      message: 'FASHN_API_KEY is not set.',
      fix: 'Copy .env.example to .env.local and add your key from fashn.ai/settings.',
      httpStatus: 500,
    });
  }
  return key;
}

function baseUrl(): string {
  return (process.env.FASHN_API_BASE || DEFAULT_BASE).replace(/\/$/, '');
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Normalise FASHN's several error shapes into one StudioError. */
function mapApiError(status: number, body: unknown, retryAfter?: number): StudioError {
  const raw =
    typeof body === 'object' && body !== null
      ? ((body as Record<string, unknown>).error ?? (body as Record<string, unknown>).detail)
      : body;

  const name =
    typeof raw === 'object' && raw !== null
      ? String((raw as Record<string, unknown>).name ?? '')
      : '';
  const detail =
    typeof raw === 'object' && raw !== null
      ? String((raw as Record<string, unknown>).message ?? '')
      : typeof raw === 'string'
        ? raw
        : '';

  if (status === 401 || status === 403) {
    return new StudioError({
      code: 'Unauthorized',
      message: 'FASHN rejected the API key.',
      fix: 'Check FASHN_API_KEY in .env.local, then restart the dev server.',
      httpStatus: 401,
    });
  }

  if (status === 429) {
    return new StudioError({
      code: 'RateLimited',
      message: 'FASHN is rate limiting this key.',
      fix: 'Retrying automatically.',
      httpStatus: 429,
      retryable: true,
      retryAfter: retryAfter ?? 5,
    });
  }

  if (name === 'InputValidationError' || /validation/i.test(detail)) {
    return new StudioError({
      code: 'InputValidationError',
      message: detail || 'FASHN rejected one of the images.',
      fix: 'Images must be under 30 MB, at least 15 x 15 px, and between 1:16 and 16:1.',
      httpStatus: 422,
    });
  }

  if (/credit/i.test(name) || /credit/i.test(detail)) {
    return new StudioError({
      code: 'InsufficientCredits',
      message: detail || 'Not enough credits for this generation.',
      fix: 'Top up at fashn.ai/billing, or drop the quality preset to lower the cost.',
      httpStatus: 402,
    });
  }

  if (/moderation|nsfw|content/i.test(name)) {
    return new StudioError({
      code: 'ContentModerationError',
      message: detail || 'FASHN flagged one of the images.',
      fix: 'Try a different photo. Full-body, clothed, well-lit images work best.',
      httpStatus: 422,
    });
  }

  if (status >= 500) {
    return new StudioError({
      code: 'PipelineError',
      message: detail || 'FASHN had a server error.',
      fix: 'Retrying automatically.',
      httpStatus: status,
      retryable: true,
    });
  }

  return new StudioError({
    code: 'Unknown',
    message: detail || `FASHN returned ${status}.`,
    httpStatus: status,
  });
}

interface FetchOptions {
  method: 'GET' | 'POST';
  path: string;
  body?: unknown;
  timeoutMs?: number;
}

/** One request with bounded retries on 429 and 5xx. */
async function request<T>({ method, path, body, timeoutMs = 60_000 }: FetchOptions): Promise<T> {
  const url = `${baseUrl()}${path}`;
  let lastError: StudioError | null = null;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${apiKey()}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: 'no-store',
      });

      const text = await res.text();
      let parsed: unknown = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = text;
      }

      if (!res.ok) {
        const retryAfterHeader = res.headers.get('retry-after');
        const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : undefined;
        const err = mapApiError(res.status, parsed, Number.isFinite(retryAfter) ? retryAfter : undefined);
        if (err.retryable && attempt < MAX_ATTEMPTS) {
          lastError = err;
          await sleep((err.retryAfter ?? 2 ** attempt) * 1000);
          continue;
        }
        throw err;
      }

      return parsed as T;
    } catch (err) {
      const studio = toStudioError(err);
      if (studio.retryable && attempt < MAX_ATTEMPTS) {
        lastError = studio;
        await sleep(2 ** attempt * 1000);
        continue;
      }
      throw studio;
    } finally {
      clearTimeout(timer);
    }
  }

  throw lastError ?? new StudioError({ code: 'Unknown', message: 'Request failed.', httpStatus: 500 });
}

/** Strip undefined so we never send a key FASHN would read as an explicit null. */
function compact<T extends object>(obj: T): T {
  return Object.fromEntries(
    Object.entries(obj).filter(([, value]) => value !== undefined),
  ) as T;
}

/** Bare base64 out of privacy mode becomes a data URI the browser can render. */
function asRenderableImage(value: string): string {
  if (/^(https?:|data:)/i.test(value)) return value;
  const mime = value.startsWith('iVBOR') ? 'image/png' : 'image/jpeg';
  return `data:${mime};base64,${value}`;
}

export const fashn = {
  /** POST /v1/run -- submit a job, get a prediction id back. */
  async run<M extends FashnModelName>(
    modelName: M,
    inputs: FashnInputMap[M],
  ): Promise<string> {
    const payload: RunRequest<M> = {
      model_name: modelName,
      inputs: compact(inputs),
    };

    const res = await request<RunResponse>({ method: 'POST', path: '/run', body: payload });

    if (res.error) throw mapApiError(422, { error: res.error });
    if (!res.id) {
      throw new StudioError({
        code: 'Unknown',
        message: 'FASHN accepted the job but returned no prediction id.',
        httpStatus: 502,
        retryable: true,
      });
    }
    return res.id;
  },

  /** GET /v1/status/{id} -- one poll. */
  async status(predictionId: string): Promise<PredictionResult> {
    const res = await request<StatusResponse>({
      method: 'GET',
      path: `/status/${encodeURIComponent(predictionId)}`,
      timeoutMs: 20_000,
    });

    const error =
      res.error == null
        ? null
        : typeof res.error === 'string'
          ? res.error
          : (res.error.message ?? res.error.name ?? 'Generation failed.');

    // `output` is always an array on success -- render all of it.
    const raw = Array.isArray(res.output) ? res.output : res.output ? [res.output] : null;

    return {
      id: res.id ?? predictionId,
      status: res.status ?? 'processing',
      // With return_base64 the entries are bare base64, not data URIs. Make
      // them renderable so privacy mode behaves like every other result.
      output: raw ? raw.map(asRenderableImage) : null,
      error,
    };
  },

  /** GET /v1/credits -- live balance for the header. */
  async credits(): Promise<CreditBalance> {
    const res = await request<Record<string, unknown>>({
      method: 'GET',
      path: '/credits',
      timeoutMs: 15_000,
    });

    const node = (res.credits ?? res) as Record<string, unknown> | number;

    if (typeof node === 'number') {
      return { total: node, subscription: node, onDemand: 0 };
    }

    const subscription = Number(node.subscription ?? 0);
    const onDemand = Number(node.on_demand ?? node.onDemand ?? 0);
    const total = Number(node.total ?? subscription + onDemand);

    return {
      total: Number.isFinite(total) ? total : 0,
      subscription: Number.isFinite(subscription) ? subscription : 0,
      onDemand: Number.isFinite(onDemand) ? onDemand : 0,
    };
  },
};
