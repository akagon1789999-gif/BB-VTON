import type { FabricScope, FabricTemplate, GarmentType } from './types';

/**
 * The studio composes its prompt from a template and the garment-type
 * selector. The user can take the wheel at any point via Advanced -> Prompt,
 * and once they do we stop rewriting it.
 *
 * Three templates ship:
 *
 * - `strict`       the default. A structural directive that treats the model
 *                  photo as a template rather than inspiration, pinning
 *                  silhouette, construction, identity, pose and camera, and
 *                  remaking every layer of the outfit in the uploaded cloth.
 * - `coordinated`  a shorter designer brief aimed squarely at colour harmony.
 *                  Worth trying when the structural directive starts diluting.
 * - `concise`      a single sentence, as an A/B floor.
 *
 * Coverage is a separate axis for `strict` and `concise`. `full-set` remakes
 * every layer -- headwear, main garment, inner layer, lower garment and the
 * embroidery -- so the result reads as one coordinated outfit. `outer-only`
 * changes the main garment and leaves the rest in their reference colours.
 */

export type { FabricScope, FabricTemplate };

/**
 * Garment vocabulary. Every template interpolates from here, so a template
 * reads correctly for a suit or a dress and never talks about a trouser cut on
 * a garment that has no trousers.
 */
interface GarmentVocab {
  /** How the piece is named in prose: "the same {phrase}". */
  phrase: string;
  /** Every layer whose material changes, as one list. */
  pieces: string;
  /** Headwear clause subject, sentence-initial: "{headwear} is cut from...". */
  headwear: string;
  /** Layers other than the main garment and the headwear. Bare noun phrase. */
  secondary: string;
  /** Construction specifics worth naming for this piece. */
  details: string;
}

const VOCAB: Record<GarmentType, GarmentVocab> = {
  agbada: {
    phrase: 'agbada and trousers',
    pieces: 'the outer agbada, the inner buba, the sokoto trousers and the fila cap',
    headwear: 'The fila cap',
    secondary: 'the inner buba and the sokoto trousers',
    details:
      "sleeve proportions, neckline, embroidery placement, side openings, the trouser cut and the cap's shape",
  },
  kaftan: {
    phrase: 'kaftan',
    pieces: 'the kaftan, any inner top worn beneath it, the trousers and any cap',
    headwear: 'Any cap',
    secondary: 'the inner top and the trousers',
    details:
      "sleeve proportions, neckline, embroidery placement, side vents, the trouser cut and the cap's shape",
  },
  senator: {
    phrase: 'senator top and trousers',
    pieces: 'the senator top, the matching trousers and any cap',
    headwear: 'Any cap',
    secondary: 'the trousers',
    details:
      'sleeve proportions, collar and neckline, embroidery placement, the placket, side vents and the trouser cut',
  },
  suit: {
    phrase: 'suit jacket and trousers',
    pieces: 'the jacket, the trousers and any waistcoat',
    headwear: 'Any hat',
    secondary: 'the waistcoat and the trousers',
    details:
      'lapel shape and width, button stance, sleeve length and cuff, vents, pocket placement and the trouser cut',
  },
  dress: {
    phrase: 'dress',
    pieces: 'the dress and any matching headwrap, sash, belt or overlay',
    headwear: 'Any headwrap',
    secondary: 'any sash, belt or overlay',
    details:
      'neckline, sleeve construction, waist seam, skirt fullness, hem length and any overlay',
  },
  shirt: {
    phrase: 'shirt',
    pieces: 'the shirt and any matching cap, trousers or wrap worn with it',
    headwear: 'Any cap',
    secondary: 'any matching trousers or wrap',
    details: 'collar shape, placket, cuff construction, yoke, pocket placement and hem',
  },
  'two-piece': {
    phrase: 'two-piece set',
    pieces: 'the top, the matching trousers or skirt, and any cap or wrap',
    headwear: 'Any cap or wrap',
    secondary: 'the lower piece',
    details:
      'neckline, sleeve construction, hem lengths, the waistband and the cut of the lower piece',
  },
  custom: {
    phrase: 'outfit',
    pieces:
      'every layer of the outfit, including any inner layer, lower garment and head covering',
    headwear: 'Any head covering',
    secondary: 'the remaining layers',
    details:
      'necklines, sleeve construction, hems, fastenings, seam placement and the cut of every layer',
  },
};

function vocab(garment: GarmentType): GarmentVocab {
  return VOCAB[garment] ?? VOCAB.custom;
}

/** Lowercases a sentence-initial clause for use mid-sentence. */
function lower(clause: string): string {
  return clause.charAt(0).toLowerCase() + clause.slice(1);
}

/**
 * The default. A structural directive that treats the model photo as a
 * template rather than inspiration, and remakes every layer of the outfit --
 * main garment, inner layer, lower garment and headwear -- in the uploaded
 * cloth, so nothing is left in the colour it had in the reference.
 */
