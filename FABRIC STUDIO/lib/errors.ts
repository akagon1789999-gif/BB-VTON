/**
 * One error shape for the whole app. Every failure that reaches the UI carries
 * a plain-language `message` and, where one exists, a concrete `fix`.
 */

export type StudioErrorCode =
  | 'InputValidationError'
  | 'InsufficientCredits'
  | 'RateLimited'
  | 'Timeout'
  | 'NetworkError'
  | 'Unauthorized'
  | 'ContentModerationError'
  | 'PipelineError'
  | 'StorageError'
  | 'Unknown';

export interface StudioErrorPayload {
  code: StudioErrorCode;
  message: string;
  fix?: string;
  /** Kept so the UI can offer "Check again" instead of forcing a re-run. */
  predictionId?: string;
  retryable: boolean;
  /** Seconds to wait before an automatic retry, when the server told us. */
  retryAfter?: number;
}

export class StudioError extends Error {
  readonly code: StudioErrorCode;
  readonly fix?: string;
  readonly httpStatus: number;
  readonly retryable: boolean;
  readonly retryAfter?: number;
  readonly predictionId?: string;

  constructor(init: {
    code: StudioErrorCode;
    message: string;
    fix?: string;
    httpStatus?: number;
    retryable?: boolean;
    retryAfter?: number;
    predictionId?: string;
  }) {
    super(init.message);
    this.name = 'StudioError';
    this.code = init.code;
    this.fix = init.fix;
    this.httpStatus = init.httpStatus ?? 400;
    this.retryable = init.retryable ?? false;
    this.retryAfter = init.retryAfter;
    this.predictionId = init.predictionId;
  }

  toPayload(): StudioErrorPayload {
    return {
      code: this.code,
      message: this.message,
      fix: this.fix,
      retryable: this.retryable,
      retryAfter: this.retryAfter,
      predictionId: this.predictionId,
    };
  }
}

/** Turn anything thrown into something a person can act on. */
export function toStudioError(err: unknown): StudioError {
  if (err instanceof StudioError) return err;
  if (err instanceof Error) {
    const isNetwork =
      err.name === 'AbortError' ||
      /fetch failed|ECONNRESET|ENOTFOUND|ETIMEDOUT|socket hang up/i.test(err.message);
    if (isNetwork) {
      return new StudioError({
        code: 'NetworkError',
        message: 'The connection to FASHN dropped.',
        fix: 'Check your network and try again. Your images and settings are kept.',
        httpStatus: 502,
        retryable: true,
      });
    }
    return new StudioError({
      code: 'Unknown',
      message: err.message || 'Something went wrong.',
      httpStatus: 500,
      retryable: true,
    });
  }
  return new StudioError({
    code: 'Unknown',
    message: 'Something went wrong.',
    httpStatus: 500,
    retryable: true,
  });
}

const BYTES_PER_MIB = 1024 * 1024;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < BYTES_PER_MIB) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / BYTES_PER_MIB).toFixed(1)} MB`;
}
