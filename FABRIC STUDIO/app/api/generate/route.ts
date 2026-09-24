import { NextResponse } from 'next/server';
import { creditCost } from '@/lib/credits';
import { StudioError, toStudioError } from '@/lib/errors';
import { fashn, type FashnModelName } from '@/lib/fashn';
import { toDataUri } from '@/lib/image';
import { fabricEditPrompt, fabricPrompt } from '@/lib/prompts';
import { getStorage } from '@/lib/storage';
import type { GenerateRequest, GenerateResponse, ImageRef, StudioParams } from '@/lib/types';

export const runtime = 'nodejs';
export const maxDuration = 60;

type FabricStrategy = 'tryon-max' | 'edit';

function fabricStrategy(): FabricStrategy {
  return process.env.FABRIC_STRATEGY === 'edit' ? 'edit' : 'tryon-max';
}

/**
 * Turn a client image reference into something FASHN can actually read.
 *
 * Hosted https URLs are preferred -- base64 inflates the payload and slows the
 * round trip. Data URIs are used only when privacy mode is on, or when the
 * configured storage is not reachable from the public internet (the usual case
 * on localhost).
 */
async function resolveImage(
  ref: ImageRef | null | undefined,
  label: string,
  privacy: boolean,
): Promise<{ value: string; inlined: boolean }> {
  if (!ref) {
    throw new StudioError({
      code: 'InputValidationError',
      message: `The ${label} is missing.`,
      fix: `Upload a ${label} before generating.`,
      httpStatus: 400,
    });
  }

  if (ref.dataUri) return { value: ref.dataUri, inlined: true };

  const storage = getStorage();
  const needsInline = privacy || !storage.isPubliclyReachable;

  if (!needsInline && ref.url && ref.url.startsWith('https://')) {
    return { value: ref.url, inlined: false };
  }

  if (ref.key) {
    const object = await storage.get(ref.key);
    if (!object) {
      throw new StudioError({
        code: 'StorageError',
        message: `The ${label} is no longer in storage.`,
        fix: 'Upload it again.',
        httpStatus: 410,
      });
    }
    return { value: toDataUri(object.body, object.contentType), inlined: true };
  }

  if (ref.url && ref.url.startsWith('https://')) {
    return { value: ref.url, inlined: false };
  }

  throw new StudioError({
    code: 'InputValidationError',
    message: `The ${label} has no readable source.`,
    fix: 'Upload it again.',
    httpStatus: 400,
  });
}

/** Fabric mode composes its prompt unless the user took the wheel. */
function promptFor(params: StudioParams, strategy: FabricStrategy): string {
  if (params.promptOverridden && params.prompt.trim()) return params.prompt.trim();
  const template = params.fabricTemplate ?? 'strict';
  const scope = params.fabricScope ?? 'full-set';
  return strategy === 'edit'
    ? fabricEditPrompt(params.garmentType, template, scope)
    : fabricPrompt(params.garmentType, template, scope);
}

/** Non-fatal balance check so "not enough credits" arrives with real numbers. */
async function assertAffordable(cost: number): Promise<void> {
  try {
    const balance = await fashn.credits();
    if (balance.total < cost) {
      throw new StudioError({
        code: 'InsufficientCredits',
        message: `This costs ${cost} credits and you have ${balance.total}. You are ${cost - balance.total} short.`,
        fix: 'Drop to a lower quality preset, reduce the image count, or top up at fashn.ai/billing.',
        httpStatus: 402,
      });
    }
  } catch (err) {
    // A hard InsufficientCredits verdict propagates; a flaky balance lookup
    // must never block a generation the user can probably afford.
    if (err instanceof StudioError && err.code === 'InsufficientCredits') throw err;
  }
}

