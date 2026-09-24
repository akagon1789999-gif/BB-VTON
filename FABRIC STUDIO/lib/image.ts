import 'server-only';
import sharp from 'sharp';
import { StudioError, formatBytes } from './errors';
import {
  ACCEPTED_TYPES,
  MAX_ASPECT_RATIO,
  MAX_FILE_BYTES,
  MAX_LONG_EDGE,
  MIN_DIMENSION,
} from './types';

export interface CropRect {
  /** Normalised 0..1 against the EXIF-rotated original. */
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PreprocessOptions {
  /** Keeps PNG instead of transcoding to JPEG. */
  lossless?: boolean;
  crop?: CropRect | null;
  maxLongEdge?: number;
}

export interface PreprocessResult {
  buffer: Buffer;
  contentType: 'image/jpeg' | 'image/png';
  extension: 'jpg' | 'png';
  width: number;
  height: number;
  bytes: number;
}

/** File-level checks that need no decode. Runs before we hand bytes to sharp. */
export function validateFile(file: { name: string; size: number; type: string }): void {
  if (file.size > MAX_FILE_BYTES) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${file.name} is ${formatBytes(file.size)}. The limit is 30 MB.`,
      fix: 'Export it smaller, or screenshot it at a lower resolution.',
      httpStatus: 422,
    });
  }
  if (file.size === 0) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${file.name} is empty.`,
      fix: 'Pick a different file.',
      httpStatus: 422,
    });
  }
  if (file.type && !ACCEPTED_TYPES.includes(file.type)) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${file.name} is ${file.type}. JPEG, PNG, WebP and AVIF are supported.`,
      fix: 'Convert it to JPEG or PNG first.',
      httpStatus: 422,
    });
  }
}

/** Dimension and aspect checks against decoded metadata. */
export function validateDimensions(name: string, width: number, height: number): void {
  if (width < MIN_DIMENSION || height < MIN_DIMENSION) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${name} is ${width} x ${height} px. The minimum is 15 x 15 px.`,
      fix: 'Use the original photo rather than a thumbnail.',
      httpStatus: 422,
    });
  }
  const ratio = width / height;
  if (ratio > MAX_ASPECT_RATIO || ratio < 1 / MAX_ASPECT_RATIO) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${name} is ${width} x ${height} px, past the 16:1 aspect ratio limit.`,
      fix: 'Crop it closer to square before uploading.',
      httpStatus: 422,
    });
  }
}

/**
 * 1. Auto-rotate from EXIF and strip metadata.
 * 2. Apply the crop rect, if the user set one.
 * 3. Downscale anything over 2000 px on the long edge, preserving aspect.
 * 4. JPEG q95, or PNG when the caller asked for lossless.
 */
export async function preprocess(
  input: Buffer,
  name: string,
  options: PreprocessOptions = {},
): Promise<PreprocessResult> {
  const { lossless = false, crop = null, maxLongEdge = MAX_LONG_EDGE } = options;

  let pipeline: sharp.Sharp;
  let meta: sharp.Metadata;
  try {
    // rotate() with no argument applies the EXIF orientation, then drops it.
    pipeline = sharp(input, { failOn: 'none' }).rotate();
    meta = await sharp(input, { failOn: 'none' }).rotate().metadata();
  } catch {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${name} could not be decoded as an image.`,
      fix: 'Re-export it as JPEG or PNG and try again.',
      httpStatus: 422,
    });
  }

  const srcWidth = meta.width ?? 0;
  const srcHeight = meta.height ?? 0;
  if (!srcWidth || !srcHeight) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${name} has no readable dimensions.`,
      fix: 'Re-export it as JPEG or PNG and try again.',
      httpStatus: 422,
    });
  }
  validateDimensions(name, srcWidth, srcHeight);

  let workingWidth = srcWidth;
  let workingHeight = srcHeight;

  if (crop) {
    const left = Math.max(0, Math.round(crop.x * srcWidth));
    const top = Math.max(0, Math.round(crop.y * srcHeight));
    const width = Math.max(MIN_DIMENSION, Math.round(crop.width * srcWidth));
    const height = Math.max(MIN_DIMENSION, Math.round(crop.height * srcHeight));
    const clampedWidth = Math.min(width, srcWidth - left);
    const clampedHeight = Math.min(height, srcHeight - top);

    validateDimensions(name, clampedWidth, clampedHeight);
    pipeline = pipeline.extract({ left, top, width: clampedWidth, height: clampedHeight });
    workingWidth = clampedWidth;
    workingHeight = clampedHeight;
  }

  const longEdge = Math.max(workingWidth, workingHeight);
  if (longEdge > maxLongEdge) {
    const scale = maxLongEdge / longEdge;
    workingWidth = Math.round(workingWidth * scale);
    workingHeight = Math.round(workingHeight * scale);
    pipeline = pipeline.resize(workingWidth, workingHeight, { fit: 'inside', withoutEnlargement: true });
  }

  const encoded = lossless
    ? await pipeline.png({ compressionLevel: 9, effort: 7 }).toBuffer({ resolveWithObject: true })
    : await pipeline
        .flatten({ background: '#ffffff' })
        .jpeg({ quality: 95, chromaSubsampling: '4:4:4', mozjpeg: true })
        .toBuffer({ resolveWithObject: true });

  const bytes = encoded.data.byteLength;
  if (bytes > MAX_FILE_BYTES) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `${name} is still ${formatBytes(bytes)} after processing. The limit is 30 MB.`,
      fix: 'Turn off privacy mode, or use a smaller source image.',
      httpStatus: 422,
    });
  }

  return {
    buffer: encoded.data,
    contentType: lossless ? 'image/png' : 'image/jpeg',
    extension: lossless ? 'png' : 'jpg',
    width: encoded.info.width,
    height: encoded.info.height,
    bytes,
  };
}

export function toDataUri(buffer: Buffer, contentType: string): string {
  return `data:${contentType};base64,${buffer.toString('base64')}`;
}

/** Model images generate best near 2:3. Used to nudge, never to crop silently. */
export function aspectHint(width: number, height: number): string | null {
  const ratio = width / height;
  const target = 2 / 3;
  if (Math.abs(ratio - target) < 0.12) return null;
  if (ratio > target) {
    return 'This model image is wider than 2:3. Cropping to portrait usually gives a cleaner try-on.';
  }
  return 'This model image is taller than 2:3. Cropping to portrait usually gives a cleaner try-on.';
}
