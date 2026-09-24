/**
 * Shared vocabulary for the studio. Everything here is safe to import from
 * both server routes and client components -- no secrets, no node builtins.
 */

export type Resolution = '1k' | '2k' | '4k';
export type GenerationMode = 'fast' | 'balanced' | 'quality';
export type OutputFormat = 'png' | 'jpeg';

/**
 * Which fabric-mode prompt template composes the prompt.
 *
 * `strict` is the default: a structural directive that pins silhouette,
 * construction, identity and pose while remaking every layer in the uploaded
 * cloth. `coordinated` is a shorter designer brief aimed at colour harmony.
 */
export type FabricTemplate = 'coordinated' | 'strict' | 'concise';

/**
 * How much of the outfit the fabric replaces.
 * `full-set` remakes cap, outer garment, inner top and trousers in the cloth
 * and recolours embroidery to match. `outer-only` leaves the other layers in
 * the colour they had in the reference photo.
 */
export type FabricScope = 'full-set' | 'outer-only';

export type GarmentType =
  | 'agbada'
  | 'kaftan'
  | 'senator'
  | 'suit'
  | 'dress'
  | 'shirt'
  | 'two-piece'
  | 'custom';

export const GARMENT_TYPES: { value: GarmentType; label: string }[] = [
  { value: 'agbada', label: 'Agbada' },
  { value: 'kaftan', label: 'Kaftan' },
  { value: 'senator', label: 'Senator' },
  { value: 'suit', label: 'Suit' },
  { value: 'dress', label: 'Dress' },
  { value: 'shirt', label: 'Shirt' },
  { value: 'two-piece', label: 'Two-piece' },
  { value: 'custom', label: 'Custom' },
];

/** A preprocessed image that has been through /api/upload. */
export interface StudioImage {
  /** Stable client id, also the storage key stem. */
  id: string;
  /** Storage key. Lets the server re-read the bytes without a round trip. */
  key?: string;
  /** Hosted https URL. Empty when the upload stayed local (privacy mode). */
  url: string;
  /** data: URI. Present when privacy mode is on or storage is unreachable. */
  dataUri?: string;
  /** What the browser renders. Always populated. */
  previewUrl: string;
  fileName: string;
  bytes: number;
  width: number;
  height: number;
  contentType: string;
}

/** Everything a generation depends on. History restores this verbatim. */
export interface StudioParams {
  garmentType: GarmentType;
  /** Which template composes the prompt. */
  fabricTemplate: FabricTemplate;
  /** How many layers the fabric replaces. */
  fabricScope: FabricScope;
  prompt: string;
  /** True once the user has hand-edited the prompt. */
  promptOverridden: boolean;
  resolution: Resolution;
  generationMode: GenerationMode;
  seed: number;
  numImages: number;
  outputFormat: OutputFormat;
  /** Privacy mode: data URIs in, base64 out, ~60 min retention at FASHN. */
  privacy: boolean;
}

export type PredictionStatus =
  | 'starting'
  | 'in_queue'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'canceled';

export interface PredictionResult {
  id: string;
  status: PredictionStatus;
  output: string[] | null;
  error: string | null;
}

export type StudioOperation =
  | 'tryon'
  | 'upscale'
  | 'image-to-video'
  | 'swap-face'
  | 'background-change'
  | 'background-remove';

export interface HistoryEntry {
  id: string;
  createdAt: number;
  predictionId: string | null;
  operation: StudioOperation;
  status: 'completed' | 'failed' | 'running' | 'timed_out';
  outputs: string[];
  /** Rendered in the drawer. Usually outputs[0]. */
  thumbnail: string;
  productImage: StudioImage | null;
  modelImage: StudioImage | null;
  params: StudioParams;
  creditCost: number;
  /** e.g. "Agbada in indigo adire" -- shown under the thumbnail. */
  label: string;
  error?: string;
}

export const DEFAULT_PARAMS: StudioParams = {
  garmentType: 'agbada',
  fabricTemplate: 'strict',
  fabricScope: 'full-set',
  prompt: '',
  promptOverridden: false,
  resolution: '1k',
  generationMode: 'fast',
  seed: 42,
  numImages: 1,
  outputFormat: 'png',
  privacy: false,
};

/* -------------------------------------------------------------------------- */
/* Hard input limits, straight from the FASHN docs. Enforced client-side       */
/* before upload and again server-side before the API call.                    */
/* -------------------------------------------------------------------------- */

export const MAX_FILE_BYTES = 30 * 1024 * 1024; // 30 MiB
export const MIN_DIMENSION = 15; // px
export const MAX_ASPECT_RATIO = 16; // 1:16 .. 16:1
export const MAX_LONG_EDGE = 2000; // our own downscale ceiling
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/avif'];

/* -------------------------------------------------------------------------- */
/* Route contracts. Shared by the client and the route handlers.               */
/* -------------------------------------------------------------------------- */

export interface ImageRef {
  key?: string;
  url?: string;
  dataUri?: string;
  fileName: string;
}

export interface UploadResponse extends StudioImage {
  /** Soft advice, e.g. "this model image is wider than 2:3". Never blocking. */
  hint: string | null;
}

export interface GenerateRequest {
  operation: StudioOperation;
  params: StudioParams;
  /** Garment or fabric swatch. Required for `tryon`. */
  product?: ImageRef | null;
  /** The person. Required for `tryon`. */
  model?: ImageRef | null;
  /** For post-processing operations: the https URL of the image to work on. */
  source?: string;
  /** Operation-specific extras, e.g. target_aspect_ratio or duration. */
  options?: Record<string, string | number | boolean>;
}

export interface GenerateResponse {
  predictionId: string;
  creditCost: number;
  modelName: string;
  /** Which fabric strategy actually ran. Echoed so the UI can label history. */
  strategy: 'tryon-max' | 'edit' | 'n/a';
  /** True when the payload used data URIs rather than hosted URLs. */
  inlined: boolean;
}

export interface CreditsResponse {
  total: number;
  subscription: number;
  onDemand: number;
}
