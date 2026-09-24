'use client';

import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, requestGeneration } from '@/lib/client-api';
import { expectedSeconds } from '@/lib/credits';
import { GARMENT_TYPES, type GenerateRequest, type StudioOperation } from '@/lib/types';
import { useStudio } from '@/store/studio';

function labelFor(state: ReturnType<typeof useStudio.getState>): string {
  const garment =
    GARMENT_TYPES.find((g) => g.value === state.params.garmentType)?.label ?? 'Garment';
  const swatch = state.product.image?.fileName.replace(/\.[a-z0-9]+$/i, '') ?? 'upload';
  return `${garment} in ${swatch}`;
}

export function useGenerate() {
  const queryClient = useQueryClient();

  const generate = useCallback(async () => {
    const state = useStudio.getState();
    const { ready, reason } = state.readiness();
    if (!ready) {
      state.pushToast({ tone: 'info', message: reason });
      return;
    }

    const params = state.params;
    const product = state.product.image;
    const model = state.model.image;

    const body: GenerateRequest = {
      operation: 'tryon',
      params,
      product: product
        ? { key: product.key, url: product.url, dataUri: product.dataUri, fileName: product.fileName }
        : null,
      model: model
        ? { key: model.key, url: model.url, dataUri: model.dataUri, fileName: model.fileName }
        : null,
    };

    try {
      const res = await requestGeneration(body);
      state.startPrediction({
        id: res.predictionId,
        operation: 'tryon',
        startedAt: Date.now(),
        expectedSeconds: expectedSeconds(params.generationMode, params.resolution, params.numImages),
        creditCost: res.creditCost,
        params,
        product,
        model,
        label: labelFor(state),
        timedOut: false,
      });
      void queryClient.invalidateQueries({ queryKey: ['credits'] });
    } catch (err) {
      const payload = err instanceof ApiError ? err.payload : null;
      state.setError(
        payload ?? {
          code: 'Unknown',
          message: 'The generation could not be submitted.',
          retryable: true,
        },
      );
      state.pushToast({
        tone: 'error',
        message: payload?.message ?? 'The generation could not be submitted.',
        detail: payload?.fix,
      });
    }
  }, [queryClient]);

  /** Upscale, video, face swap and background work run on an existing result. */
  const runOperation = useCallback(
    async (
      operation: StudioOperation,
      source: string,
      options: Record<string, string | number | boolean> = {},
      label?: string,
    ) => {
      const state = useStudio.getState();
      if (!source) {
        state.pushToast({ tone: 'info', message: 'Generate a result first.' });
        return;
      }

      try {
        const res = await requestGeneration({
          operation,
          params: state.params,
          source,
          options,
        });
        state.startPrediction({
          id: res.predictionId,
          operation,
          startedAt: Date.now(),
          expectedSeconds: operation === 'image-to-video' ? 90 : 20,
          creditCost: res.creditCost,
          params: state.params,
          product: state.product.image,
          model: state.model.image,
          label: label ?? operation,
          timedOut: false,
        });
        void queryClient.invalidateQueries({ queryKey: ['credits'] });
      } catch (err) {
        const payload = err instanceof ApiError ? err.payload : null;
        state.setError(
          payload ?? { code: 'Unknown', message: 'That operation failed to start.', retryable: true },
        );
        state.pushToast({
          tone: 'error',
          message: payload?.message ?? 'That operation failed to start.',
          detail: payload?.fix,
        });
      }
    },
    [queryClient],
  );

  return { generate, runOperation };
}
