'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { recallFile } from '@/lib/fileCache';
import { cn } from '@/lib/utils';
import { useStudio, type CropRect, type SlotName } from '@/store/studio';
import { Button, Modal } from '../ui';

const FULL: CropRect = { x: 0, y: 0, width: 1, height: 1 };
const TARGET_RATIO = 2 / 3;

type DragMode = 'move' | 'resize' | null;

function clampRect(rect: CropRect): CropRect {
  const width = Math.min(1, Math.max(0.05, rect.width));
  const height = Math.min(1, Math.max(0.05, rect.height));
  return {
    width,
    height,
    x: Math.min(Math.max(0, rect.x), 1 - width),
    y: Math.min(Math.max(0, rect.y), 1 - height),
  };
}

/** Largest 2:3 box that fits inside the frame, centred on the current rect. */
function fitPortrait(rect: CropRect, imageRatio: number): CropRect {
  // Work in normalised space, so the target ratio has to account for the
  // image's own aspect: a normalised box of w,h is (w*W) by (h*H) pixels.
  let width = 1;
  let height = width / TARGET_RATIO / (1 / imageRatio);
  if (height > 1) {
    height = 1;
    width = TARGET_RATIO * height * (1 / imageRatio);
  }
  const cx = rect.x + rect.width / 2;
  const cy = rect.y + rect.height / 2;
  return clampRect({ x: cx - width / 2, y: cy - height / 2, width, height });
}

export function CropModal({
  open,
  onClose,
  slot,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  slot: SlotName;
  onApply: (rect: CropRect | null) => void;
}) {
  const slotState = useStudio((s) => s[slot]);
  const [rect, setRect] = useState<CropRect>(slotState.crop ?? FULL);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [imageRatio, setImageRatio] = useState(1);
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: DragMode; startX: number; startY: number; origin: CropRect }>({
    mode: null,
    startX: 0,
    startY: 0,
    origin: FULL,
  });

  const original = open ? recallFile(slot) : undefined;

  useEffect(() => {
    if (!open) return;
    setRect(slotState.crop ?? FULL);
    if (!original) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(original);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
    // slotState.crop is read once when the dialog opens, on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, original]);

  const source = objectUrl ?? slotState.image?.previewUrl ?? '';
  const canApply = Boolean(original);

  const onPointerDown = useCallback(
    (mode: Exclude<DragMode, null>) => (event: React.PointerEvent) => {
      event.preventDefault();
      (event.target as HTMLElement).setPointerCapture(event.pointerId);
      drag.current = { mode, startX: event.clientX, startY: event.clientY, origin: rect };
    },
    [rect],
  );

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    const box = frame.current?.getBoundingClientRect();
    const state = drag.current;
    if (!box || !state.mode) return;

    const dx = (event.clientX - state.startX) / box.width;
    const dy = (event.clientY - state.startY) / box.height;

    if (state.mode === 'move') {
      setRect(clampRect({ ...state.origin, x: state.origin.x + dx, y: state.origin.y + dy }));
    } else {
      setRect(
        clampRect({
          ...state.origin,
          width: state.origin.width + dx,
          height: state.origin.height + dy,
        }),
      );
    }
  }, []);

  const onPointerUp = useCallback(() => {
    drag.current.mode = null;
  }, []);

  /** Arrow keys nudge, shift+arrows resize. The crop is fully keyboard-driven. */
  const onKeyDown = useCallback((event: React.KeyboardEvent) => {
    const step = event.altKey ? 0.005 : 0.02;
    const map: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    const delta = map[event.key];
    if (!delta) return;
    event.preventDefault();

    setRect((current) =>
      event.shiftKey
        ? clampRect({
            ...current,
            width: current.width + delta[0],
            height: current.height + delta[1],
          })
        : clampRect({ ...current, x: current.x + delta[0], y: current.y + delta[1] }),
    );
  }, []);

  const readout = useMemo(() => {
    const image = slotState.image;
    if (!image) return '';
    const w = Math.round(image.width * rect.width);
    const h = Math.round(image.height * rect.height);
    return `${w}×${h} · ${(w / h).toFixed(2)}:1`;
  }, [rect, slotState.image]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="Crop"
      description="Model images generate best near 2:3. Nothing is written over your original — change the crop as often as you like."
      footer={
        <>
          <Button variant="quiet" onClick={() => setRect(FULL)}>
            Reset
          </Button>
          <Button onClick={() => setRect((r) => fitPortrait(r, imageRatio))}>Fit 2:3</Button>
          <Button
            variant="primary"
            disabled={!canApply}
            onClick={() => onApply(rect.width === 1 && rect.height === 1 ? null : rect)}
          >
            Apply crop
          </Button>
        </>
      }
    >
      {!canApply && (
        <p className="mb-3 border border-thread bg-weft px-3 py-2 text-[11px] text-lint">
          This image came back from history, so the original file is not in this session. Upload it
          again to change the crop.
        </p>
      )}

      <div
        ref={frame}
        role="group"
        aria-label="Crop area"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className="relative mx-auto max-h-[46vh] w-full select-none overflow-hidden border border-thread bg-vat"
      >
        {source && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={source}
            alt=""
            onLoad={(e) => {
              const el = e.currentTarget;
              setImageRatio(el.naturalWidth / el.naturalHeight);
            }}
            className="block max-h-[46vh] w-full object-contain"
          />
        )}

        <div className="pointer-events-none absolute inset-0 bg-vat/60" />

        <div
          onPointerDown={onPointerDown('move')}
          className="absolute cursor-move border border-calico shadow-[0_0_0_9999px_rgba(9,11,16,0.6)]"
          style={{
            left: `${rect.x * 100}%`,
            top: `${rect.y * 100}%`,
            width: `${rect.width * 100}%`,
            height: `${rect.height * 100}%`,
          }}
        >
          {/* Rule of thirds, the weaver's grid */}
          <div className="pointer-events-none absolute inset-0 opacity-40">
            <div className="absolute left-1/3 top-0 h-full w-px bg-calico" />
            <div className="absolute left-2/3 top-0 h-full w-px bg-calico" />
            <div className="absolute top-1/3 h-px w-full bg-calico" />
            <div className="absolute top-2/3 h-px w-full bg-calico" />
          </div>
          <span
            onPointerDown={onPointerDown('resize')}
            className={cn(
              'absolute -bottom-1.5 -right-1.5 h-3 w-3 cursor-nwse-resize bg-selvedge',
            )}
          />
        </div>
      </div>

      <p className="mt-3 text-center font-mono text-[10px] text-slub">
        {readout} · drag to move, arrow keys to nudge, shift+arrows to resize
      </p>
    </Modal>
  );
}
