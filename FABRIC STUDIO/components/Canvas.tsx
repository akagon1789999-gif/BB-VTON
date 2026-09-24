'use client';

import { useMemo, useState } from 'react';
import { useGenerate } from '@/hooks/useGenerate';
import { useElapsed } from '@/hooks/usePrediction';
import { usePrediction } from './PredictionProvider';
import { downloadImage } from '@/lib/download';
import { cn, formatClock } from '@/lib/utils';
import { useStudio } from '@/store/studio';
import { IconAlert, IconDownload, IconEdit, IconTrash } from './icons';
import { Button, Modal } from './ui';

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <div aria-hidden className="mb-6 h-24 w-16 border border-thread twill" />
      <h2 className="font-display text-lg font-semibold uppercase tracking-loom text-calico">
        Two images make a bolt
      </h2>
      <p className="mt-3 max-w-[38ch] text-sm leading-relaxed text-lint">
        Add a fabric swatch and a photo of someone already wearing the piece. The cut stays,
        the cloth changes.
      </p>
    </div>
  );
}

function Generating() {
  const prediction = useStudio((s) => s.prediction)!;
  const elapsed = useElapsed(prediction.startedAt, !prediction.timedOut);
  const { reconnecting } = usePrediction();

  const progress = Math.min(0.97, elapsed / Math.max(1, prediction.expectedSeconds));
  const overdue = elapsed > prediction.expectedSeconds * 1.4;

  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-8">
      <div className="relative aspect-[2/3] w-full max-w-[280px] overflow-hidden border border-thread bg-weft twill">
        <div
          className="absolute inset-x-0 bottom-0 bg-[rgb(var(--indigo)/0.16)] transition-[height] duration-1000 ease-linear"
          style={{ height: `${progress * 100}%` }}
        />
        <div className="absolute inset-x-0 top-0 h-[2px] overflow-hidden bg-thread">
          <div className="h-full w-1/3 animate-shuttle bg-selvedge" />
        </div>
      </div>

      <div className="text-center">
        <p className="font-mono text-2xl tabular-nums text-calico">{formatClock(elapsed)}</p>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-loom text-slub">
          {reconnecting
            ? 'Connection dropped, retrying'
            : overdue
              ? `Past the usual ${prediction.expectedSeconds}s, still working`
              : `${prediction.params.generationMode} · ${prediction.params.resolution} · about ${prediction.expectedSeconds}s`}
        </p>
      </div>
    </div>
  );
}

function ErrorPanel() {
  const error = useStudio((s) => s.error)!;
  const setError = useStudio((s) => s.setError);
  const clearPrediction = useStudio((s) => s.clearPrediction);
  const { checkAgain, checking } = usePrediction();
  const { generate } = useGenerate();

  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="w-full max-w-md border border-selvedge/50 bg-warp p-5">
        <div className="flex items-center gap-2 text-selvedge">
          <IconAlert />
          <span className="font-mono text-[10px] uppercase tracking-loom">{error.code}</span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-calico">{error.message}</p>
        {error.fix && <p className="mt-2 text-xs leading-relaxed text-lint">{error.fix}</p>}
        {error.predictionId && (
          <p className="mt-3 font-mono text-[10px] text-slub">id {error.predictionId}</p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {error.code === 'Timeout' && (
            <Button variant="primary" onClick={() => void checkAgain()} disabled={checking}>
              {checking ? 'Checking' : 'Check again'}
            </Button>
          )}
          {error.retryable && error.code !== 'Timeout' && (
            <Button
              variant="primary"
              onClick={() => {
                setError(null);
                clearPrediction();
                void generate();
              }}
            >
              Try again
            </Button>
          )}
          <Button
            variant="quiet"
            onClick={() => {
              setError(null);
              clearPrediction();
            }}
          >
            Dismiss
          </Button>
        </div>

        <p className="mt-4 border-t border-thread pt-3 text-[11px] text-slub">
          Your images and settings are exactly where you left them.
        </p>
      </div>
    </div>
  );
}

function RefineModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const params = useStudio((s) => s.params);
  const setPrompt = useStudio((s) => s.setPrompt);
  const rerollSeed = useStudio((s) => s.rerollSeed);
  const { generate } = useGenerate();
  const cost = useStudio((s) => s.currentCost());
  const [draft, setDraft] = useState(params.prompt);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit and re-run"
      description="Same inputs, new instruction. This spends credits like any other generation."
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setPrompt(draft);
              onClose();
              void generate();
            }}
          >
            Re-run · {cost} cr
          </Button>
        </>
      }
    >
      <label htmlFor="refine-prompt" className="label">
        Prompt
      </label>
      <textarea
        id="refine-prompt"
        rows={4}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="field mt-2 resize-y font-mono text-[11px] leading-relaxed"
      />
      <button
        type="button"
        onClick={rerollSeed}
        className="mt-3 font-mono text-[10px] uppercase tracking-loom text-selvedge hover:underline"
      >
        Re-roll seed ({params.seed})
      </button>
    </Modal>
  );
}