function strictPrompt(garment: GarmentType, scope: FabricScope): string {
  const v = vocab(garment);
  const fullSet = scope === 'full-set';

  const objective = fullSet
    ? `Treat the person's photo as a strict structural template, and the fabric image as the material source. Produce a photorealistic image of the same person wearing the same ${v.phrase} as one complete, coordinated set cut from the uploaded fabric: ${v.pieces} are all remade in that cloth.`
    : `Treat the person's photo as a strict structural and visual template, and the fabric image as the material source. Produce a photorealistic image of the same person wearing the same ${v.phrase}, reconstructed so it reads as genuinely manufactured from the uploaded fabric. Change the main garment only; every other layer keeps the colour it has in the reference.`;

  // The shape is preserved. Whether the colour is preserved depends on scope,
  // so the two lists are kept apart -- a single "preserve everything" list is
  // what makes a model leave the cap in its original colour.
  const preserveShape = `PRESERVE THE SHAPE, HIGHEST PRIORITY. Keep exactly: garment type, overall silhouette, length, width and proportions, neckline, sleeves and sleeve construction, shoulder structure, front opening and placket, the position and stitch pattern of all embroidery, the position of decorative panels, seams and garment boundaries, layering, the cut of the lower garment, the shape and fold of any cap or head covering, footwear, the person's identity and facial appearance, pose and body position, camera angle, framing and composition. Do not redesign, modernise, simplify or reinterpret the garment. The reference is a template, not inspiration.`;

  const coordinatedSet = fullSet
    ? `COORDINATED SET. Every garment layer changes material: ${v.pieces}. ${v.headwear} is cut from the same cloth as the main garment, in the same print at a scale suited to its size. The other layers -- ${v.secondary} -- are made either from the same fabric or from a solid tone drawn from the fabric's own dominant palette, so they read as bought together. Embroidery keeps its exact position and stitch structure but is recoloured to a tone from that same palette. No garment element keeps the colour it had in the reference photo. Footwear, eyewear, watch and jewellery are the only things that stay as they are.`
    : `SCOPE. Change the main ${v.phrase} only. ${v.headwear}, ${v.secondary}, the embroidery colour, footwear and accessories all stay exactly as they appear in the reference photo.`;

  const construction = fullSet
    ? `CONSTRUCTION. Retain the exact construction of the reference ${v.phrase}: ${v.details}. Construction and placement are fixed; material and colour are what change.`
    : `CONSTRUCTION. Retain the exact construction of the reference ${v.phrase}: ${v.details}. Only the main garment's material changes, unless the fabric itself carries decorative elements that naturally become part of its surface.`;

  const doNot = fullSet
    ? `DO NOT create a new outfit, change the garment style or silhouette, shorten or lengthen it, add or remove sleeves, invent embroidery or decoration, substitute a similar-looking fabric, distort the body, change the pose or the face, or generate a generic fashion model. Do not leave ${lower(v.headwear)}, ${v.secondary} or the embroidery in the colour they had in the reference photo -- a single layer left in the old colour is a failed result.`
    : `DO NOT create a new outfit, change the garment style or silhouette, shorten or lengthen it, add or remove sleeves, invent embroidery or decoration, substitute a similar-looking fabric, distort the body, change the pose or the face, or generate a generic fashion model.`;

  return [
    objective,
    preserveShape,
    coordinatedSet,
    `FABRIC, MATERIAL SOURCE. Take from the fabric image: its exact dominant colours, pattern, motifs, repeating geometry, texture, weave appearance, material character, pattern scale and pattern density. Carry the fabric across every surface it covers so it follows the real shape, seams, folds, sleeves, torso and perspective. Do not paste the fabric flat over the person; it must behave like real cloth.`,
    `PATTERN PRESERVATION. Keep the recognisable identity of the uploaded fabric. Do not invent a different pattern, substitute a generic print, or blur, simplify or regenerate the motifs. Hold pattern scale and orientation consistent across connected areas, while allowing the natural distortion that construction, folds and perspective produce.`,
    construction,
    `PERSON AND POSE. Do not change the face, skin tone, hairstyle, beard, body proportions, pose, hand position, footwear or camera position. It must read as the same person photographed in the same setup.`,
    `PHOTOREALISM. High-end fashion photography: realistic folds, natural fabric tension, accurate shadows, correct occlusion around the arms and body, believable seams, realistic draping, physically consistent lighting and natural textile texture.`,
    `ON CONFLICT, IN ORDER: 1) preserve the person and pose, 2) preserve the garment silhouette and construction, 3) preserve garment details and proportions, 4) preserve the fabric's pattern, colours and texture, 5) apply realistic fabric behaviour and lighting, 6) improve photographic realism.`,
    doNot,
  ].join('\n\n');
}

/**
 * A designer brief rather than a constraint list. Shorter, and sometimes lands
 * colour coordination better when the structural directive starts diluting.
 */
