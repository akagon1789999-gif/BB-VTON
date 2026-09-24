'use client';

import { createContext, useContext, type ReactNode } from 'react';
import { usePredictionEngine } from '@/hooks/usePrediction';

interface PredictionContextValue {
  checking: boolean;
  reconnecting: boolean;
  checkAgain: () => Promise<void>;
}

const PredictionContext = createContext<PredictionContextValue>({
  checking: false,
  reconnecting: false,
  checkAgain: async () => {},
});

/** Runs the single polling loop for the app and shares its state downward. */
export function PredictionProvider({ children }: { children: ReactNode }) {
  const engine = usePredictionEngine();
  return <PredictionContext.Provider value={engine}>{children}</PredictionContext.Provider>;
}

export function usePrediction(): PredictionContextValue {
  return useContext(PredictionContext);
}
