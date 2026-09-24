"""Prompt composition for fabric remakes.

The studio composes its prompt from a template and the garment-type selector.
The customer can take the wheel at any point via Advanced -> Prompt, and once
they do we stop rewriting it.

Three templates ship:

- ``strict``       the default. A structural directive that treats the model
                   photo as a template rather than inspiration, pinning
                   silhouette, construction, identity, pose and camera, and
                   remaking every layer of the outfit in the uploaded cloth.
- ``coordinated``  a shorter designer brief aimed squarely at colour harmony.
                   Worth trying when the structural directive starts diluting.
- ``concise``      a single sentence, as an A/B floor.

Coverage is a separate axis for ``strict`` and ``concise``. ``full-set``
remakes every layer -- headwear, main garment, inner layer, lower garment and
the embroidery -- so the result reads as one coordinated outfit.
``outer-only`` changes the main garment and leaves the rest in their reference
colours.
"""

GARMENT_TYPES = [
    {"value": "agbada", "label": "Agbada"},
    {"value": "kaftan", "label": "Kaftan"},
    {"value": "senator", "label": "Senator"},
    {"value": "suit", "label": "Suit"},
    {"value": "dress", "label": "Dress"},
    {"value": "shirt", "label": "Shirt"},
    {"value": "two-piece", "label": "Two-piece"},
    {"value": "custom", "label": "Custom"},
]

FABRIC_TEMPLATES = [
    {"value": "universal", "label": "Universal", "note": "any garment"},
    {"value": "strict", "label": "Structural", "note": "full directive"},
    {"value": "coordinated", "label": "Designer", "note": "colour first"},
    {"value": "concise", "label": "Concise", "note": "one sentence"},
]

TEMPLATE_VALUES = tuple(t["value"] for t in FABRIC_TEMPLATES)

FABRIC_SCOPES = [
    {"value": "full-set", "label": "Full set", "note": "cap + all layers"},
    {"value": "outer-only", "label": "Outer only", "note": "robe alone"},
]

# Garment vocabulary. Every template interpolates from here, so a template
# reads correctly for a suit or a dress and never talks about a trouser cut on
# a garment that has no trousers.
#
#   phrase     how the piece is named in prose: "the same {phrase}"
#   pieces     every layer whose material changes, as one list
#   headwear   headwear clause subject, sentence-initial
#   secondary  layers other than the main garment and the headwear
#   details    construction specifics worth naming for this piece
VOCAB = {
    "agbada": {
        "phrase": "agbada and trousers",
        "pieces": "the outer agbada, the inner buba, the sokoto trousers and the fila cap",
        "headwear": "The fila cap",
        "secondary": "the inner buba and the sokoto trousers",
        "details": ("sleeve proportions, neckline, embroidery placement, side openings, "
                    "the trouser cut and the cap's shape"),
    },
    "kaftan": {
        "phrase": "kaftan",
        "pieces": "the kaftan, any inner top worn beneath it, the trousers and any cap",
        "headwear": "Any cap",
        "secondary": "the inner top and the trousers",
        "details": ("sleeve proportions, neckline, embroidery placement, side vents, "
                    "the trouser cut and the cap's shape"),
    },
    "senator": {
        "phrase": "senator top and trousers",
        "pieces": "the senator top, the matching trousers and any cap",
        "headwear": "Any cap",
        "secondary": "the trousers",
        "details": ("sleeve proportions, collar and neckline, embroidery placement, "
                    "the placket, side vents and the trouser cut"),
    },
    "suit": {
        "phrase": "suit jacket and trousers",
        "pieces": "the jacket, the trousers and any waistcoat",
        "headwear": "Any hat",
        "secondary": "the waistcoat and the trousers",
        "details": ("lapel shape and width, button stance, sleeve length and cuff, vents, "
                    "pocket placement and the trouser cut"),
    },
    "dress": {
        "phrase": "dress",
        "pieces": "the dress and any matching headwrap, sash, belt or overlay",
        "headwear": "Any headwrap",
        "secondary": "any sash, belt or overlay",
        "details": ("neckline, sleeve construction, waist seam, skirt fullness, hem length "
                    "and any overlay"),
    },
    "shirt": {
        "phrase": "shirt",
        "pieces": "the shirt and any matching cap, trousers or wrap worn with it",
        "headwear": "Any cap",
        "secondary": "any matching trousers or wrap",
        "details": "collar shape, placket, cuff construction, yoke, pocket placement and hem",
    },
    "two-piece": {
        "phrase": "two-piece set",
        "pieces": "the top, the matching trousers or skirt, and any cap or wrap",
        "headwear": "Any cap or wrap",
        "secondary": "the lower piece",
        "details": ("neckline, sleeve construction, hem lengths, the waistband and the cut "
                    "of the lower piece"),
    },
    "custom": {
        "phrase": "outfit",
        "pieces": ("every layer of the outfit, including any inner layer, lower garment "
                   "and head covering"),
        "headwear": "Any head covering",
        "secondary": "the remaining layers",
        "details": ("necklines, sleeve construction, hems, fastenings, seam placement and "
                    "the cut of every layer"),
    },
}


