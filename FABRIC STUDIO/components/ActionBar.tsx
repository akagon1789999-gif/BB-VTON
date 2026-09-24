'use client';

import { useEffect, useRef, useState } from 'react';
import { useGenerate } from '@/hooks/useGenerate';
import { creditCost } from '@/lib/credits';
import { cn } from '@/lib/utils';
import { useStudio } from '@/store/studio';
import { IconFace, IconLayers, IconMore, IconPlay, IconSparkle } from './icons';
import { Button, Modal, Segmented } from './ui';

type Panel = 'upscale' | 'video' | 'swap' | 'background' | null;

function CostNote({ credits, note }: { credits: number; note: string }) {
  return (
    <p className="mt-4 border-t border-thread pt-3 font-mono text-[10px] uppercase tracking-loom text-slub">
      {credits} credits · {note}
    </p>
  );
}

export function ActionBar() {
  const outputs = useStudio((s) => s.outputs);
  const activeOutput = useStudio((s) => s.activeOutput);
  const params = useStudio((s) => s.params);
  const running = useStudio((s) => Boolean(s.prediction) && !s.prediction?.timedOut);
  const { runOperation } = useGenerate();

  const [panel, setPanel] = useState<Panel>(null);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const overflowRef = useRef<HTMLDivElement>(null);

  const source = outputs[Math.min(activeOutput, Math.max(0, outputs.length - 1))] ?? '';
  const disabled = !source || running;

  const [ratio, setRatio] = useState('4:3');
  const [duration, setDuration] = useState('5');
  const [videoPrompt, setVideoPrompt] = useState('the model turns slowly toward the camera');
  const [swapPrompt, setSwapPrompt] = useState('');
  const [backgroundPrompt, setBackgroundPrompt] = useState('a clean seamless studio backdrop');

  useEffect(() => {
    if (!overflowOpen) return;
    const onClick = (event: MouseEvent) => {
      if (!overflowRef.current?.contains(event.target as Node)) setOverflowOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOverflowOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [overflowOpen]);

  const oneShotCost = creditCost(params.generationMode, params.resolution, 1);

  const actions = [
    { id: 'upscale' as const, label: 'Upscale', icon: IconSparkle },
    { id: 'video' as const, label: 'Image to video', icon: IconPlay },
    { id: 'swap' as const, label: 'Swap face', icon: IconFace },
  ];

  return (
    <>
      <div className="flex shrink-0 items-center gap-1 border-t border-thread bg-warp/90 px-3 py-2 backdrop-blur">
        {actions.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            disabled={disabled}
            onClick={() => setPanel(id)}
            title={disabled ? 'Generate a result first' : label}
            className={cn(
              'flex items-center gap-2 border border-transparent px-3 py-2 font-mono text-[10px] uppercase tracking-loom transition-colors',
              disabled
                ? 'cursor-not-allowed text-slub/60'
                : 'text-lint hover:border-thread hover:bg-weft hover:text-calico',
            )}
          >
            <Icon width={14} height={14} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}

        <div className="relative ml-auto" ref={overflowRef}>
          <button
            type="button"
            disabled={disabled}
            aria-haspopup="menu"
            aria-expanded={overflowOpen}
            onClick={() => setOverflowOpen((v) => !v)}
            className={cn(
              'flex items-center gap-2 border border-transparent px-3 py-2 text-lint transition-colors',
              disabled ? 'cursor-not-allowed text-slub/60' : 'hover:border-thread hover:bg-weft hover:text-calico',
            )}
            aria-label="More actions"
          >
            <IconMore />
          </button>

          {overflowOpen && (
            <div
              role="menu"
              className="absolute bottom-full right-0 z-20 mb-1 w-56 border border-thread bg-warp py-1 shadow-xl"
            >
              <button
                role="menuitem"
                type="button"
                onClick={() => {
                  setOverflowOpen(false);
                  setPanel('background');
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-lint hover:bg-weft hover:text-calico"
              >
                <IconLayers width={13} height={13} />
                Change background
              </button>
              <button
                role="menuitem"
                type="button"
                onClick={() => {
                  setOverflowOpen(false);
                  void runOperation('background-remove', source, {}, 'Background removed');
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-lint hover:bg-weft hover:text-calico"
              >
                <IconLayers width={13} height={13} />
                Remove background
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Upscale ------------------------------------------------------ */}
      <Modal
        open={panel === 'upscale'}
        onClose={() => setPanel(null)}
        title="Upscale"
        description="Runs the reframe model over the current result."
        footer={
          <>
            <Button variant="quiet" onClick={() => setPanel(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setPanel(null);
                void runOperation('upscale', source, { target_aspect_ratio: ratio }, 'Upscaled');
              }}
            >
              Upscale · {oneShotCost} cr
            </Button>
          </>
        }
      >
        <span className="label">Aspect ratio</span>
        <div className="mt-2">
          <Segmented
            ariaLabel="Target aspect ratio"
            size="sm"
            value={ratio}
            onChange={setRatio}
            options={[
              { value: '1:1', label: '1:1' },
              { value: '4:3', label: '4:3' },
              { value: '3:4', label: '3:4' },
              { value: '9:16', label: '9:16' },
            ]}
          />
        </div>
        <CostNote credits={oneShotCost} note="nothing is spent until you press upscale" />
      </Modal>

      {/* Image to video ---------------------------------------------- */}
      <Modal
        open={panel === 'video'}
        onClose={() => setPanel(null)}
        title="Image to video"
        description="Animates the current result. Video takes noticeably longer than a still."
        footer={
          <>
            <Button variant="quiet" onClick={() => setPanel(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setPanel(null);
                void runOperation(
                  'image-to-video',
                  source,
                  { prompt: videoPrompt, duration: Number(duration), resolution: '720p' },
                  'Video',
                );
              }}
            >
              Animate · {oneShotCost} cr
            </Button>
          </>
        }
      >
        <label htmlFor="video-prompt" className="label">
          Motion
        </label>
        <textarea
          id="video-prompt"
          rows={3}
          value={videoPrompt}
          onChange={(e) => setVideoPrompt(e.target.value)}
          className="field mt-2 resize-y font-mono text-[11px]"
        />
        <div className="mt-4">
          <span className="label">Duration</span>
          <div className="mt-2">
            <Segmented
              ariaLabel="Duration"
              size="sm"
              value={duration}
              onChange={setDuration}
              options={[
                { value: '5', label: '5s' },
                { value: '10', label: '10s' },
              ]}
            />
          </div>
        </div>
        <CostNote credits={oneShotCost} note="video jobs run around 90 seconds" />
      </Modal>

      {/* Swap face ---------------------------------------------------- */}
      <Modal
        open={panel === 'swap'}
        onClose={() => setPanel(null)}
        title="Swap face"
        description="Replaces the model while keeping the garment, pose and lighting."
        footer={
          <>
            <Button variant="quiet" onClick={() => setPanel(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setPanel(null);
                void runOperation('swap-face', source, { prompt: swapPrompt }, 'Model swapped');
              }}
            >
              Swap · {oneShotCost} cr
            </Button>
          </>
        }
      >
        <label htmlFor="swap-prompt" className="label">
          New model
        </label>
        <input
          id="swap-prompt"
          value={swapPrompt}
          onChange={(e) => setSwapPrompt(e.target.value)}
          placeholder="west african man, late thirties, close-cropped hair"
          className="field mt-2 font-mono text-[11px]"
        />
        <p className="mt-2 text-[11px] text-slub">Leave it empty to let FASHN choose.</p>
        <CostNote credits={oneShotCost} note="one image per run" />
      </Modal>

      {/* Background --------------------------------------------------- */}
      <Modal
        open={panel === 'background'}
        onClose={() => setPanel(null)}
        title="Change background"
        description="Keeps the person and the garment, replaces everything behind them."
        footer={
          <>
            <Button variant="quiet" onClick={() => setPanel(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setPanel(null);
                void runOperation(
                  'background-change',
                  source,
                  { prompt: backgroundPrompt },
                  'Background changed',
                );
              }}
            >
              Replace · {oneShotCost} cr
            </Button>
          </>
        }
      >
        <label htmlFor="bg-prompt" className="label">
          Backdrop
        </label>
        <textarea
          id="bg-prompt"
          rows={3}
          value={backgroundPrompt}
          onChange={(e) => setBackgroundPrompt(e.target.value)}
          className="field mt-2 resize-y font-mono text-[11px]"
        />
        <CostNote credits={oneShotCost} note="nothing is spent until you press replace" />
      </Modal>
    </>
  );
}
