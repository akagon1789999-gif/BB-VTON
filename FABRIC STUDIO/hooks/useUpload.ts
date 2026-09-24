'use client';

import { useCallback, useState } from 'react';
import { ApiError, uploadImage } from '@/lib/client-api';
import { inspect, validate } from '@/lib/client-validate';
import { recallFile, rememberFile } from '@/lib/fileCache';
import { useStudio, type CropRect, type SlotName } from '@/store/studio';

export function useUpload(slot: SlotName) {
  const setSlot = useStudio((s) => s.setSlot);
  const privacy = useStudio((s) => s.params.privacy);
  const pushToast = useStudio((s) => s.pushToast);
  const [progress, setProgress] = useState(0);

  const send = useCallback(
    async (file: File, crop: CropRect | null) => {
      setSlot(slot, { uploading: true, error: null, hint: null });
      setProgress(0.15);

      try {
        const uploaded = await uploadImage(file, { slot, privacy, crop });
        setProgress(1);
        setSlot(slot, {
          image: uploaded,
          uploading: false,
          error: null,
          hint: uploaded.hint,
          crop,
        });
      } catch (err) {
        const payload = err instanceof ApiError ? err.payload : null;
        const message = payload?.message ?? 'The upload failed.';
        setSlot(slot, { uploading: false, error: payload?.fix ? `${message} ${payload.fix}` : message });
        pushToast({ tone: 'error', message, detail: payload?.fix });
      } finally {
        setProgress(0);
      }
    },
    [privacy, pushToast, setSlot, slot],
  );

  /** Runs the client-side limit checks first, so a 41 MB file never uploads. */
  const accept = useCallback(
    async (file: File) => {
      let dims: { width: number; height: number } | undefined;
      try {
        const inspected = await inspect(file);
        dims = { width: inspected.width, height: inspected.height };
        URL.revokeObjectURL(inspected.objectUrl);
      } catch {
        dims = undefined;
      }

      const problem = validate(file, dims);
      if (problem) {
        setSlot(slot, {
          uploading: false,
          error: problem.fix ? `${problem.message} ${problem.fix}` : problem.message,
        });
        pushToast({ tone: 'error', message: problem.message, detail: problem.fix });
        return;
      }

      rememberFile(slot, file);
      await send(file, null);
    },
    [pushToast, send, setSlot, slot],
  );

  /** Re-uploads the original with a new crop rect. The original is never lost. */
  const recrop = useCallback(
    async (crop: CropRect | null) => {
      const original = recallFile(slot);
      if (!original) {
        pushToast({
          tone: 'error',
          message: 'The original file is no longer in this session.',
          detail: 'Upload the image again to change the crop.',
        });
        return;
      }
      await send(original, crop);
    },
    [pushToast, send, slot],
  );

  return { accept, recrop, progress };
}