def vocab(garment):
    return VOCAB.get(garment, VOCAB["custom"])


def _lower(clause):
    """Lowercases a sentence-initial clause for use mid-sentence."""
    return clause[:1].lower() + clause[1:]


def strict_prompt(garment, scope="full-set"):
    """The default.

    A structural directive that treats the model photo as a template rather
    than inspiration, and remakes every layer of the outfit -- main garment,
    inner layer, lower garment and headwear -- in the uploaded cloth, so
    nothing is left in the colour it had in the reference.
    """
    v = vocab(garment)
    full_set = scope == "full-set"

    if full_set:
        objective = (
            "Treat the person's photo as a strict structural template, and the fabric image "
            "as the material source. Produce a photorealistic image of the same person wearing "
            "the same %s as one complete, coordinated set cut from the uploaded fabric: %s are "
            "all remade in that cloth." % (v["phrase"], v["pieces"])
        )
    else:
        objective = (
            "Treat the person's photo as a strict structural and visual template, and the fabric "
            "image as the material source. Produce a photorealistic image of the same person "
            "wearing the same %s, reconstructed so it reads as genuinely manufactured from the "
            "uploaded fabric. Change the main garment only; every other layer keeps the colour it "
            "has in the reference." % v["phrase"]
        )

    # The shape is preserved. Whether the colour is preserved depends on scope,
    # so the two lists are kept apart -- a single "preserve everything" list is
    # what makes a model leave the cap in its original colour.
    preserve_shape = (
        "PRESERVE THE SHAPE, HIGHEST PRIORITY. Keep exactly: garment type, overall silhouette, "
        "length, width and proportions, neckline, sleeves and sleeve construction, shoulder "
        "structure, front opening and placket, the position and stitch pattern of all embroidery, "
        "the position of decorative panels, seams and garment boundaries, layering, the cut of the "
        "lower garment, the shape and fold of any cap or head covering, footwear, the person's "
        "identity and facial appearance, pose and body position, camera angle, framing and "
        "composition. Do not redesign, modernise, simplify or reinterpret the garment. The "
        "reference is a template, not inspiration."
    )

    if full_set:
        coordinated_set = (
            "COORDINATED SET. Every garment layer changes material: %s. %s is cut from the same "
            "cloth as the main garment, in the same print at a scale suited to its size. The other "
            "layers -- %s -- are made either from the same fabric or from a solid tone drawn from "
            "the fabric's own dominant palette, so they read as bought together. Embroidery keeps "
            "its exact position and stitch structure but is recoloured to a tone from that same "
            "palette. No garment element keeps the colour it had in the reference photo. Footwear, "
            "eyewear, watch and jewellery are the only things that stay as they are."
            % (v["pieces"], v["headwear"], v["secondary"])
        )
    else:
        coordinated_set = (
            "SCOPE. Change the main %s only. %s, %s, the embroidery colour, footwear and "
            "accessories all stay exactly as they appear in the reference photo."
            % (v["phrase"], v["headwear"], v["secondary"])
        )

    if full_set:
        construction = (
            "CONSTRUCTION. Retain the exact construction of the reference %s: %s. Construction and "
            "placement are fixed; material and colour are what change." % (v["phrase"], v["details"])
        )
    else:
        construction = (
            "CONSTRUCTION. Retain the exact construction of the reference %s: %s. Only the main "
            "garment's material changes, unless the fabric itself carries decorative elements that "
            "naturally become part of its surface." % (v["phrase"], v["details"])
        )

    do_not = (
        "DO NOT create a new outfit, change the garment style or silhouette, shorten or lengthen "
        "it, add or remove sleeves, invent embroidery or decoration, substitute a similar-looking "
        "fabric, distort the body, change the pose or the face, or generate a generic fashion model."
    )
    if full_set:
        do_not += (
            " Do not leave %s, %s or the embroidery in the colour they had in the reference photo "
            "-- a single layer left in the old colour is a failed result."
            % (_lower(v["headwear"]), v["secondary"])
        )

    return "\n\n".join([
        objective,
        preserve_shape,
        coordinated_set,
        ("FABRIC, MATERIAL SOURCE. Take from the fabric image: its exact dominant colours, pattern, "
         "motifs, repeating geometry, texture, weave appearance, material character, pattern scale "
         "and pattern density. Carry the fabric across every surface it covers so it follows the "
         "real shape, seams, folds, sleeves, torso and perspective. Do not paste the fabric flat "
         "over the person; it must behave like real cloth."),
        ("PATTERN PRESERVATION. Keep the recognisable identity of the uploaded fabric. Do not "
         "invent a different pattern, substitute a generic print, or blur, simplify or regenerate "
         "the motifs. Hold pattern scale and orientation consistent across connected areas, while "
         "allowing the natural distortion that construction, folds and perspective produce."),
        construction,
        ("PERSON AND POSE. Do not change the face, skin tone, hairstyle, beard, body proportions, "
         "pose, hand position, footwear or camera position. It must read as the same person "
         "photographed in the same setup."),
        ("PHOTOREALISM. High-end fashion photography: realistic folds, natural fabric tension, "
         "accurate shadows, correct occlusion around the arms and body, believable seams, "
         "realistic draping, physically consistent lighting and natural textile texture."),
        ("ON CONFLICT, IN ORDER: 1) preserve the person and pose, 2) preserve the garment "
         "silhouette and construction, 3) preserve garment details and proportions, 4) preserve "
         "the fabric's pattern, colours and texture, 5) apply realistic fabric behaviour and "
         "lighting, 6) improve photographic realism."),
        do_not,
    ])


