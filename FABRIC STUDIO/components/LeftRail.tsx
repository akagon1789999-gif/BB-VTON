'use client';

import { useShallow } from 'zustand/react/shallow';
import { useCredits } from '@/hooks/useCredits';
import { useGenerate } from '@/hooks/useGenerate';
import { QUALITY_PRESETS, expectedSeconds, matchPreset } from '@/lib/credits';
import { GARMENT_TYPES } from '@/lib/types';
import { cn } from '@/lib/utils';
import { useStudio } from '@/store/studio';
import { AdvancedPanel } from './AdvancedPanel';
import { Dropzone } from './Dropzone';
import { IconSparkle } from './icons';
import { Segmented } from './ui';

function GarmentTypeSelect() {
  const garmentType = useStudio((s) => s.params.garmentType);
  const setGarmentType = useStudio((s) => s.setGarmentType);

  return (
    <section className="space-y-2">
      <label htmlFor="garment-type" className="label">
        Garment type
      </label>
      <select
        id="garment-type"
        value={garmentType}
        onChange={(e) => setGarmentType(e.target.value as typeof garmentType)}
        className="field appearance-none font-mono text-[11px]"
      >
        {GARMENT_TYPES.map((type) => (
          <option key={type.value} value={type.value} className="bg-weft">
            {type.label}
          </option>
        ))}
      </select>
      <p className="text-[11px] leading-relaxed text-slub">
        Written into the prompt as the piece to remake in this cloth.
      </p>
    </section>
  );
}

function GenerateBar() {
  const params = useStudio((s) => s.params);
  const cost = useStudio((s) => s.currentCost());
  // readiness() builds a fresh object, so it needs a shallow-compared selector.
  const readiness = useStudio(useShallow((s) => s.readiness()));
  const running = useStudio((s) => Boolean(s.prediction) && !s.prediction?.timedOut);
  const applyPreset = useStudio((s) => s.applyPreset);
  const { generate } = useGenerate();
  const { data: credits } = useCredits();

  const preset = matchPreset(params.generationMode, params.resolution);
  const short = credits ? credits.total < cost : false;
  const seconds = expectedSeconds(params.generationMode, params.resolution, params.numImages);

  return (
    <div className="sticky bottom-0 z-20 space-y-3 border-t border-thread bg-warp/95 px-4 pb-4 pt-3 backdrop-blur lg:static">
      <div className="flex items-baseline justify-between">
        <span className="label">Quality</span>
        <span className="font-mono text-[10px] text-slub">
          {preset ? `~${seconds}s` : `custom · ~${seconds}s`}
        </span>
      </div>

      <Segmented
        ariaLabel="Quality preset"
        value={preset}
        onChange={(id) => {
          const next = QUALITY_PRESETS.find((p) => p.id === id);
          if (next) applyPreset(next.generationMode, next.resolution);
        }}
        options={QUALITY_PRESETS.map((p) => ({ value: p.id, label: p.label, note: p.note }))}
      />

      <button
        type="button"
        onClick={() => void generate()}
        disabled={!readiness.ready}
        className={cn(
          'group flex w-full items-center justify-between gap-3 border px-4 py-3 transition-colors',
          readiness.ready
            ? 'border-selvedge bg-selvedge text-vat hover:bg-[rgb(var(--selvedge)/0.88)]'
            : 'cursor-not-allowed border-thread bg-weft text-slub',
        )}
      >
        <span className="flex items-center gap-2 font-display text-[13px] font-bold uppercase tracking-loom">
          <IconSparkle width={15} height={15} />
          {running ? 'Generating' : 'Generate'}
        </span>
        <span
          className={cn(
            'flex items-center gap-1 border px-1.5 py-1 font-mono text-[10px]',
            readiness.ready ? 'border-vat/30 bg-vat/10' : 'border-thread',
          )}
        >
          {cost}
          <span className="opacity-70">cr</span>
        </span>
      </button>

      <p
        className={cn(
          'text-center font-mono text-[10px]',
          readiness.ready ? 'text-slub' : 'text-lint',
        )}
        aria-live="polite"
      >
        {readiness.ready
          ? short
            ? `You have ${credits?.total} credits. This costs ${cost}.`
            : `${params.generationMode} · ${params.resolution} · ${params.numImages} image${params.numImages > 1 ? 's' : ''}`
          : readiness.reason}
      </p>
    </div>
  );
}

export function LeftRail() {
  return (
    <aside className="flex w-full shrink-0 flex-col border-thread bg-warp/60 lg:w-[360px] lg:border-r">
      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <Dropzone
          slot="product"
          title="Fabric"
          offerCrop
          hintLine="A flat swatch shot square-on, filling the frame. Crop out the table and the room."
        />

        <Dropzone
          slot="model"
          title="Model"
          offerCrop
          hintLine="Someone already wearing the piece you want remade."
        />

        <GarmentTypeSelect />

        <AdvancedPanel />
      </div>

      <GenerateBar />
    </aside>
  );
}
