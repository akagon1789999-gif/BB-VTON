"""Prompt construction for fabric-to-garment try-on.

FASHN confirmed that `tryon-max` can tailor a garment from a length of cloth
when the product image is the fabric itself — provided the prompt explains the
effect you want. That makes the prompt a load-bearing part of the pipeline
rather than a cosmetic extra, so it is built here from structured data instead
of being pasted together at the call site.

A prompt has four jobs, in this order:

1. Say plainly that the product image is cloth, not a finished garment —
   without this the model tries to fit a rectangle of fabric to the body.
2. Describe the garment to construct, from the outfit record.
3. Describe the fabric in words as well as pixels, from the analysis, so the
   print survives the model's own interpretation.
4. Fence off what must not change: face, body, pose, background.
"""

MAX_PROMPT_CHARS = 900

# Falls back to this when an outfit record carries no description of its own.
GARMENT_FALLBACK = "a well-tailored outfit that covers the body naturally"


def describe_fabric(fabric):
    """A short phrase for the cloth: colours, motif, and hand."""
    processed = (fabric or {}).get("processed") or {}
    metadata = processed.get("metadata") or {}

    colors = [c for c in (fabric or {}).get("primary_colors") or []]
    if not colors:
        colors = [c.get("name") for c in metadata.get("dominantColors", []) if c.get("name")]
    colors = [c for c in colors if c][:3]

    pattern = (fabric or {}).get("pattern_type") or metadata.get("patternType") or ""
    density = metadata.get("patternDensity") or ""
    texture = (fabric or {}).get("texture_description") or metadata.get("texture") or ""

    parts = []
    if colors:
        parts.append(" and ".join(colors))
    if pattern and pattern != "solid":
        motif = "%s %s print" % (density, pattern) if density in ("medium", "high") else "%s print" % pattern
        parts.append(motif.strip())
    elif pattern == "solid":
        parts.append("solid colour")
    phrase = ", ".join(p for p in parts if p)

    if texture:
        # Keep the curated texture note short; it is prose written for humans.
        phrase = "%s (%s)" % (phrase, texture.rstrip(".").lower()[:90]) if phrase else texture
    return phrase or "the fabric shown"


def describe_garment(outfit):
    """The construction brief for the outfit, from the catalogue record."""
    description = (outfit or {}).get("default_prompt") or (outfit or {}).get("description") or ""
    description = description.strip().rstrip(".")
    if description:
        return description
    name = (outfit or {}).get("name")
    return "a %s" % name.lower() if name else GARMENT_FALLBACK


def build_composite_prompt(outfit, fabric, user_prompt=None):
    """Prompt for the composite strategy.

    Here the product image already *is* the garment in the customer's fabric,
    so the prompt must not re-describe the cut and invite a second
    interpretation. Its job is fidelity: wear this, exactly as shown.
    """
    sentences = [
        "The product image is a flat-lay of the finished outfit — %s — already made in the customer's chosen fabric."
        % describe_garment(outfit),
        "Dress the person in exactly this garment, keeping its cut and the fabric's print, colours and motif scale as shown, "
        "with natural drape, folds and shadows on the body.",
        "The fabric is %s." % describe_fabric(fabric),
    ]
    extra = _sentence(user_prompt)
    if extra:
        sentences.append(extra)
    sentences.append(
        "Keep the person's face, body, pose, hands and the background exactly as they are."
    )
    return _clip(" ".join(sentences))


def build_tryon_prompt(outfit, fabric, user_prompt=None):
    """Prompt for `tryon-max` when the product image is the fabric itself."""
    sentences = [
        "The product image is a flat length of fabric, not a finished garment.",
        "Tailor it into %s." % describe_garment(outfit),
        "Cut every panel from this cloth so the whole outfit is made of it, "
        "keeping the print's exact colours, motif shapes and scale, and matching the pattern across seams.",
        "The fabric is %s." % describe_fabric(fabric),
    ]
    extra = _sentence(user_prompt)
    if extra:
        sentences.append(extra)
    sentences.append(
        "Keep the person's face, body, pose, hands and the background exactly as they are."
    )
    return _clip(" ".join(sentences))


def build_edit_prompt(outfit, fabric, user_prompt=None):
    """Prompt for the `edit` model, where the fabric arrives as image_context."""
    sentences = [
        "Dress the person in %s." % describe_garment(outfit),
        "Make the outfit from the fabric in the reference image — %s — "
        "reproducing its print, colours and motif scale faithfully across the garment."
        % describe_fabric(fabric),
    ]
    extra = _sentence(user_prompt)
    if extra:
        sentences.append(extra)
    sentences.append("Do not change the person's face, body, pose or the background.")
    return _clip(" ".join(sentences))


def build_template_prompt(outfit, fabric, user_prompt=None):
    """Prompt for the composed-template strategy.

    Here the product image is already a flat-lay of the garment in the right
    fabric, so the prompt only needs to refine fit and styling.
    """
    sentences = ["Fit the garment naturally to the body with realistic drape and shadows."]
    extra = _sentence(user_prompt)
    if extra:
        sentences.append(extra)
    sentences.append("Keep the person's face, pose and background unchanged.")
    return _clip(" ".join(sentences))


def _sentence(text):
    """Normalise a user-typed brief into one sentence."""
    text = (text or "").strip().rstrip(".")
    if not text:
        return ""
    return text[0].upper() + text[1:] + "."


def _clip(text):
    text = " ".join(text.split())
    if len(text) <= MAX_PROMPT_CHARS:
        return text
    clipped = text[:MAX_PROMPT_CHARS]
    cut = clipped.rfind(". ")
    return clipped[:cut + 1] if cut > MAX_PROMPT_CHARS * 0.6 else clipped