def coordinated_prompt(garment):
    """A designer brief rather than a constraint list.

    Shorter, and sometimes lands colour coordination better when the
    structural directive starts diluting.
    """
    v = vocab(garment)

    return "\n\n".join([
        ("ROLE. You are a professional fashion designer and image editor. Apply the uploaded "
         "fabric to the entire outfit, including the headwear and all embroidery, with perfect "
         "colour harmony and material consistency."),
        ("INPUTS. Fabric image: the fabric to use, including its pattern, colours, texture and "
         "material. Garment image: the model wearing the original outfit, including the "
         "silhouette, style, embroidery placement and design details."),
        ("TASK. Generate a new image of the same model in the same pose, wearing the same %s, with "
         "these changes:\n"
         "1. Use the uploaded fabric to remake the entire outfit.\n"
         "2. %s must be remade using the same fabric.\n"
         "3. All embroidery, decorative panels and accents must be recoloured or recreated using "
         "colours taken from the uploaded fabric, so that everything matches perfectly.\n"
         "4. Do not keep any element in the colour it had in the reference photo, or in any colour "
         "that does not exist in the uploaded fabric.\n"
         "5. Ensure %s, together with the embroidery, all look as though they were made from the "
         "same fabric collection.\n"
         "6. Preserve the exact outfit style, cut, structure, length and embroidery placement.\n"
         "7. Preserve the model's identity, pose, facial expression and background."
         % (v["phrase"], v["headwear"], v["pieces"])),
        ("VISUAL GUIDELINES. The final look must be clean, realistic and professionally lit. "
         "Pattern alignment should look natural on folds and curves. Embroidery must blend "
         "seamlessly with the fabric and must not look pasted on. The headwear and embroidery "
         "should look intentionally matched to the outfit, not edited afterwards. Maintain "
         "realistic textile texture, folds, shadows and fabric behaviour. The uploaded fabric's "
         "original colours and pattern must remain clearly recognisable."),
        ("OUTPUT. A single high-quality, photorealistic image of the model wearing the fully "
         "coordinated outfit. The result should look as though the entire outfit -- %s, and the "
         "embroidery -- was originally designed and professionally tailored from the uploaded "
         "fabric." % v["pieces"]),
    ])


def concise_prompt(garment, scope="full-set"):
    v = vocab(garment)
    base = (
        "Remake the %s in this fabric, preserving the original cut, drape and embroidery "
        "placement. Match the print scale to the body and let the pattern follow the folds and "
        "seams." % v["phrase"]
    )
    if scope != "full-set":
        return base
    return base + (
        " Remake %s in the same cloth, and recolour the embroidery to a tone from the fabric's "
        "palette, so the whole outfit reads as one coordinated set. Leave footwear and accessories "
        "alone." % v["pieces"]
    )


