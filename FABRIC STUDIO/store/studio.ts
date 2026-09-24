'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { creditCost, expectedSeconds } from '@/lib/credits';
import type { StudioErrorPayload } from '@/lib/errors';
import { defaultPromptFor } from '@/lib/prompts';
import { seedHistory } from '@/lib/seed';
import { isHeavyDataUri, randomSeed } from '@/lib/utils';
import {
  DEFAULT_PARAMS,
  type FabricScope,
  type FabricTemplate,
  type GarmentType,
  type HistoryEntry,
  type StudioImage,
  type StudioOperation,
  type StudioParams,
} from '@/lib/types';

export type SlotName = 'product' | 'model';

export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SlotState {
  image: StudioImage | null;
  uploading: boolean;
  error: string | null;
  hint: string | null;
  crop: CropRect | null;
}

export interface ActivePrediction {
  id: string;
  operation: StudioOperation;
  startedAt: number;
  expectedSeconds: number;
  creditCost: number;
  params: StudioParams;
  product: StudioImage | null;
  model: StudioImage | null;
  label: string;
  /** Set when polling gave up at 120s. The id is kept so "Check again" works. */
  timedOut: boolean;
}

export interface Toast {
  id: string;
  tone: 'ok' | 'error' | 'info';
  message: string;
  detail?: string;
}

const emptySlot = (): SlotState => ({
  image: null,
  uploading: false,
  error: null,
  hint: null,
  crop: null,
});

interface StudioState {
  params: StudioParams;
  product: SlotState;
  model: SlotState;
  prediction: ActivePrediction | null;
  outputs: string[];
  activeOutput: number;
  error: StudioErrorPayload | null;
  history: HistoryEntry[];
  historyOpen: boolean;
  toasts: Toast[];
  hydrated: boolean;

  setParam: <K extends keyof StudioParams>(key: K, value: StudioParams[K]) => void;
  setGarmentType: (garment: GarmentType) => void;
  setFabricTemplate: (template: FabricTemplate) => void;
  setFabricScope: (scope: FabricScope) => void;
  refreshPrompt: () => void;
  setPrompt: (prompt: string) => void;
  resetPrompt: () => void;
  rerollSeed: () => void;
  applyPreset: (generationMode: StudioParams['generationMode'], resolution: StudioParams['resolution']) => void;

  setSlot: (slot: SlotName, patch: Partial<SlotState>) => void;
  clearSlot: (slot: SlotName) => void;
  swapSlots: () => void;

  startPrediction: (prediction: ActivePrediction) => void;
  markTimedOut: () => void;
  completePrediction: (outputs: string[]) => void;
  failPrediction: (error: StudioErrorPayload) => void;
  clearPrediction: () => void;
  setActiveOutput: (index: number) => void;
  setError: (error: StudioErrorPayload | null) => void;

  setOutputs: (outputs: string[]) => void;
  restore: (entry: HistoryEntry) => void;
  removeHistory: (id: string) => void;
  clearHistory: () => void;
  toggleHistory: (open?: boolean) => void;

  pushToast: (toast: Omit<Toast, 'id'>) => void;
  dismissToast: (id: string) => void;

  markHydrated: () => void;
  seedIfEmpty: () => void;

  currentCost: () => number;
  readiness: () => { ready: boolean; reason: string };
}

/** Strip anything that would blow the localStorage quota. */
function slimImage(image: StudioImage | null): StudioImage | null {
  if (!image) return null;
  const previewUrl = isHeavyDataUri(image.previewUrl) ? '' : image.previewUrl;
  const { dataUri: _dataUri, ...rest } = image;
  return { ...rest, previewUrl };
}

function slimEntry(entry: HistoryEntry): HistoryEntry {
  return {
    ...entry,
    outputs: entry.outputs.filter((o) => !isHeavyDataUri(o)),
    thumbnail: isHeavyDataUri(entry.thumbnail) ? '' : entry.thumbnail,
    productImage: slimImage(entry.productImage),
    modelImage: slimImage(entry.modelImage),
  };
}

const HISTORY_LIMIT = 40;

