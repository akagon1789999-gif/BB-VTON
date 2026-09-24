'use client';

import { useEffect } from 'react';
import { GARMENT_TYPES, type HistoryEntry } from '@/lib/types';
import { cn, formatRelative } from '@/lib/utils';
import { useStudio } from '@/store/studio';
import { IconClose, IconHistory, IconTrash } from './icons';

function Entry({ entry }: { entry: HistoryEntry }) {
  const restore = useStudio((s) => s.restore);
  const removeHistory = useStudio((s) => s.removeHistory);
  const pushToast = useStudio((s) => s.pushToast);

  const garment = GARMENT_TYPES.find((g) => g.value === entry.params.garmentType)?.label;
  const failed = entry.status === 'failed';

  return (
    <li className="group relative border border-thread bg-warp">
      <button
        type="button"
        onClick={() => {
          restore(entry);
          pushToast({
            tone: 'ok',
            message: 'Restored',
            detail: `${entry.label} · seed ${entry.params.seed}`,
          });
        }}
        className="flex w-full gap-3 p-2 text-left"
      >
        <span className="relative h-20 w-14 shrink-0 overflow-hidden border border-thread bg-weft twill">
          {entry.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={entry.thumbnail} alt="" className="h-full w-full object-cover" />
          ) : null}
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate text-xs text-calico">{entry.label}</span>
            <span className="shrink-0 font-mono text-[9px] text-slub">
              {formatRelative(entry.createdAt)}
            </span>
          </span>

          <span className="mt-1 block font-mono text-[10px] leading-relaxed text-lint">
            {`${garment} · ${entry.params.fabricTemplate ?? 'strict'}/${
              entry.params.fabricScope === 'outer-only' ? 'outer' : 'set'
            }`}
            {' · '}
            {entry.params.generationMode}/{entry.params.resolution}
            {entry.params.numImages > 1 && ` · ${entry.params.numImages}×`}
          </span>

          <span className="mt-1.5 flex items-center gap-1.5">
            <span className="border border-thread px-1 py-0.5 font-mono text-[9px] text-slub">
              seed {entry.params.seed}
            </span>
            <span
              className={cn(
                'border px-1 py-0.5 font-mono text-[9px]',
                failed ? 'border-selvedge/60 text-selvedge' : 'border-thread text-slub',
              )}
            >
              {failed ? 'failed' : `${entry.creditCost} cr`}
            </span>
            {entry.params.privacy && (
              <span className="border border-thread px-1 py-0.5 font-mono text-[9px] text-slub">
                private
              </span>
            )}
          </span>

          {/* Both inputs travel with the entry, so restore is lossless. */}
          <span className="mt-2 flex gap-1">
            {[entry.productImage, entry.modelImage].map((image, index) =>
              image?.previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={`${entry.id}-${index}`}
                  src={image.previewUrl}
                  alt=""
                  className="h-7 w-7 border border-thread object-cover"
                />
              ) : (
                <span
                  key={`${entry.id}-${index}`}
                  className="h-7 w-7 border border-thread bg-weft twill"
                />
              ),
            )}
          </span>
        </span>
      </button>

      <button
        type="button"
        onClick={() => removeHistory(entry.id)}
        aria-label={`Delete ${entry.label} from history`}
        className="absolute right-1.5 top-1.5 p-1 text-slub opacity-0 transition-opacity hover:text-selvedge focus-visible:opacity-100 group-hover:opacity-100"
      >
        <IconTrash width={13} height={13} />
      </button>
    </li>
  );
}

export function HistoryDrawer() {
  const open = useStudio((s) => s.historyOpen);
  const toggleHistory = useStudio((s) => s.toggleHistory);
  const history = useStudio((s) => s.history);
  const clearHistory = useStudio((s) => s.clearHistory);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') toggleHistory(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, toggleHistory]);

  return (
    <>
      {/* The edge tab, always reachable */}
      <button
        type="button"
        onClick={() => toggleHistory()}
        aria-expanded={open}
        className={cn(
          'fixed right-0 top-1/2 z-30 hidden -translate-y-1/2 items-center gap-2 border border-r-0 border-thread bg-warp px-2 py-4 text-lint transition-colors hover:text-calico lg:flex',
          open && 'opacity-0',
        )}
        style={{ writingMode: 'vertical-rl' }}
      >
        <IconHistory width={13} height={13} />
        <span className="font-mono text-[10px] uppercase tracking-loom">History</span>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-vat/70 backdrop-blur-sm"
            onClick={() => toggleHistory(false)}
            aria-hidden
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Generation history"
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[380px] animate-drawer-in flex-col border-l border-thread bg-vat"
          >
            <header className="flex items-center justify-between border-b border-thread px-4 py-3">
              <div className="flex items-baseline gap-2">
                <h2 className="font-display text-xs font-semibold uppercase tracking-loom text-calico">
                  History
                </h2>
                <span className="font-mono text-[10px] text-slub">{history.length}</span>
              </div>
              <div className="flex items-center gap-1">
                {history.length > 0 && (
                  <button
                    type="button"
                    onClick={clearHistory}
                    className="px-2 py-1 font-mono text-[10px] uppercase tracking-loom text-slub hover:text-selvedge"
                  >
                    Clear
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => toggleHistory(false)}
                  aria-label="Close history"
                  className="p-1 text-slub hover:text-calico"
                >
                  <IconClose />
                </button>
              </div>
            </header>

            {history.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
                <div aria-hidden className="h-16 w-11 border border-thread twill" />
                <p className="text-xs leading-relaxed text-lint">
                  Every generation lands here with both inputs and the exact settings. Click one to
                  put it all back in the rail.
                </p>
              </div>
            ) : (
              <ul className="flex-1 space-y-2 overflow-y-auto p-3">
                {history.map((entry) => (
                  <Entry key={entry.id} entry={entry} />
                ))}
              </ul>
            )}

            <footer className="border-t border-thread px-4 py-3">
              <p className="font-mono text-[10px] leading-relaxed text-slub">
                Clicking an entry restores its prompt, seed, quality, mode and both uploads.
              </p>
            </footer>
          </aside>
        </>
      )}
    </>
  );
}