# ---------------------------------------------------------------- universal --
# Supplied by the shop. Unlike the other three, this one does not interpolate
# the garment-type selector: it asks the model to identify every visible
# garment component itself, which is why it reads the same for an agbada and a
# mermaid gown. Kept verbatim rather than paraphrased -- it is the shop's own
# text, and the section numbering is load-bearing for the priority list at the
# end.
UNIVERSAL_PROMPT = """UNIVERSAL FABRIC-TO-GARMENT GENERATION PROMPT

ROLE
You are an expert fashion designer, garment construction specialist, and photorealistic image editor.
Your task is to transform the clothing worn by the person in the GARMENT REFERENCE IMAGE using the UPLOADED FABRIC IMAGE, while preserving the original garment's design, construction, proportions, and the person's appearance.
The garment reference is a strict structural template.
The fabric image is the material, color, pattern, and texture source.
The goal is to make the result look as though the original outfit was professionally designed and manufactured using the uploaded fabric.

1. GARMENT REFERENCE - STRICT TEMPLATE
Analyze the reference image and identify every visible garment and garment layer, regardless of clothing type.
This may include, but is not limited to:
* Dresses
* Gowns
* Shirts
* Blouses
* Trousers
* Skirts
* Jackets
* Blazers
* Suits
* Coats
* Kaftans
* Tunics
* Agbada
* Buba
* Sokoto
* Traditional garments
* Headwear
* Caps
* Scarves
* Matching sets
* Layered garments
* Sleeves
* Waistbands
* Collars
* Cuffs
* Pockets
* Plackets
* Decorative panels
* Embroidery
* Applique
* Trim
* Borders
* Other visible garment components
Treat the identified garment structure as fixed.
Do not redesign the outfit.
Do not create a new fashion concept.
Do not reinterpret the garment.
Do not use the reference merely as inspiration.
The output must represent the same clothing design reconstructed using the uploaded fabric.

2. PRESERVE GARMENT STRUCTURE - HIGHEST PRIORITY
Preserve the reference garment as accurately as possible.
Keep:
* Garment type
* Overall silhouette
* Length
* Width
* Proportions
* Fit
* Neckline
* Collar
* Sleeves
* Sleeve length
* Sleeve construction
* Shoulder structure
* Waistline
* Hemline
* Front opening
* Buttons
* Zippers
* Plackets
* Pockets
* Seams
* Panels
* Pleats
* Folds
* Darts
* Stitch lines
* Decorative borders
* Embroidery placement
* Applique placement
* Garment layering
* Matching pieces
* Trousers/skirt/shorts cut
* Headwear shape
* Any other identifiable construction details
Preserve the exact relationship between all garment components.
If the reference contains multiple coordinated pieces, maintain the same complete outfit structure.
Do not shorten, lengthen, widen, narrow, redesign, modernize, simplify, or reinterpret the garments.

3. FABRIC IMAGE - MATERIAL SOURCE
Use the uploaded fabric image as the primary source for:
* Colors
* Color relationships
* Pattern
* Motifs
* Repeating geometry
* Texture
* Weave
* Material appearance
* Pattern scale
* Pattern density
* Surface characteristics
* Decorative characteristics contained within the fabric
The uploaded fabric should remain clearly recognizable in the final garment.
Do not substitute it with a generic fabric.
Do not create a vaguely similar pattern.
Do not invent a completely different textile.

4. APPLY THE FABRIC TO THE ENTIRE OUTFIT
Apply the uploaded fabric appropriately to all garment pieces that should logically be made from the same material.
This includes every applicable visible component such as:
* Main garment
* Matching top
* Matching bottom
* Jacket
* Blazer
* Skirt
* Trousers
* Sleeves
* Waistbands
* Cuffs
* Collars
* Pockets
* Panels
* Headwear
* Cap
* Scarf
* Other coordinated fabric components
Do not leave an obvious garment component in the original reference color unless it is intentionally designed as a contrasting component.
The final outfit should look like a single professionally coordinated fashion collection.

5. INTELLIGENT COLOR COORDINATION
Analyze the dominant and secondary colors contained within the uploaded fabric.
Use those colors to coordinate all garment components.
If the reference contains embroidery, trim, piping, decorative panels, borders, or other colored details:
* Preserve their exact position.
* Preserve their shape.
* Preserve their construction.
* Preserve their stitch/design structure.
* Recolor them using appropriate colors from the uploaded fabric's palette.
Choose colors that naturally complement the uploaded textile.
Do not retain an old garment color simply because it existed in the reference.
For example, if the reference garment is purple but the uploaded fabric contains burgundy, gold, cream and black, do not leave visible purple garment components behind.
Instead, intelligently coordinate the outfit using the fabric's actual palette.

6. COORDINATED SECONDARY GARMENTS
When the outfit contains multiple pieces, intelligently determine how they should coordinate.
For example:
Same fabric where appropriate:
* Main garment
* Matching trousers
* Matching skirt
* Matching jacket
* Matching cap
* Matching scarf
Solid complementary color where appropriate:
* Inner shirt
* Lining
* Undershirt
* Base garment
* Secondary layer
Any solid color must be selected from the uploaded fabric's own dominant or complementary palette.
Do not introduce unrelated colors.
The result must look intentionally designed as one coordinated outfit.

7. HEADWEAR
If the reference contains a cap, hat, fila, scarf, turban, headwrap, or other fabric-based head covering:
Preserve its:
* Shape
* Size
* Construction
* Position
* Fold structure
* Relationship to the outfit
Where appropriate, remake it using the uploaded fabric.
Use the fabric at a scale appropriate for the smaller surface area.
Do not simply shrink the original fabric image onto the headwear.
The headwear must look physically manufactured from the same textile.

8. EMBROIDERY AND DECORATION
Preserve the exact:
* Position
* Shape
* Layout
* Scale
* Stitch structure
* Decorative geometry
* Relationship to garment construction
However, recolor or adapt the embroidery, trim, piping, borders, and decorative accents so they harmonize with the uploaded fabric.
Use colors derived from the uploaded fabric.
The embroidery must look intentionally designed for the new fabric.
It must not look like leftover decoration from the original garment.
Do not invent large new decorative elements that were not present in the reference.

9. PATTERN PRESERVATION
Preserve the recognizable identity of the uploaded fabric.
Maintain:
* Correct motif shapes
* Correct colors
* Correct pattern characteristics
* Consistent pattern scale
* Consistent pattern density
* Appropriate orientation
The pattern should naturally follow:
* Garment seams
* Sleeves
* Curves
* Folds
* Draping
* Body contours
* Perspective
* Individual garment panels
Allow realistic distortion where required by the garment's physical construction.
Do not stretch the pattern unnaturally.
Do not randomly rotate motifs.
Do not blur or simplify the fabric.
Do not replace the pattern with an AI-generated approximation.

10. REALISTIC GARMENT CONSTRUCTION
The final clothing must look physically manufactured from real fabric.
Maintain realistic:
* Seams
* Stitching
* Fold behavior
* Fabric tension
* Draping
* Wrinkles
* Compression
* Shadows
* Overlapping layers
* Occlusion
* Sleeve behavior
* Hem behavior
* Pattern continuity
The fabric must conform to the actual three-dimensional shape of the garment.
It must NOT appear as a flat texture pasted onto the person.

11. PERSON - PRESERVE EXACTLY
Preserve the same person from the reference image.
Do not change:
* Face
* Facial identity
* Skin tone
* Hairstyle
* Hair
* Beard
* Body proportions
* Body shape
* Pose
* Hand position
* Leg position
* Facial expression
* Accessories
The person should look like the same individual photographed in the same session.

12. PRESERVE NON-FABRIC ACCESSORIES
Do not unnecessarily modify items that are not made from the garment fabric.
Preserve where applicable:
* Shoes
* Eyeglasses
* Watches
* Jewellery
* Belts
* Bags
* Other clearly non-textile accessories
These should remain unchanged unless the reference clearly indicates that they are part of the garment design.

13. CAMERA AND COMPOSITION
Preserve:
* Camera angle
* Perspective
* Framing
* Crop
* Subject position
* Body position
* Background
* Lighting direction
* Overall photographic composition
Do not turn the image into a different photoshoot.
The final image should look like the same photograph after the clothing has been professionally redesigned using the uploaded fabric.

14. PHOTOREALISM
Generate a high-end, photorealistic fashion photograph.
The final result must have:
* Realistic textile texture
* Natural folds
* Realistic fabric tension
* Accurate shadows
* Correct lighting
* Natural garment draping
* Realistic seams
* Correct occlusion
* Natural pattern distortion
* Physically believable clothing
* High-quality photographic detail
The fabric should look tangible and wearable.

15. IMPORTANT RULE FOR ORIGINAL COLORS
Do not leave accidental remnants of the original garment colors.
After the transformation, inspect every visible garment component.
If an original garment component was blue, purple, red, green, white, etc., determine whether that color exists naturally within the uploaded fabric.
If it does not, replace or recolor that component using an appropriate color from the uploaded fabric's palette.
A visible original-color component should remain only when it is clearly a non-fabric accessory or when the garment design intentionally requires a contrasting solid component.

16. DO NOT
Do not:
* Create a completely new outfit.
* Change the garment style.
* Change the silhouette.
* Change garment proportions.
* Change the person's body.
* Change the person's face.
* Change the person's pose.
* Change the camera angle.
* Change the garment construction.
* Remove important garment details.
* Add random embroidery.
* Invent random decorative elements.
* Substitute the uploaded fabric with another fabric.
* Use a generic version of the uploaded pattern.
* Flatten the fabric onto the body.
* Distort the fabric pattern excessively.
* Leave unexplained original garment colors.
* Generate a generic fashion model.
* Treat the reference as inspiration rather than a template.

17. PRIORITY ORDER
When instructions conflict, follow this priority:
1. Preserve the person's identity and pose
2. Preserve the garment silhouette and construction
3. Preserve garment details and proportions
4. Preserve the uploaded fabric's colors, pattern and texture
5. Apply intelligent color coordination to secondary garments and decoration
6. Apply realistic fabric behavior
7. Maximize photorealism

FINAL INSTRUCTION
Create one high-quality, photorealistic image of the same person wearing the same outfit from the reference image, reconstructed using the uploaded fabric.
The result must look as though the original outfit was professionally tailored from the uploaded textile.
The reference image determines WHAT is being worn.
The fabric image determines WHAT the garments are made from.
The AI must intelligently identify the garment type and all visible garment components rather than assuming a specific clothing style.
Every applicable fabric-based component should belong to the same coordinated design language, with matching colors, materials, patterns and decorative details.
The final result must look intentional, professionally designed, physically realistic, and ready for presentation to a fashion customer."""


