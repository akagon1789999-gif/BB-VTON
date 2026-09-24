'use client';

import { FABRIC_SCOPES, FABRIC_TEMPLATES, scopeApplies } from '@/lib/prompts';
import { cn } from '@/lib/utils';
import type {
  FabricScope,
  FabricTemplate,
  GenerationMode,
  OutputFormat,
  Resolution,
} from '@/lib/types';
import { useStudio } from '@/store/studio';
import { IconDice, IconLock } from './icons';
import { Disclosure, Segmented, Switch } from './ui';

export function AdvancedPanel() {
  const params = useStudio((s) => s.params);
  const setParam = useStudio((s) => s.setParam);
  const setPrompt = useStudio((s) => s.setPrompt);
  const resetPrompt = useStudio((s) => s.resetPrompt);
  const rerollSeed = useStudio((s) => s.rerollSeed);
  const setFabricTemplate = useStudio((s) => s.setFabricTemplate);
  const setFabricScope = useStudio((s) => s.setFabricScope);

  return (
    <Disclosure
      title="Advanced"
      badge={`seed ${params.seed} · ${params.numImages}×`}
      defaultOpen={false}
    >
      {/* Template ----------------------------------------------------- */}
      <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="label">Template</span>
            <span className="font-mono text-[10px] text-slub">
              {params.prompt.length.toLocaleString()} chars
            </span>
          </div>
          <Segmented
            ariaLabel="Fabric prompt template"
            size="sm"
            value={params.fabricTemplate}
            onChange={(value) => setFabricTemplate(value as FabricTemplate)}
            options={FABRIC_TEMPLATES.map((t) => ({
              value: t.value,
              label: t.label,
              note: t.note,
          }))}
        />
      </div>

      {/* Coverage ----------------------------------------------------- */}
      {!scopeApplies(params.fabricTemplate) && (
        <p className="-mt-2 text-[11px] leading-relaxed text-slub">
          The coordinated brief already remakes every layer, so there is no coverage choice
          here. Pick Structural if you want to change the outer garment alone.
        </p>
      )}

      {scopeApplies(params.fabricTemplate) && (
        <div className="space-y-2">
          <span className="label">Coverage</span>
          <Segmented
            ariaLabel="How much of the outfit the fabric replaces"
            size="sm"
            value={params.fabricScope}
            onChange={(value) => setFabricScope(value as FabricScope)}
            options={FABRIC_SCOPES.map((c) => ({
              value: c.value,
              label: c.label,
              note: c.note,
            }))}
          />
          <p className="text-[11px] leading-relaxed text-slub">
            {params.fabricScope === 'full-set'
              ? 'Cap, outer garment, inner top and trousers are all cut from this cloth, and the embroidery is recoloured to match. Footwear and accessories are left alone.'
              : 'Only the outer garment changes. The cap, inner top, trousers and embroidery keep the colour they have in the model photo.'}
          </p>
        </div>
      )}

      {/* Prompt ------------------------------------------------------- */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label htmlFor="prompt" className="label">
            Prompt
          </label>
          {params.promptOverridden && (
            <button
              type="button"
              onClick={resetPrompt}
              className="font-mono text-[10px] uppercase tracking-loom text-selvedge hover:underline"
            >
              Reset to template
            </button>
          )}
        </div>
        <textarea
          id="prompt"
          value={params.prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={params.fabricTemplate === 'concise' ? 4 : 10}
          placeholder="Composed from the template and garment type"
          className="field resize-y font-mono text-[11px] leading-relaxed"
        />
        <p className="text-[11px] leading-relaxed text-slub">
          {params.promptOverridden
            ? 'You are driving this prompt. The template and garment type no longer rewrite it.'
            : 'Composed from the template and garment type above. Edit it to take over.'}
        </p>
      </div>

      {/* Seed --------------------------------------------------------- */}
      <div className="space-y-2">
        <label htmlFor="seed" className="label">
          Seed
        </label>
        <div className="flex gap-1">
          <input
            id="seed"
            type="number"
            min={0}
            max={4294967295}
            value={params.seed}
            onChange={(e) => {
              const next = Number(e.target.value);
              setParam('seed', Number.isFinite(next) ? Math.max(0, Math.min(4294967295, next)) : 42);
            }}
            className="field font-mono text-[11px]"
          />
          <button
            type="button"
            onClick={rerollSeed}
            title="Re-roll the seed"
            aria-label="Re-roll the seed"
            className="shrink-0 border border-thread bg-weft px-2.5 text-lint hover:border-slub hover:text-calico"
          >
            <IconDice />
          </button>
        </div>
        <p className="text-[11px] text-slub">Same seed and same inputs reproduce the same result.</p>
      </div>

      {/* Image count -------------------------------------------------- */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="label">Images</span>
          <span className="font-mono text-[10px] text-slub">multiplies cost</span>
        </div>
        <Segmented
          ariaLabel="Number of images"
          size="sm"
          value={String(params.numImages)}
          onChange={(value) => setParam('numImages', Number(value))}
          options={[1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n}` }))}
        />
      </div>

      {/* Independent quality axes ------------------------------------- */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <span className="label">Mode</span>
          <Segmented
            ariaLabel="Generation mode"
            size="sm"
            value={params.generationMode}
            onChange={(value) => setParam('generationMode', value as GenerationMode)}
            options={[
              { value: 'fast', label: 'Fast' },
              { value: 'balanced', label: 'Bal' },
              { value: 'quality', label: 'Qual' },
            ]}
          />
        </div>
        <div className="space-y-2">
          <span className="label">Resolution</span>
          <Segmented
            ariaLabel="Resolution"
            size="sm"
            value={params.resolution}
            onChange={(value) => setParam('resolution', value as Resolution)}
            options={[
              { value: '1k', label: '1k' },
              { value: '2k', label: '2k' },
              { value: '4k', label: '4k' },
            ]}
          />
        </div>
      </div>

      {/* Output format ------------------------------------------------ */}
      <div className="space-y-2">
        <span className="label">Output format</span>
        <Segmented
          ariaLabel="Output format"
          size="sm"
          value={params.outputFormat}
          onChange={(value) => setParam('outputFormat', value as OutputFormat)}
          options={[
            { value: 'png', label: 'PNG' },
            { value: 'jpeg', label: 'JPEG' },
          ]}
        />
      </div>

      {/* Privacy ------------------------------------------------------ */}
      <div className={cn('border border-thread p-3', params.privacy && 'selvedge-mark')}>
        <Switch
          checked={params.privacy}
          onChange={(next) => setParam('privacy', next)}
          label="Privacy mode"
          icon={<IconLock width={13} height={13} />}
          description="Images go up as data, results come back as base64, and FASHN keeps them for about 60 minutes instead of storing them in request history."
        />
      </div>
    </Disclosure>
  );
}
