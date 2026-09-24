'use client';

import { useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useStudio, type Toast } from '@/store/studio';
import { IconAlert, IconCheck, IconClose } from './icons';

function ToastRow({ toast }: { toast: Toast }) {
  const dismiss = useStudio((s) => s.dismissToast);

  useEffect(() => {
    const id = setTimeout(() => dismiss(toast.id), toast.tone === 'error' ? 8_000 : 4_000);
    return () => clearTimeout(id);
  }, [dismiss, toast.id, toast.tone]);

  return (
    <div
      role="status"
      className={cn(
        'flex w-[320px] animate-fade-up items-start gap-2 border bg-warp px-3 py-2.5 shadow-xl',
        toast.tone === 'error' ? 'border-selvedge/60' : 'border-thread',
      )}
    >
      <span className={cn('mt-[2px]', toast.tone === 'error' ? 'text-selvedge' : 'text-lint')}>
        {toast.tone === 'error' ? <IconAlert width={13} height={13} /> : <IconCheck width={13} height={13} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-xs text-calico">{toast.message}</span>
        {toast.detail && (
          <span className="mt-0.5 block text-[11px] leading-relaxed text-slub">{toast.detail}</span>
        )}
      </span>
      <button
        type="button"
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss"
        className="-mr-1 -mt-0.5 p-1 text-slub hover:text-calico"
      >
        <IconClose width={12} height={12} />
      </button>
    </div>
  );
}

export function Toasts() {
  const toasts = useStudio((s) => s.toasts);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-20 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastRow toast={toast} />
        </div>
      ))}
    </div>
  );
}