# ------------------------------------------------------------- dress mode --
# A garment-specific specialisation of the universal brief, supplied by the
# shop. A dress fails in two ways a robe does not, and this text is aimed at
# both: the model reads bodice and skirt as separate garments and re-textures
# only one, and -- once told to cover everything -- it goes the other way and
# flattens a solid-plus-lace-plus-print dress into a single print. Sections 2,
# 3 and 5 carry the material-zone hierarchy that stops the flattening, so they
# are kept verbatim.
DRESS_MODE_PROMPT = """DRESS FABRIC TRANSFORMATION - STRICT CONSTRUCTION LOCK

ROLE:
You are an expert fashion garment reconstruction and textile replacement system.

INPUTS:

GARMENT PHOTO:
The garment photo is the absolute structural reference.

FABRIC PHOTO:
The fabric photo is the material and color reference.

OBJECTIVE:

Recreate the SAME PERSON wearing the SAME DRESS from the garment photo.

Do NOT redesign the dress.

Do NOT reinterpret the dress.

Do NOT simplify the dress.

Do NOT create a new dress inspired by the reference.

The ONLY intended change is the textile/color treatment of the dress according to the uploaded fabric.

==================================================
1. STRUCTURE IS LOCKED
==================================================

The reference photograph is a STRICT GARMENT BLUEPRINT.

Before generating the result, identify the dress construction.

Lock and preserve:

- exact silhouette
- exact dress length
- exact proportions
- neckline shape
- collar
- bodice shape
- waist position
- waist shaping
- sleeve type
- sleeve length
- sleeve width
- sleeve flare
- sleeve volume
- shoulder construction
- skirt shape
- skirt width
- skirt flare
- hemline
- ruffles
- pleats
- gathers
- panels
- seams
- darts
- decorative sections
- overlays
- transparent sections
- lace sections
- fabric boundaries
- color/material boundaries

These characteristics MUST remain unchanged.

The generated garment must have the SAME CONSTRUCTION as the reference.

==================================================
2. MATERIAL ZONES MUST BE PRESERVED
==================================================

IMPORTANT:

A dress can contain multiple materials.

Do NOT assume that every visible part of the dress must become the uploaded fabric.

First identify the different material zones in the reference.

For example:

ZONE A:
Opaque main dress fabric.

ZONE B:
Contrasting solid fabric.

ZONE C:
Lace.

ZONE D:
Mesh or transparent material.

ZONE E:
Decorative embroidery or appliqué.

ZONE F:
Non-fabric accessories.

Each zone must retain its original STRUCTURAL ROLE.

The uploaded fabric should replace the appropriate textile zones WITHOUT destroying the original material hierarchy.

==================================================
3. LACE AND TRANSPARENT MATERIAL LOCK
==================================================

If the reference contains:

- lace
- transparent lace
- mesh
- tulle
- net
- sheer sleeves
- sheer neckline
- transparent overlay

DO NOT convert these areas into opaque printed fabric.

Preserve:

- transparency
- lace appearance
- lace pattern
- sheer quality
- sleeve construction
- neckline construction
- placement
- boundaries

The lace must remain visually identifiable as lace.

The uploaded fabric may be used for the opaque garment underneath or adjacent to the lace, but DO NOT remove the lace simply because the uploaded fabric is being applied.

==================================================
4. FABRIC REPLACEMENT
==================================================

Replace the ORIGINAL OPAQUE DRESS TEXTILE with the uploaded fabric.

Apply the uploaded fabric to the appropriate opaque areas of the dress.

The uploaded fabric should replace the original garment textile while preserving the exact shape and construction.

The transformation should therefore behave like:

ORIGINAL DRESS DESIGN
+
NEW FABRIC
=
SAME DRESS, DIFFERENT TEXTILE

NOT:

ORIGINAL DRESS
+
NEW FABRIC
=
NEW DRESS DESIGN

==================================================
5. PRESERVE THE REFERENCE'S MATERIAL HIERARCHY
==================================================

If the original dress contains:

SOLID + PRINT + LACE

the result should still contain:

NEW FABRIC + COORDINATED SOLID + LACE

If the original dress contains:

PRINT + LACE

the result should contain:

UPLOADED PRINT + LACE

If the original dress contains:

SOLID + LACE

the result should contain:

COORDINATED SOLID FROM FABRIC PALETTE + LACE

Do not flatten multiple materials into one material.

Do not turn lace into printed fabric.

Do not turn transparent material into opaque fabric.

==================================================
6. COLOUR COORDINATION
==================================================

Where the reference contains a solid-color garment section, replace its original color with a coordinated color derived from the uploaded fabric's palette when appropriate.

Example:

If the original dress contains burgundy solid fabric and the uploaded fabric contains:

- burgundy
- cream
- black
- gold

the solid section may become burgundy, cream, black, or another appropriate tone from the uploaded fabric palette.

However, preserve the original solid section's location and construction.

Do not replace a solid section with a printed section unless specifically required.

==================================================
7. FABRIC PATTERN PRESERVATION
==================================================

Use the uploaded fabric as the exact pattern source.

Preserve:

- motifs
- colors
- geometry
- pattern density
- pattern identity
- realistic pattern scale

The uploaded fabric must remain recognizable.

Do not create a generic substitute pattern.

Do not invent new motifs.

Do not simplify the pattern.

Do not blur the pattern.

==================================================
8. PATTERN MUST FOLLOW THE GARMENT
==================================================

The fabric pattern must conform naturally to the existing garment.

Respect:

- seams
- darts
- folds
- curves
- sleeves
- waist shaping
- ruffles
- panels
- perspective
- garment tension

The pattern must look printed or woven into the actual cloth.

It must NOT look like a flat image pasted over the person.

==================================================
9. DO NOT CHANGE THE DRESS DESIGN
==================================================

ABSOLUTELY DO NOT:

- change neckline
- change sleeve design
- remove lace
- remove transparent sections
- add sleeves
- remove sleeves
- change sleeve width
- change sleeve flare
- change waist position
- change skirt length
- change skirt width
- change hemline
- add ruffles
- remove ruffles
- add pleats
- remove pleats
- change the silhouette
- turn the dress into a different style
- convert the dress into a two-piece
- redesign the bodice
- redesign the skirt

The reference garment's construction is LOCKED.

==================================================
10. PERSON LOCK
==================================================

Preserve exactly:

- person's identity
- face
- skin tone
- hairstyle
- body proportions
- pose
- hand position
- facial expression
- camera angle
- framing

Do not generate a generic fashion model.

The result must clearly be the same person.

==================================================
11. ACCESSORY LOCK
==================================================

Keep all non-garment accessories unchanged:

- handbag
- shoes
- jewellery
- earrings
- watch
- glasses
- other accessories

Do not redesign accessories.

==================================================
12. FINAL QUALITY CONTROL
==================================================

Before returning the final image, compare the result against the garment reference.

CHECK THE FOLLOWING:

GARMENT SILHOUETTE:
Must match.

NECKLINE:
Must match.

SLEEVES:
Must match.

WAIST:
Must match.

SKIRT:
Must match.

HEMLINE:
Must match.

LACE:
Must remain lace.

TRANSPARENT AREAS:
Must remain transparent.

MATERIAL BOUNDARIES:
Must remain in the same locations.

PERSON:
Must remain the same.

POSE:
Must remain the same.

FABRIC:
Must clearly come from the uploaded fabric.

If the generated result changes any major construction feature, regenerate while restoring the reference construction.

==================================================
FINAL INSTRUCTION
==================================================

Generate the SAME DRESS DESIGN shown in the reference photograph.

Preserve the dress's exact construction, silhouette, proportions, material zones, lace, transparency, sleeves, neckline, waist, skirt and decorative details.

Replace the appropriate opaque dress textile using the uploaded fabric.

Coordinate solid-color areas using colors from the uploaded fabric palette.

KEEP LACE AS LACE.

KEEP SHEER AS SHEER.

KEEP THE DRESS CONSTRUCTION EXACTLY AS SHOWN.

CHANGE THE MATERIAL.

DO NOT CHANGE THE DESIGN.

The final result should look like the original dress was professionally remade by a tailor using the uploaded fabric, while retaining its original construction and material hierarchy."""


