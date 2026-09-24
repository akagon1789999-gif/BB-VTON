import type { GenerationMode, Resolution } from './types';

/**
 * Credit cost matrix. Multiply by num_images.
 *
 *   mode \ res   1k   2k   4k
 *   fast          1    2    3
 *   balanced      2    3    4
 *   quality       3    4    5
 */
const MATRIX: Record<GenerationMode, Record<Resolution, number>> = {
  fast: { '1k': 1, '2k': 2, '4k': 3 },
  balanced: { '1k': 2, '2k': 3, '4k': 4 },
  quality: { '1k': 3, '2k': 4, '4k': 5 },
};

export function creditCost(
  mode: GenerationMode,
  resolution: Resolution,
  numImages = 1,
): number {
  return MATRIX[mode][resolution] * Math.max(1, Math.min(4, numImages));
}

/** Expected wall-clock seconds, used to calibrate the progress readout. */
const LATENCY: Record<GenerationMode, Record<Resolution, number>> = {
  fast: { '1k': 10, '2k': 16, '4k': 24 },
  balanced: { '1k': 16, '2k': 25, '4k': 38 },
  quality: { '1k': 26, '2k': 40, '4k': 55 },
};

export function expectedSeconds(
  mode: GenerationMode,
  resolution: Resolution,
  numImages = 1,
): number {
  const base = LATENCY[mode][resolution];
  // Extra images are batched, not serialised -- they cost roughly 35% each.
  return Math.round(base * (1 + 0.35 * (Math.max(1, numImages) - 1)));
}

/** Preset rungs on the quality control. Advanced can still diverge from these. */
export const QUALITY_PRESETS = [
  {
    id: 'draft',
    label: 'Draft',
    generationMode: 'fast' as GenerationMode,
    resolution: '1k' as Resolution,
    note: '1 MP, about 10s',
  },
  {
    id: 'standard',
    label: 'Standard',
    generationMode: 'balanced' as GenerationMode,
    resolution: '2k' as Resolution,
    note: '4 MP, about 25s',
  },
  {
    id: 'final',
    label: 'Final',
    generationMode: 'quality' as GenerationMode,
    resolution: '4k' as Resolution,
    note: '16 MP, about 55s',
  },
];

export function matchPreset(
  mode: GenerationMode,
  resolution: Resolution,
): string | null {
  const hit = QUALITY_PRESETS.find(
    (p) => p.generationMode === mode && p.resolution === resolution,
  );
  return hit ? hit.id : null;
}
