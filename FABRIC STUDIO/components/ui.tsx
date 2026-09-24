'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { IconChevron, IconClose } from './icons';

/* -------------------------------------------------------------------------- */
/* Segmented control                                                          */
/* -------------------------------------------------------------------------- */

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  note?: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'md',
}: {
  options: SegmentOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  ariaLabel: string;
  size?: 'sm' | 'md';
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="grid gap-px border border-thread bg-thread"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'relative flex flex-col items-center justify-center gap-0.5 bg-weft transition-colors',
              size === 'sm' ? 'px-2 py-1.5' : 'px-2 py-2.5',
              active ? 'bg-warp text-calico' : 'text-lint hover:text-calico hover:bg-warp/60',
              active && 'selvedge-mark',
            )}
          >
            <span
              className={cn(
                'font-mono uppercase tracking-loom',
                size === 'sm' ? 'text-[10px]' : 'text-[11px]',
              )}
            >
              {option.label}
            </span>
            {option.note && (
              <span className="font-mono text-[9px] text-slub">{option.note}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Switch                                                                     */
/* -------------------------------------------------------------------------- */

export function Switch({
  checked,
  onChange,
  label,
  description,
  icon,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  icon?: ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-3">
      <label htmlFor={id} className="cursor-pointer">
        <span className="flex items-center gap-1.5 text-xs text-calico">
          {icon}
          {label}
        </span>
        {description && <span className="mt-0.5 block text-[11px] text-slub">{description}</span>}
      </label>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'mt-0.5 h-4 w-8 shrink-0 border transition-colors',
          checked ? 'border-selvedge bg-selvedge/20' : 'border-thread bg-weft',
        )}
      >
        <span
          className={cn(
            'block h-3 w-3 translate-y-[1px] transition-transform',
            checked ? 'translate-x-[17px] bg-selvedge' : 'translate-x-[2px] bg-slub',
          )}
        />
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Disclosure                                                                 */
/* -------------------------------------------------------------------------- */

export function Disclosure({
  title,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  badge?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();

  return (
    <div className="border-t border-thread">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between py-3 text-left"
      >
        <span className="label">{title}</span>
        <span className="flex items-center gap-2">
          {badge && <span className="font-mono text-[10px] text-slub">{badge}</span>}
          <IconChevron
            className={cn('text-slub transition-transform', open && 'rotate-90')}
          />
        </span>
      </button>
      {open && (
        <div id={id} className="space-y-4 pb-4">
          {children}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Modal -- focus trap, escape, scroll lock, portal-free but overlaid          */
/* -------------------------------------------------------------------------- */

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!open) return;

    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const focusables = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => !el.hasAttribute('disabled'));

    focusables()[0]?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-vat/85 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        className={cn(
          'relative w-full animate-scale-in border border-thread bg-warp shadow-2xl',
          wide ? 'max-w-3xl' : 'max-w-md',
        )}
      >
        <div className="flex items-start justify-between border-b border-thread px-5 py-4">
          <div>
            <h2 id={titleId} className="font-display text-sm font-semibold uppercase tracking-loom">
              {title}
            </h2>
            {description && (
              <p id={descId} className="mt-1 max-w-md text-xs text-lint">
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 p-1 text-slub hover:text-calico"
          >
            <IconClose />
          </button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-thread px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Buttons                                                                    */
/* -------------------------------------------------------------------------- */

export function Button({
  children,
  onClick,
  variant = 'ghost',
  disabled,
  type = 'button',
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost' | 'quiet';
  disabled?: boolean;
  type?: 'button' | 'submit';
  className?: string;
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center justify-center gap-2 border px-3 py-2 font-mono text-[11px] uppercase tracking-loom transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        variant === 'primary' &&
          'border-selvedge bg-selvedge text-vat hover:bg-selvedge/90 disabled:bg-weft disabled:text-slub disabled:border-thread',
        variant === 'ghost' && 'border-thread bg-weft text-calico hover:border-slub',
        variant === 'quiet' && 'border-transparent bg-transparent text-lint hover:text-calico',
        className,
      )}
    >
      {children}
    </button>
  );
}