# Garment types with a dedicated brief. Anything not listed here falls back to
# the general universal text, so adding a garment is one entry, not a branch.
GARMENT_BRIEFS = {
    "dress": DRESS_MODE_PROMPT,
}


def has_garment_brief(garment):
    return garment in GARMENT_BRIEFS


def universal_prompt(garment=None):
    """The general brief, or a garment's own where one exists.

    A dress fails differently from a robe -- the model reads bodice and skirt
    as two garments and re-textures one of them -- so `dress` carries a
    dedicated brief. Everything else uses the general text, which tells the
    model to identify the garments itself.

    Coverage never applies either way: both briefs remake the whole garment.
    """
    return GARMENT_BRIEFS.get(garment, UNIVERSAL_PROMPT)


def fabric_prompt(garment, template="universal", scope="full-set"):
    if template == "universal":
        return universal_prompt(garment)
    if template == "concise":
        return concise_prompt(garment, scope)
    if template == "strict":
        return strict_prompt(garment, scope)
    # The coordinated brief is inherently full-set, so scope does not apply.
    return coordinated_prompt(garment)


def fabric_edit_prompt(garment, template="universal", scope="full-set"):
    """The retexture instruction used when FABRIC_STRATEGY=edit."""
    v = vocab(garment)

    if template == "universal":
        # The universal brief already frames the reference as the thing being
        # rebuilt, so it needs no re-framing for the edit endpoint.
        return universal_prompt(garment)

    if template == "concise":
        layers = v["pieces"] if scope == "full-set" else "the main %s" % v["phrase"]
        return (
            "Retexture %s with the supplied fabric swatch. Keep the person, pose, lighting, "
            "background, garment silhouette and seam lines exactly as they are. Change only the "
            "cloth: weave, print, colour and pattern scale, wrapping correctly around every fold."
            % layers
        )

    # The edit endpoint takes the person as the base image, so the directive is
    # framed as an edit of what is already there rather than a reconstruction.
    head = (
        "Retexture the %s in this image using the supplied fabric as the material source. Change "
        "nothing but the cloth." % v["phrase"]
    )
    body = strict_prompt(garment, scope) if template == "strict" else coordinated_prompt(garment)
    return head + "\n\n" + body


def default_prompt_for(garment, template="universal", scope="full-set"):
    return fabric_prompt(garment, template, scope)


def scope_applies(template):
    """Coverage is a Structural/Concise axis.

    The designer brief and the universal brief both cover the whole outfit by
    construction, so offering a coverage choice there would be a lie.
    """
    return template not in ("coordinated", "universal")


def garment_applies(template):
    """Whether the garment-type selector feeds this template.

    It feeds every template now. The three composed templates interpolate the
    vocabulary; the universal one uses it to pick a garment-specific brief
    where one exists, and falls back to its general text otherwise.
    """
    return True


# Each template carries its own applicability, so the browser can grey out the
# controls a template ignores without re-implementing these two rules.
for _template in FABRIC_TEMPLATES:
    _template["scopeApplies"] = scope_applies(_template["value"])
    _template["garmentApplies"] = garment_applies(_template["value"])
