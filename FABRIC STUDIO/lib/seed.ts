import { creditCost } from './credits';
import { fabricPrompt } from './prompts';
import type { HistoryEntry, StudioImage } from './types';

/**
 * Three example generations so the app is demoable before the first API call.
 * The imagery is drawn inline as SVG -- small enough to survive localStorage,
 * and no network dependency for a cold start.
 */

function uri(svg: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg.replace(/\s{2,}/g, ' '))}`;
}

function swatch(a: string, b: string, motif: 'adire' | 'aso-oke' | 'plain'): string {
  const pattern =
    motif === 'adire'
      ? `<g fill="none" stroke="${b}" stroke-width="1.4" opacity="0.85">
           <circle cx="20" cy="20" r="6"/><circle cx="20" cy="20" r="11"/>
           <circle cx="60" cy="60" r="6"/><circle cx="60" cy="60" r="11"/>
           <path d="M0 40h80M40 0v80"/>
         </g>`
      : motif === 'aso-oke'
        ? `<g stroke="${b}" stroke-width="3" opacity="0.9">
             <path d="M8 0v80M26 0v80M52 0v80M70 0v80"/>
           </g>
           <g stroke="${b}" stroke-width="1" opacity="0.45">
             <path d="M0 14h80M0 46h80"/>
           </g>`
        : `<g stroke="${b}" stroke-width="1" opacity="0.35">
             <path d="M0 10h80M0 30h80M0 50h80M0 70h80"/>
           </g>`;

  return uri(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 80 80">
    <rect width="80" height="80" fill="${a}"/>
    <pattern id="w" width="4" height="4" patternUnits="userSpaceOnUse">
      <path d="M0 0h4M0 2h4" stroke="${b}" stroke-width="0.4" opacity="0.25"/>
    </pattern>
    <rect width="80" height="80" fill="url(#w)"/>
    ${pattern}
  </svg>`);
}

function figure(ground: string, cloth: string, accent: string, label: string): string {
  return uri(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1200" viewBox="0 0 200 300">
    <rect width="200" height="300" fill="${ground}"/>
    <g opacity="0.5" stroke="${accent}" stroke-width="0.5">
      <path d="M0 240h200M0 60h200"/>
    </g>
    <circle cx="100" cy="62" r="22" fill="${cloth}" opacity="0.95"/>
    <path d="M100 86c-30 0-52 16-56 44l-10 96c-1 10 6 16 16 16h100c10 0 17-6 16-16l-10-96c-4-28-26-44-56-44z" fill="${cloth}"/>
    <path d="M62 120l-22 74M138 120l22 74" stroke="${accent}" stroke-width="2" opacity="0.55" fill="none"/>
    <path d="M100 92v150" stroke="${accent}" stroke-width="1" opacity="0.35"/>
    <text x="100" y="278" font-family="monospace" font-size="9" fill="${accent}"
      text-anchor="middle" opacity="0.75">${label}</text>
  </svg>`);
}

function image(id: string, url: string, w: number, h: number, fileName: string): StudioImage {
  return {
    id,
    url: '',
    previewUrl: url,
    fileName,
    bytes: 0,
    width: w,
    height: h,
    contentType: 'image/svg+xml',
  };
}

const ADIRE = swatch('#1d2f5e', '#cfd8ef', 'adire');
const ASO_OKE = swatch('#5a2118', '#e6c98a', 'aso-oke');
const LINEN = swatch('#d8cfbc', '#8d8574', 'plain');

const MODEL_A = figure('#171b26', '#2b3350', '#8f9ab8', 'model_01.jpg');
const MODEL_B = figure('#141821', '#333a4d', '#8f9ab8', 'model_02.jpg');

const RESULT_ADIRE = figure('#10141d', '#1d2f5e', '#cfd8ef', 'output_0.png');
const RESULT_ASO = figure('#12111a', '#5a2118', '#e6c98a', 'output_0.png');
const RESULT_LINEN = figure('#101319', '#d8cfbc', '#8d8574', 'output_0.png');

const HOUR = 3_600_000;

export function seedHistory(now = Date.now()): HistoryEntry[] {
  return [
    {
      id: 'seed-adire',
      createdAt: now - 40 * 60_000,
      predictionId: 'pred_demo_adire',
      operation: 'tryon',
      status: 'completed',
      outputs: [RESULT_ADIRE],
      thumbnail: RESULT_ADIRE,
      productImage: image('seed-adire-p', ADIRE, 1400, 1400, 'indigo-adire.jpg'),
      modelImage: image('seed-adire-m', MODEL_A, 1000, 1500, 'model_01.jpg'),
      params: {
        garmentType: 'agbada',
        fabricTemplate: 'strict',
        fabricScope: 'full-set',
        prompt: fabricPrompt('agbada'),
        promptOverridden: false,
        resolution: '2k',
        generationMode: 'balanced',
        seed: 42,
        numImages: 1,
        outputFormat: 'png',
        privacy: false,
      },
      creditCost: creditCost('balanced', '2k', 1),
      label: 'Agbada in indigo adire',
    },
    {
      id: 'seed-aso-oke',
      createdAt: now - 3 * HOUR,
      predictionId: 'pred_demo_aso',
      operation: 'tryon',
      status: 'completed',
      outputs: [RESULT_ASO],
      thumbnail: RESULT_ASO,
      productImage: image('seed-aso-p', ASO_OKE, 1200, 1600, 'aso-oke-stripe.jpg'),
      modelImage: image('seed-aso-m', MODEL_B, 1000, 1500, 'model_02.jpg'),
      params: {
        garmentType: 'kaftan',
        fabricTemplate: 'concise',
        fabricScope: 'outer-only',
        prompt:
          'Remake the kaftan in this fabric, keeping the original cut and drape. ' +
          'Run the stripe vertically down the body and align it across the seams.',
        promptOverridden: true,
        resolution: '4k',
        generationMode: 'quality',
        seed: 90210,
        numImages: 1,
        outputFormat: 'png',
        privacy: false,
      },
      creditCost: creditCost('quality', '4k', 1),
      label: 'Kaftan in aso-oke stripe',
    },
    {
      id: 'seed-linen',
      createdAt: now - 27 * HOUR,
      predictionId: 'pred_demo_linen',
      operation: 'tryon',
      status: 'completed',
      outputs: [RESULT_LINEN],
      thumbnail: RESULT_LINEN,
      productImage: image('seed-linen-p', LINEN, 1500, 1500, 'linen-shirt-flatlay.jpg'),
      modelImage: image('seed-linen-m', MODEL_A, 1000, 1500, 'model_01.jpg'),
      params: {
        garmentType: 'shirt',
        fabricTemplate: 'concise',
        fabricScope: 'full-set',
        prompt: fabricPrompt('shirt', 'concise', 'full-set'),
        promptOverridden: false,
        resolution: '1k',
        generationMode: 'fast',
        seed: 42,
        numImages: 1,
        outputFormat: 'jpeg',
        privacy: false,
      },
      creditCost: creditCost('fast', '1k', 1),
      label: 'Shirt in plain linen',
    },
  ];
}
