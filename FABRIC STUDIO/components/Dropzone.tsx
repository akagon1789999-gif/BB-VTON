'use client';

import { useCallback, useRef, useState } from 'react';
import { useUpload } from '@/hooks/useUpload';
import { formatBytes } from '@/lib/errors';
import { cn } from '@/lib/utils';
import { useStudio, type SlotName } from '@/store/studio';
import { IconAlert, IconClose, IconCrop, IconUpload } from './icons';
import { CropModal } from './modals/CropModal';

export function Dropzone({
  slot,
  title,
  hintLine,
  offerCrop = false,
}: {
  slot: SlotName;
  title: string;
  hintLine: string;
  offerCrop?: boolean;
}) {
  const state = useStudio((s) => s[slot]);
  const clearSlot = useStudio((s) => s.clearSlot);
  const { accept, recrop } = useUpload(slot);

  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [cropOpen, setCropOpen] = useState(false);

  const onFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) void accept(file);
    },
    [accept],
  );

  const image = state.image;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h3 className="label">{title}</h3>
        {image && (
          <span className="font-mono text-[10px] text-slub">
            {image.width}×{image.height}
            {image.bytes > 0 && ` · ${formatBytes(image.bytes)}`}
          </span>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          onFiles(e.dataTransfer.files);
        }}
        onPaste={(e) => onFiles(e.clipboardData.files)}
        className={cn(
          'group relative aspect-[4/3] w-full overflow-hidden border bg-weft transition-colors',
          dragging ? 'border-selvedge' : 'border-thread',
          !image && 'twill',
        )}
      >
        {image ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.previewUrl}
              alt={image.fileName}
              className="h-full w-full object-contain"
            />
            <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-gradient-to-t from-vat/95 to-transparent px-2 pb-2 pt-6">
              <span className="truncate font-mono text-[10px] text-lint">{image.fileName}</span>
              <span className="flex shrink-0 items-center gap-1">
                {offerCrop && (
                  <button
                    type="button"
                    onClick={() => setCropOpen(true)}
                    className="border border-thread bg-warp/90 p-1 text-lint hover:text-calico"
                    title="Crop"
                    aria-label={`Crop ${title}`}
                  >
                    <IconCrop width={13} height={13} />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => clearSlot(slot)}
                  className="border border-thread bg-warp/90 p-1 text-lint hover:text-selvedge"
                  title="Remove"
                  aria-label={`Remove ${title}`}
                >
                  <IconClose width={13} height={13} />
                </button>
              </span>
            </div>
          </>
        ) : (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="flex h-full w-full flex-col items-center justify-center gap-2 px-4 text-center"
          >
            <IconUpload className="text-slub transition-colors group-hover:text-calico" width={20} height={20} />
            <span className="text-xs text-lint">Drop an image, or click to browse</span>
            <span className="max-w-[24ch] text-[11px] leading-relaxed text-slub">{hintLine}</span>
          </button>
        )}

        {state.uploading && (
          <div className="absolute inset-0 flex items-end bg-vat/70">
            <div className="h-[2px] w-full overflow-hidden bg-thread">
              <div className="h-full w-1/3 animate-shuttle bg-selvedge" />
            </div>
          </div>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/avif"
        className="sr-only"
        onChange={(e) => {
          onFiles(e.target.files);
          e.target.value = '';
        }}
      />

      {state.error && (
        <p className="flex gap-1.5 text-[11px] leading-relaxed text-selvedge" role="alert">
          <IconAlert width={13} height={13} className="mt-[1px] shrink-0" />
          {state.error}
        </p>
      )}

      {!state.error && state.hint && (
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-lint">
          <span>{state.hint}</span>
          {offerCrop && (
            <button
              type="button"
              onClick={() => setCropOpen(true)}
              className="shrink-0 font-mono text-[10px] uppercase tracking-loom text-selvedge underline-offset-2 hover:underline"
            >
              Crop
            </button>
          )}
        </p>
      )}

      {offerCrop && (
        <CropModal
          open={cropOpen}
          onClose={() => setCropOpen(false)}
          slot={slot}
          onApply={(rect) => {
            setCropOpen(false);
            void recrop(rect);
          }}
        />
      )}
    </section>
  );
}
