import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { StudioError, toStudioError } from '@/lib/errors';
import { aspectHint, preprocess, toDataUri, validateFile, type CropRect } from '@/lib/image';
import { getStorage } from '@/lib/storage';
import type { UploadResponse } from '@/lib/types';

export const runtime = 'nodejs';
export const maxDuration = 60;

/**
 * Accepts multipart form data and returns a URL FASHN can read.
 *
 * fields: file, slot=product|model, privacy=true|false, lossless=true|false,
 *         crop={"x":0,"y":0,"width":1,"height":1}
 */
export async function POST(request: Request): Promise<NextResponse> {
  try {
    const form = await request.formData();
    const file = form.get('file');

    if (!(file instanceof File)) {
      throw new StudioError({
        code: 'InputValidationError',
        message: 'No file arrived with the upload.',
        fix: 'Pick an image and try again.',
        httpStatus: 400,
      });
    }

    validateFile({ name: file.name, size: file.size, type: file.type });

    const slot = form.get('slot') === 'model' ? 'model' : 'product';
    const privacy = form.get('privacy') === 'true';
    const lossless = privacy || form.get('lossless') === 'true';

    let crop: CropRect | null = null;
    const rawCrop = form.get('crop');
    if (typeof rawCrop === 'string' && rawCrop.trim()) {
      try {
        const parsed = JSON.parse(rawCrop) as CropRect;
        if (
          [parsed.x, parsed.y, parsed.width, parsed.height].every(
            (n) => typeof n === 'number' && Number.isFinite(n),
          )
        ) {
          crop = parsed;
        }
      } catch {
        /* a malformed crop is ignored rather than failing the upload */
      }
    }

    const input = Buffer.from(await file.arrayBuffer());
    const processed = await preprocess(input, file.name, { lossless, crop });

    const id = randomUUID();

    // Privacy mode keeps the bytes off our disk as well as out of FASHN's history.
    if (privacy) {
      const dataUri = toDataUri(processed.buffer, processed.contentType);
      const payload: UploadResponse = {
        id,
        url: '',
        dataUri,
        previewUrl: dataUri,
        fileName: file.name,
        bytes: processed.bytes,
        width: processed.width,
        height: processed.height,
        contentType: processed.contentType,
        hint: slot === 'model' ? aspectHint(processed.width, processed.height) : null,
      };
      return NextResponse.json(payload);
    }

    const storage = getStorage();
    const key = `${slot}/${id}.${processed.extension}`;
    const stored = await storage.put(key, processed.buffer, processed.contentType);

    const payload: UploadResponse = {
      id,
      key: stored.key,
      url: stored.url,
      previewUrl: `/api/files/${stored.key}`,
      fileName: file.name,
      bytes: processed.bytes,
      width: processed.width,
      height: processed.height,
      contentType: processed.contentType,
      hint: slot === 'model' ? aspectHint(processed.width, processed.height) : null,
    };

    return NextResponse.json(payload);
  } catch (err) {
    const studio = toStudioError(err);
    return NextResponse.json(studio.toPayload(), { status: studio.httpStatus });
  }
}
