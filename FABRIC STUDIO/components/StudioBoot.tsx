'use client';

import { useEffect } from 'react';
import { useStudio } from '@/store/studio';

/**
 * Rehydrates the persisted store after mount -- the first client render has to
 * match the server render, so persistence is deliberately not automatic.
 *
 * An in-flight prediction id survives the refresh: usePrediction picks the job
 * back up rather than orphaning it.
 */
export function StudioBoot() {
  useEffect(() => {
    let cancelled = false;

    void useStudio.persist.rehydrate()?.then?.(() => {
      if (cancelled) return;
      const state = useStudio.getState();
      state.seedIfEmpty();
      // A session saved under an older prompt template picks up the new text,
      // unless the user has taken the prompt over.
      state.refreshPrompt();
      state.markHydrated();

      if (state.prediction) {
        state.pushToast({
          tone: 'info',
          message: 'Resuming your last generation',
          detail: `Prediction ${state.prediction.id.slice(0, 12)}`,
        });
      }
    });

    // rehydrate() resolves synchronously when storage is empty on some engines.
    const timer = setTimeout(() => {
      if (!cancelled && !useStudio.getState().hydrated) {
        useStudio.getState().seedIfEmpty();
        useStudio.getState().refreshPrompt();
        useStudio.getState().markHydrated();
      }
    }, 60);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return null;
}
