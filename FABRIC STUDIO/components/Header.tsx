'use client';

import { useCredits } from '@/hooks/useCredits';
import { cn } from '@/lib/utils';
import { useStudio } from '@/store/studio';
import { IconHistory, IconLock } from './icons';

export function Header() {
  const { data, isLoading, isError } = useCredits();
  const cost = useStudio((s) => s.currentCost());
  const privacy = useStudio((s) => s.params.privacy);
  const toggleHistory = useStudio((s) => s.toggleHistory);
  const historyCount = useStudio((s) => s.history.length);

  const short = data ? data.total < cost : false;

  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center justify-between border-b border-thread bg-warp/90 px-4 backdrop-blur">
      <div className="flex items-center gap-3">
        {/* The selvedge: the vermilion thread woven into the edge of the bolt. */}
        <span aria-hidden className="block h-7 w-[3px] bg-selvedge" />
        <div className="leading-none">
          <h1 className="font-display text-[15px] font-extrabold uppercase tracking-[0.22em] text-calico">
            Selvedge
          </h1>
          <p className="mt-1 font-mono text-[9px] uppercase tracking-loom text-slub">
            Fabric &amp; garment try-on
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {privacy && (
          <span className="hidden items-center gap-1.5 border border-thread px-2 py-1.5 font-mono text-[10px] uppercase tracking-loom text-lint sm:inline-flex">
            <IconLock width={12} height={12} />
            Privacy
          </span>
        )}

        <div
          className={cn(
            'flex items-center gap-2 border px-2.5 py-1.5 font-mono text-[11px]',
            short ? 'border-selvedge text-selvedge' : 'border-thread text-calico',
          )}
          title={
            data
              ? `${data.subscription} subscription + ${data.onDemand} on-demand`
              : 'Live balance from FASHN'
          }
        >
          <span className="text-[9px] uppercase tracking-loom text-slub">Credits</span>
          <span aria-live="polite">
            {isLoading ? '····' : isError ? '—' : data?.total.toLocaleString()}
          </span>
        </div>

        <button
          type="button"
          onClick={() => toggleHistory()}
          className="inline-flex items-center gap-2 border border-thread bg-weft px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-loom text-lint transition-colors hover:border-slub hover:text-calico"
        >
          <IconHistory width={13} height={13} />
          <span className="hidden sm:inline">History</span>
          <span className="text-slub">{historyCount}</span>
        </button>
      </div>
    </header>
  );
}
