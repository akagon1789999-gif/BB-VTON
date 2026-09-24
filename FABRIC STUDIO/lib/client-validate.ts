'use client';

import { formatBytes } from './errors';
import {
  ACCEPTED_TYPES,
  MAX_ASPECT_RATIO,
  MAX_FILE_BYTES,
  MIN_DIMENSION,
} from './types';

export interface ClientCheck {
  message: string;
  fix?: string;
}

export interface Inspected {
  width: number;
  height: number;
  objectUrl: string;
}

/** Decodes just enough to know the dimensions, before anything hits the wire. */
export async function inspect(file: File): Promise<Inspected> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const bitmap = await createImageBitmap(file);
    const { width, height } = bitmap;
    bitmap.close();
    return { width, height, objectUrl };
  } catch {
    // Some formats (AVIF on older Safari) refuse createImageBitmap. Fall back
    // to an <img> decode rather than rejecting a file the server can handle.
    return await new Promise<Inspected>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight, objectUrl });
      img.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        reject(new Error('decode failed'));
      };
      img.src = objectUrl;
    });
  }
}

/** The same limits the API enforces, checked before we spend an upload on it. */
export function validate(file: File, dims?: { width: number; height: number }): ClientCheck | null {
  if (file.size > MAX_FILE_BYTES) {
    return {
      message: `${file.name} is ${formatBytes(file.size)}. The limit is 30 MB.`,
      fix: 'Export it smaller, or use a JPEG instead of a raw PNG.',
    };
  }
  if (file.size === 0) {
    return { message: `${file.name} is empty.`, fix: 'Pick a different file.' };
  }
  if (file.type && !ACCEPTED_TYPES.includes(file.type)) {
    return {
      message: `${file.name} is ${file.type || 'an unsupported type'}. Use JPEG, PNG, WebP or AVIF.`,
      fix: 'Convert it and try again.',
    };
  }
  if (dims) {
    if (dims.width < MIN_DIMENSION || dims.height < MIN_DIMENSION) {
      return {
        message: `${file.name} is ${dims.width} x ${dims.height} px. The minimum is 15 x 15 px.`,
        fix: 'Use the full-size original, not a thumbnail.',
      };
    }
    const ratio = dims.width / dims.height;
    if (ratio > MAX_ASPECT_RATIO || ratio < 1 / MAX_ASPECT_RATIO) {
      return {
        message: `${file.name} is ${dims.width} x ${dims.height} px, past the 16:1 aspect ratio limit.`,
        fix: 'Crop it closer to square first.',
      };
    }
  }
  return null;
}