function Result() {
  const outputs = useStudio((s) => s.outputs);
  const activeOutput = useStudio((s) => s.activeOutput);
  const setActiveOutput = useStudio((s) => s.setActiveOutput);
  const setOutputs = useStudio((s) => s.setOutputs);
  const removeHistory = useStudio((s) => s.removeHistory);
  const pushToast = useStudio((s) => s.pushToast);
  const params = useStudio((s) => s.params);
  const [refining, setRefining] = useState(false);

  const current = outputs[Math.min(activeOutput, outputs.length - 1)];
  const fileName = useMemo(
    () => `selvedge-${params.garmentType}-${params.seed}-${activeOutput}.${params.outputFormat}`,
    [activeOutput, params.garmentType, params.outputFormat, params.seed],
  );

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-4 px-6 py-6">
      <div className="relative flex max-h-full min-h-0 items-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={current}
          alt="Generated try-on result"
          style={{ height: 'clamp(220px, calc(100vh - 20rem), 900px)' }}
          className="w-auto max-w-full animate-fade-up border border-thread object-contain"
        />

        {/* Floating rail, pinned to the image edge */}
        <div className="absolute -right-11 top-0 hidden flex-col gap-px border border-thread bg-warp md:flex">
          <button
            type="button"
            onClick={() => setRefining(true)}
            title="Edit and re-run"
            aria-label="Edit and re-run"
            className="p-2.5 text-lint hover:bg-weft hover:text-calico"
          >
            <IconEdit />
          </button>
          <button
            type="button"
            onClick={() =>
              void downloadImage(current, fileName).catch((err: Error) =>
                pushToast({ tone: 'error', message: 'The download failed.', detail: err.message }),
              )
            }
            title="Download"
            aria-label="Download"
            className="p-2.5 text-lint hover:bg-weft hover:text-calico"
          >
            <IconDownload />
          </button>
          <button
            type="button"
            onClick={() => {
              setOutputs([]);
              const latest = useStudio.getState().history[0];
              if (latest && latest.outputs[0] === current) removeHistory(latest.id);
            }}
            title="Delete"
            aria-label="Delete"
            className="p-2.5 text-lint hover:bg-weft hover:text-selvedge"
          >
            <IconTrash />
          </button>
        </div>
      </div>

      {outputs.length > 1 && (
        <div className="flex gap-1" role="tablist" aria-label="Generated images">
          {outputs.map((output, index) => (
            <button
              key={output}
              role="tab"
              aria-selected={index === activeOutput}
              aria-label={`Result ${index + 1}`}
              onClick={() => setActiveOutput(index)}
              className={cn(
                'h-14 w-10 overflow-hidden border',
                index === activeOutput ? 'border-selvedge' : 'border-thread opacity-60',
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={output} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}

      {/* Mobile actions -- the floating rail is desktop-only */}
      <div className="flex gap-2 md:hidden">
        <Button onClick={() => setRefining(true)}>Edit</Button>
        <Button onClick={() => void downloadImage(current, fileName)}>Download</Button>
        <Button onClick={() => setOutputs([])}>Delete</Button>
      </div>

      {/* Remounted each time so the draft starts from the live prompt. */}
      {refining && <RefineModal open onClose={() => setRefining(false)} />}
    </div>
  );
}

export function Canvas() {
  const prediction = useStudio((s) => s.prediction);
  const outputs = useStudio((s) => s.outputs);
  const error = useStudio((s) => s.error);

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden bg-vat">
      {error ? (
        <ErrorPanel />
      ) : prediction && !prediction.timedOut ? (
        <Generating />
      ) : outputs.length > 0 ? (
        <Result />
      ) : (
        <EmptyState />
      )}
    </div>
  );
}