function coordinatedPrompt(garment: GarmentType): string {
  const v = vocab(garment);

  return [
    `ROLE. You are a professional fashion designer and image editor. Apply the uploaded fabric to the entire outfit, including the headwear and all embroidery, with perfect colour harmony and material consistency.`,

    `INPUTS. Fabric image: the fabric to use, including its pattern, colours, texture and material. Garment image: the model wearing the original outfit, including the silhouette, style, embroidery placement and design details.`,

    `TASK. Generate a new image of the same model in the same pose, wearing the same ${v.phrase}, with these changes:\n1. Use the uploaded fabric to remake the entire outfit.\n2. ${v.headwear} must be remade using the same fabric.\n3. All embroidery, decorative panels and accents must be recoloured or recreated using colours taken from the uploaded fabric, so that everything matches perfectly.\n4. Do not keep any element in the colour it had in the reference photo, or in any colour that does not exist in the uploaded fabric.\n5. Ensure ${v.pieces}, together with the embroidery, all look as though they were made from the same fabric collection.\n6. Preserve the exact outfit style, cut, structure, length and embroidery placement.\n7. Preserve the model's identity, pose, facial expression and background.`,

    `VISUAL GUIDELINES. The final look must be clean, realistic and professionally lit. Pattern alignment should look natural on folds and curves. Embroidery must blend seamlessly with the fabric and must not look pasted on. The headwear and embroidery should look intentionally matched to the outfit, not edited afterwards. Maintain realistic textile texture, folds, shadows and fabric behaviour. The uploaded fabric's original colours and pattern must remain clearly recognisable.`,

    `OUTPUT. A single high-quality, photorealistic image of the model wearing the fully coordinated outfit. The result should look as though the entire outfit -- ${v.pieces}, and the embroidery -- was originally designed and professionally tailored from the uploaded fabric.`,
  ].join('\n\n');
}

function concisePrompt(garment: GarmentType, scope: FabricScope): string {
  const base =
    `Remake the ${vocab(garment).phrase} in this fabric, preserving the ` +
    'original cut, drape and embroidery placement. Match the print scale to ' +
    'the body and let the pattern follow the folds and seams.';

  return scope === 'full-set'
    ? `${base} Remake ${vocab(garment).pieces} in the same cloth, and recolour the ` +
      "embroidery to a tone from the fabric's palette, so the whole outfit " +
      'reads as one coordinated set. Leave footwear and accessories alone.'
    : base;
}

export function fabricPrompt(
  garment: GarmentType,
  template: FabricTemplate = 'strict',
  scope: FabricScope = 'full-set',
): string {
  if (template === 'concise') return concisePrompt(garment, scope);
  if (template === 'strict') return strictPrompt(garment, scope);
  // The coordinated brief is inherently full-set, so scope does not apply.
  return coordinatedPrompt(garment);
}

/** The retexture instruction used when FABRIC_STRATEGY=edit. */
export function fabricEditPrompt(
  garment: GarmentType,
  template: FabricTemplate = 'strict',
  scope: FabricScope = 'full-set',
): string {
  if (template === 'concise') {
    const layers =
      scope === 'full-set' ? vocab(garment).pieces : `the main ${vocab(garment).phrase}`;
    return (
      `Retexture ${layers} with the supplied fabric swatch. ` +
      'Keep the person, pose, lighting, background, garment silhouette and seam ' +
      'lines exactly as they are. Change only the cloth: weave, print, colour and ' +
      'pattern scale, wrapping correctly around every fold.'
    );
  }

  // The edit endpoint takes the person as the base image, so the directive is
  // framed as an edit of what is already there rather than a reconstruction.
  return [
    `Retexture the ${vocab(garment).phrase} in this image using the supplied fabric as the material source. Change nothing but the cloth.`,
    template === 'strict' ? strictPrompt(garment, scope) : coordinatedPrompt(garment),
  ].join('\n\n');
}

export function defaultPromptFor(
  garment: GarmentType,
  template: FabricTemplate = 'strict',
  scope: FabricScope = 'full-set',
): string {
  return fabricPrompt(garment, template, scope);
}

export const FABRIC_SCOPES: { value: FabricScope; label: string; note: string }[] = [
  { value: 'full-set', label: 'Full set', note: 'cap + all layers' },
  { value: 'outer-only', label: 'Outer only', note: 'robe alone' },
];

export const FABRIC_TEMPLATES: { value: FabricTemplate; label: string; note: string }[] = [
  { value: 'strict', label: 'Structural', note: 'full directive' },
  { value: 'coordinated', label: 'Designer', note: 'colour first' },
  { value: 'concise', label: 'Concise', note: 'one sentence' },
];

/** The coordinated brief covers the whole outfit, so Coverage is moot there. */
export function scopeApplies(template: FabricTemplate): boolean {
  return template !== 'coordinated';
}