export const useStudio = create<StudioState>()(
  persist(
    (set, get) => ({
      params: { ...DEFAULT_PARAMS },
      product: emptySlot(),
      model: emptySlot(),
      prediction: null,
      outputs: [],
      activeOutput: 0,
      error: null,
      history: [],
      historyOpen: false,
      toasts: [],
      hydrated: false,

      setParam: (key, value) =>
        set((state) => ({ params: { ...state.params, [key]: value } })),

      setGarmentType: (garmentType) =>
        set((state) => ({
          params: {
            ...state.params,
            garmentType,
            prompt: state.params.promptOverridden
              ? state.params.prompt
              : defaultPromptFor(
                  garmentType,
                  state.params.fabricTemplate,
                  state.params.fabricScope,
                ),
          },
        })),

      setFabricTemplate: (fabricTemplate) =>
        set((state) => ({
          params: {
            ...state.params,
            fabricTemplate,
            // Switching template rewrites the prompt unless the user owns it.
            prompt: state.params.promptOverridden
              ? state.params.prompt
              : defaultPromptFor(
                  state.params.garmentType,
                  fabricTemplate,
                  state.params.fabricScope,
                ),
          },
        })),

      setFabricScope: (fabricScope) =>
        set((state) => ({
          params: {
            ...state.params,
            fabricScope,
            prompt: state.params.promptOverridden
              ? state.params.prompt
              : defaultPromptFor(
                  state.params.garmentType,
                  state.params.fabricTemplate,
                  fabricScope,
                ),
          },
        })),

      setPrompt: (prompt) =>
        set((state) => ({
          params: {
            ...state.params,
            prompt,
            // Once the user edits it in fabric mode, we stop rewriting it.
            promptOverridden:
              prompt !==
              defaultPromptFor(
                state.params.garmentType,
                state.params.fabricTemplate,
                state.params.fabricScope,
              ),
          },
        })),

      resetPrompt: () =>
        set((state) => ({
          params: {
            ...state.params,
            promptOverridden: false,
            prompt: defaultPromptFor(
              state.params.garmentType,
              state.params.fabricTemplate,
              state.params.fabricScope,
            ),
          },
        })),

      /**
       * Recomposes the prompt from the current template, scope and garment
       * type unless the user owns it. Called once after rehydration so a
       * session persisted under an older template picks up the new text
       * instead of silently keeping the stale one.
       */
      refreshPrompt: () =>
        set((state) => {
          if (state.params.promptOverridden) return {};
          const next = defaultPromptFor(
            state.params.garmentType,
            state.params.fabricTemplate,
            state.params.fabricScope,
          );
          return next === state.params.prompt
            ? {}
            : { params: { ...state.params, prompt: next } };
        }),

      rerollSeed: () => set((state) => ({ params: { ...state.params, seed: randomSeed() } })),

      applyPreset: (generationMode, resolution) =>
        set((state) => ({ params: { ...state.params, generationMode, resolution } })),

      setSlot: (slot, patch) => set((state) => ({ [slot]: { ...state[slot], ...patch } }) as Partial<StudioState>),

      clearSlot: (slot) => set(() => ({ [slot]: emptySlot() }) as Partial<StudioState>),

      swapSlots: () => set((state) => ({ product: state.model, model: state.product })),

      startPrediction: (prediction) =>
        set({ prediction, outputs: [], activeOutput: 0, error: null }),

      markTimedOut: () =>
        set((state) => ({
          prediction: state.prediction ? { ...state.prediction, timedOut: true } : null,
          error: {
            code: 'Timeout',
            message: 'This generation passed two minutes without finishing.',
            fix: 'The job may still land. Check again, or start a fresh run.',
            retryable: true,
            predictionId: state.prediction?.id,
          },
        })),

      completePrediction: (outputs) =>
        set((state) => {
          const prediction = state.prediction;
          if (!prediction) return { outputs, activeOutput: 0 };

          const entry: HistoryEntry = {
            id: prediction.id,
            createdAt: Date.now(),
            predictionId: prediction.id,
            operation: prediction.operation,
            status: 'completed',
            outputs,
            thumbnail: outputs[0] ?? '',
            productImage: prediction.product,
            modelImage: prediction.model,
            params: prediction.params,
            creditCost: prediction.creditCost,
            label: prediction.label,
          };

          return {
            outputs,
            activeOutput: 0,
            prediction: null,
            error: null,
            history: [entry, ...state.history.filter((h) => h.id !== entry.id)].slice(
              0,
              HISTORY_LIMIT,
            ),
          };
        }),

      failPrediction: (error) =>
        set((state) => {
          const prediction = state.prediction;
          if (!prediction) return { error };

          const entry: HistoryEntry = {
            id: prediction.id,
            createdAt: Date.now(),
            predictionId: prediction.id,
            operation: prediction.operation,
            status: 'failed',
            outputs: [],
            thumbnail: prediction.product?.previewUrl ?? '',
            productImage: prediction.product,
            modelImage: prediction.model,
            params: prediction.params,
            creditCost: 0,
            label: prediction.label,
            error: error.message,
          };

          return {
            prediction: null,
            error,
            history: [entry, ...state.history.filter((h) => h.id !== entry.id)].slice(
              0,
              HISTORY_LIMIT,
            ),
          };
        }),

      clearPrediction: () => set({ prediction: null }),

      setActiveOutput: (activeOutput) => set({ activeOutput }),

      setError: (error) => set({ error }),

      setOutputs: (outputs) => set({ outputs, activeOutput: 0 }),

      /**
       * Lossless restore: every parameter, both inputs and the result come back
       * exactly as they were. This is the point of the history drawer.
       */
      restore: (entry) =>
        set(() => ({
          // DEFAULT_PARAMS first, so entries written before a field existed
          // still restore into a complete parameter set.
          params: { ...DEFAULT_PARAMS, ...entry.params },
          product: { ...emptySlot(), image: entry.productImage },
          model: { ...emptySlot(), image: entry.modelImage },
          outputs: entry.outputs,
          activeOutput: 0,
          error: null,
          prediction: null,
          historyOpen: false,
        })),

      removeHistory: (id) =>
        set((state) => ({ history: state.history.filter((h) => h.id !== id) })),

      clearHistory: () => set({ history: [] }),

      toggleHistory: (open) =>
        set((state) => ({ historyOpen: open ?? !state.historyOpen })),

      pushToast: (toast) =>
        set((state) => ({
          toasts: [...state.toasts, { ...toast, id: `${Date.now()}-${state.toasts.length}` }],
        })),

      dismissToast: (id) =>
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),

      markHydrated: () => set({ hydrated: true }),

      /** First run gets the three worked examples so the app is demoable. */
      seedIfEmpty: () =>
        set((state) => (state.history.length ? {} : { history: seedHistory() })),

      currentCost: () => {
        const { generationMode, resolution, numImages } = get().params;
        return creditCost(generationMode, resolution, numImages);
      },

      /** The Generate button always says why it is disabled. */
      readiness: () => {
        const state = get();

        if (state.product.uploading || state.model.uploading) {
          return { ready: false, reason: 'Waiting for the upload to finish' };
        }
        if (!state.product.image) {
          return { ready: false, reason: 'Add a fabric swatch' };
        }
        if (!state.model.image) {
          return { ready: false, reason: 'Add a model image' };
        }
        if (state.prediction && !state.prediction.timedOut) {
          return { ready: false, reason: 'A generation is already running' };
        }
        if (state.params.promptOverridden && !state.params.prompt.trim()) {
          return { ready: false, reason: 'Write a prompt or reset it to the template' };
        }
        return {
          ready: true,
          reason: `${expectedSeconds(state.params.generationMode, state.params.resolution, state.params.numImages)}s, about`,
        };
      },
    }),
    {
      name: 'fabric-studio',
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        params: state.params,
        product: { ...state.product, image: slimImage(state.product.image), uploading: false },
        model: { ...state.model, image: slimImage(state.model.image), uploading: false },
        // In-flight prediction ids survive a refresh so jobs resume, not orphan.
        prediction: state.prediction,
        outputs: state.outputs.filter((o) => !isHeavyDataUri(o)),
        history: state.history.map(slimEntry),
      }),
      merge: (persisted, current) => {
        const incoming = (persisted ?? {}) as Partial<StudioState>;
        return {
          ...current,
          ...incoming,
          params: { ...DEFAULT_PARAMS, ...(incoming.params ?? {}) },
          product: { ...emptySlot(), ...(incoming.product ?? {}) },
          model: { ...emptySlot(), ...(incoming.model ?? {}) },
          history: incoming.history ?? current.history,
          toasts: [],
        };
      },
      // Rehydration is driven from <StudioBoot /> after mount, so the first
      // client render matches the server render exactly.
      skipHydration: true,
    },
  ),
);

