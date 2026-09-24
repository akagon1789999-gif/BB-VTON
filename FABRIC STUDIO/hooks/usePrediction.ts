'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, fetchStatus } from '@/lib/client-api';
import { useStudio } from '@/store/studio';

const POLL_BASE_MS = 2_000;
const BACKOFF_AFTER_MS = 30_000;
const POLL_CEILING_MS = 10_000;
const HARD_TIMEOUT_MS = 120_000;

/** 2s flat, then exponential once the job passes 30s, capped at 10s. */
export function pollInterval(elapsedMs: number): number {
  if (elapsedMs < BACKOFF_AFTER_MS) return POLL_BASE_MS;
  const step = Math.floor((elapsedMs - BACKOFF_AFTER_MS) / 15_000) + 1;
  return Math.min(POLL_BASE_MS * 2 ** step, POLL_CEILING_MS);
}

/**
 * Drives one in-flight prediction to a terminal state. Mount this exactly once
 * -- <PredictionProvider /> does it and shares the result through context.
 *
 * - Polls on the schedule above, cancels on unmount.
 * - Transient network failures pause and resume; they never fail the job.
 * - At 120s it stops and hands the id back to the UI for "Check again".
 */
export function usePredictionEngine() {
  const prediction = useStudio((s) => s.prediction);
  const completePrediction = useStudio((s) => s.completePrediction);
  const failPrediction = useStudio((s) => s.failPrediction);
  const markTimedOut = useStudio((s) => s.markTimedOut);
  const pushToast = useStudio((s) => s.pushToast);
  const queryClient = useQueryClient();

  const [checking, setChecking] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const settle = useCallback(
    async (id: string, manual: boolean): Promise<'done' | 'pending'> => {
      abort.current?.abort();
      abort.current = new AbortController();

      try {
        const result = await fetchStatus(id, abort.current.signal);
        setReconnecting(false);

        if (result.status === 'completed' && result.output?.length) {
          completePrediction(result.output);
          void queryClient.invalidateQueries({ queryKey: ['credits'] });
          pushToast({ tone: 'ok', message: 'Generated' });
          return 'done';
        }

        if (result.status === 'failed' || result.status === 'canceled') {
          failPrediction({
            code: 'PipelineError',
            message: result.error || 'FASHN could not finish this generation.',
            fix: 'Try a clearer, full-body model image, or re-roll the seed.',
            retryable: true,
            predictionId: id,
          });
          void queryClient.invalidateQueries({ queryKey: ['credits'] });
          return 'done';
        }

        if (manual) {
          pushToast({
            tone: 'info',
            message: 'Still running',
            detail: `FASHN reports "${result.status}".`,
          });
        }
        return 'pending';
      } catch (err) {
        const payload = err instanceof ApiError ? err.payload : null;

        // A dropped connection mid-poll resumes on the next tick.
        if (!payload || payload.retryable) {
          setReconnecting(true);
          return 'pending';
        }

        failPrediction({ ...payload, predictionId: id });
        return 'done';
      }
    },
    [completePrediction, failPrediction, pushToast, queryClient],
  );

  useEffect(() => {
    if (!prediction || prediction.timedOut) return;

    let cancelled = false;
    // Local to this effect instance so a remount can never leave two loops
    // sharing one handle.
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelled) return;

      const elapsed = Date.now() - prediction.startedAt;
      if (elapsed > HARD_TIMEOUT_MS) {
        markTimedOut();
        return;
      }

      const outcome = await settle(prediction.id, false);
      if (cancelled || outcome === 'done') return;

      timer = setTimeout(tick, pollInterval(Date.now() - prediction.startedAt));
    };

    // First poll waits one interval -- the job has not started yet at t=0.
    timer = setTimeout(tick, POLL_BASE_MS);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      abort.current?.abort();
      abort.current = null;
    };
  }, [prediction, markTimedOut, settle]);

  /** "Check again" after a timeout, without spending another generation. */
  const checkAgain = useCallback(async () => {
    const current = useStudio.getState().prediction;
    if (!current) return;
    setChecking(true);
    const outcome = await settle(current.id, true);
    setChecking(false);
    if (outcome === 'pending') {
      useStudio.setState({
        prediction: { ...current, timedOut: false, startedAt: Date.now() },
      });
    }
  }, [settle]);

  return { checking, reconnecting, checkAgain };
}

/** Seconds since a timestamp, ticking once a second while active. */
export function useElapsed(startedAt: number | null | undefined, active: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt || !active) {
      setElapsed(0);
      return;
    }
    setElapsed((Date.now() - startedAt) / 1000);
    const id = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 1_000);
    return () => clearInterval(id);
  }, [startedAt, active]);

  return elapsed;
}