export async function POST(request: Request): Promise<NextResponse> {
  try {
    const body = (await request.json()) as GenerateRequest;
    const { operation = 'tryon', params, product, model, source, options = {} } = body;

    if (!params) {
      throw new StudioError({
        code: 'InputValidationError',
        message: 'The request carried no parameters.',
        httpStatus: 400,
      });
    }

    const privacy = Boolean(params.privacy);
    const seed = Math.max(0, Math.min(4_294_967_295, Math.round(params.seed ?? 42)));
    const numImages = Math.max(1, Math.min(4, Math.round(params.numImages ?? 1)));

    /* ---------------------------------------------------------------- */
    /* Post-processing operations run on an existing result.             */
    /* ---------------------------------------------------------------- */
    if (operation !== 'tryon') {
      if (!source) {
        throw new StudioError({
          code: 'InputValidationError',
          message: 'There is no image to work on.',
          fix: 'Generate a result first, then run this from the action bar.',
          httpStatus: 400,
        });
      }

      const cost = creditCost(params.generationMode, params.resolution, 1);
      await assertAffordable(cost);

      let predictionId: string;
      let modelName: FashnModelName;

      switch (operation) {
        case 'upscale':
          modelName = 'reframe';
          predictionId = await fashn.run('reframe', {
            image: source,
            target_aspect_ratio: (options.target_aspect_ratio as '4:3') || undefined,
            resolution: params.resolution,
            seed,
            output_format: params.outputFormat,
            return_base64: privacy,
          });
          break;

        case 'image-to-video':
          modelName = 'image-to-video';
          predictionId = await fashn.run('image-to-video', {
            image: source,
            prompt: typeof options.prompt === 'string' ? options.prompt : undefined,
            duration: (Number(options.duration) === 10 ? 10 : 5) as 5 | 10,
            resolution: (options.resolution as '720p') || '720p',
            seed,
            return_base64: privacy,
          });
          break;

        case 'swap-face':
          modelName = 'model-swap';
          predictionId = await fashn.run('model-swap', {
            image: source,
            prompt: typeof options.prompt === 'string' ? options.prompt : undefined,
            seed,
            output_format: params.outputFormat,
            return_base64: privacy,
          });
          break;

        case 'background-change':
          modelName = 'background-change';
          predictionId = await fashn.run('background-change', {
            image: source,
            prompt: typeof options.prompt === 'string' ? options.prompt : 'a clean studio backdrop',
            seed,
            output_format: params.outputFormat,
            return_base64: privacy,
          });
          break;

        case 'background-remove':
          modelName = 'background-remove';
          predictionId = await fashn.run('background-remove', {
            image: source,
            output_format: 'png',
            return_base64: privacy,
          });
          break;

        default:
          throw new StudioError({
            code: 'InputValidationError',
            message: `Unknown operation "${operation}".`,
            httpStatus: 400,
          });
      }

      const payload: GenerateResponse = {
        predictionId,
        creditCost: cost,
        modelName,
        strategy: 'n/a',
        inlined: privacy,
      };
      return NextResponse.json(payload);
    }

    /* ---------------------------------------------------------------- */
    /* The main try-on path.                                            */
    /* ---------------------------------------------------------------- */
    const strategy = fabricStrategy();
    const useEdit = strategy === 'edit';

    const [resolvedProduct, resolvedModel] = await Promise.all([
      resolveImage(product, 'fabric swatch', privacy),
      resolveImage(model, 'model image', privacy),
    ]);

    const cost = creditCost(params.generationMode, params.resolution, numImages);
    await assertAffordable(cost);

    const prompt = promptFor(params, strategy);

    const predictionId = useEdit
      ? await fashn.run('edit', {
          // Edit strategy: the person is the canvas, the swatch is the reference.
          image: resolvedModel.value,
          reference_image: resolvedProduct.value,
          prompt,
          resolution: params.resolution,
          generation_mode: params.generationMode,
          seed,
          num_images: numImages,
          output_format: params.outputFormat,
          return_base64: privacy,
        })
      : await fashn.run('tryon-max', {
          product_image: resolvedProduct.value,
          model_image: resolvedModel.value,
          prompt: prompt || undefined,
          resolution: params.resolution,
          // Always explicit -- omitting this silently bills as `balanced`.
          generation_mode: params.generationMode,
          seed,
          num_images: numImages,
          output_format: params.outputFormat,
          return_base64: privacy,
        });

    const payload: GenerateResponse = {
      predictionId,
      creditCost: cost,
      modelName: useEdit ? 'edit' : 'tryon-max',
      strategy,
      inlined: resolvedProduct.inlined || resolvedModel.inlined,
    };

    return NextResponse.json(payload);
  } catch (err) {
    const studio = toStudioError(err);
    return NextResponse.json(studio.toPayload(), { status: studio.httpStatus });
  }
}
