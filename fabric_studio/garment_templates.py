"""Parametric flat-lay garment templates.

A template is a *shape*, not a picture: a silhouette mask plus a shading map
plus construction details (collar, placket, cuffs, trim). Fabric is poured into
that shape by garment_composer, which is what lets one outfit be rendered in
any fabric with zero generative inference — the cheap, deterministic half of
MODE A.

Silhouettes are described as width profiles (half-width as a fraction of the
canvas at a series of heights) and mirrored, so a new outfit is a dict of
numbers rather than a new drawing.
"""
import math

from . import imaging

TEMPLATE_VERSION = 3

CANVAS = (896, 1152)  # portrait 7:9 — the shape most try-on models expect


# --------------------------------------------------------------- geometry ---
def _sample_profile(points, steps):
    """Linear-interpolate (y, half_width) control points into `steps` samples."""
    points = sorted(points, key=lambda p: p[0])
    out = []
    for index in range(steps + 1):
        t = index / float(steps)
        previous = points[0]
        for point in points:
            if point[0] >= t:
                if point[0] == previous[0]:
                    out.append((t, point[1]))
                else:
                    span = (t - previous[0]) / (point[0] - previous[0])
                    out.append((t, previous[1] + (point[1] - previous[1]) * span))
                break
            previous = point
        else:
            out.append((t, points[-1][1]))
    return out


def _profile_polygon(profile, top, bottom, width, center=0.5):
    """Mirror a half-width profile into a closed polygon in pixel space."""
    height = bottom - top
    right = []
    left = []
    for t, half in profile:
        y = top + t * height
        right.append((center * width + half * width, y))
        left.append((center * width - half * width, y))
    return right + list(reversed(left))


def _quad(a, b, width_a, width_b):
    """A tapered band from point a to point b (used for sleeves and legs)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    return [
        (a[0] + nx * width_a, a[1] + ny * width_a),
        (b[0] + nx * width_b, b[1] + ny * width_b),
        (b[0] - nx * width_b, b[1] - ny * width_b),
        (a[0] - nx * width_a, a[1] - ny * width_a),
    ]


# -------------------------------------------------------------- templates ---
# Every field is a fraction of canvas width (x) or height (y).
BASE = {
    "shoulder_y": 0.10,
    "shoulder_half": 0.20,
    "neck_half": 0.062,
    "neck_depth": 0.028,
    "chest_half": 0.205,
    "waist_half": 0.185,
    "waist_y": 0.42,
    "hem_half": 0.20,
    "hem_y": 0.62,
    "sleeve_angle": 62.0,      # degrees below horizontal
    "sleeve_length": 0.42,     # fraction of canvas height
    "sleeve_top_half": 0.062,
    "sleeve_cuff_half": 0.040,
    "collar": "mandarin",
    "placket": True,
    "buttons": 5,
    "trousers": None,          # dict -> a matching bottom is drawn
    "overlay": None,           # "agbada" adds the wide outer robe
    "peplum": None,
    "pattern_scale": 0.42,     # fabric tile width as a fraction of the canvas
    "wrapper": False,
}

TEMPLATES = {
    "modern-senator": dict(BASE, **{
        "label": "Modern Senator",
        "hem_y": 0.55, "hem_half": 0.185, "waist_half": 0.178,
        "sleeve_length": 0.40, "collar": "mandarin", "buttons": 5,
        "trousers": {"top_y": 0.55, "hem_y": 0.97, "leg_half": 0.085, "cuff_half": 0.072},
        "pattern_scale": 0.34,
    }),
    "classic-kaftan": dict(BASE, **{
        "label": "Classic Kaftan",
        "chest_half": 0.235, "waist_half": 0.245, "hem_half": 0.285, "hem_y": 0.93,
        "sleeve_angle": 48.0, "sleeve_length": 0.34, "sleeve_top_half": 0.085,
        "sleeve_cuff_half": 0.070, "collar": "mandarin", "buttons": 3,
        "pattern_scale": 0.46,
    }),
    "grand-agbada": dict(BASE, **{
        "label": "Grand Agbada",
        "chest_half": 0.245, "waist_half": 0.255, "hem_half": 0.30, "hem_y": 0.86,
        "sleeve_length": 0.30, "collar": "v", "buttons": 0, "placket": False,
        "overlay": "agbada", "pattern_scale": 0.52,
        "trousers": {"top_y": 0.80, "hem_y": 0.975, "leg_half": 0.072, "cuff_half": 0.062},
    }),
    "native-two-piece": dict(BASE, **{
        "label": "Native Two-Piece",
        "hem_y": 0.52, "hem_half": 0.20, "sleeve_length": 0.24,
        "sleeve_cuff_half": 0.062, "collar": "round", "buttons": 4,
        "trousers": {"top_y": 0.52, "hem_y": 0.97, "leg_half": 0.088, "cuff_half": 0.074},
        "pattern_scale": 0.34,
    }),
    "long-tunic": dict(BASE, **{
        "label": "Long Tunic",
        "chest_half": 0.215, "waist_half": 0.205, "hem_half": 0.225, "hem_y": 0.78,
        "sleeve_length": 0.40, "collar": "mandarin", "buttons": 4,
        "pattern_scale": 0.40,
    }),
    "ankara-gown": dict(BASE, **{
        "label": "Ankara Gown",
        "shoulder_half": 0.175, "chest_half": 0.175, "waist_half": 0.135,
        "waist_y": 0.38, "hem_half": 0.33, "hem_y": 0.95,
        "sleeve_length": 0.30, "sleeve_top_half": 0.055, "sleeve_cuff_half": 0.042,
        "collar": "round", "placket": False, "buttons": 0,
        "pattern_scale": 0.40,
    }),
    "long-gown": dict(BASE, **{
        "label": "Long Gown",
        "shoulder_half": 0.17, "chest_half": 0.17, "waist_half": 0.145,
        "waist_y": 0.40, "hem_half": 0.26, "hem_y": 0.96,
        "sleeve_length": 0.44, "sleeve_top_half": 0.052, "sleeve_cuff_half": 0.038,
        "collar": "v", "placket": False, "buttons": 0,
        "pattern_scale": 0.44,
    }),
    "iro-and-buba": dict(BASE, **{
        "label": "Iro and Buba",
        "chest_half": 0.225, "waist_half": 0.225, "hem_half": 0.235, "hem_y": 0.47,
        "sleeve_angle": 44.0, "sleeve_length": 0.24, "sleeve_top_half": 0.095,
        "sleeve_cuff_half": 0.088, "collar": "round", "placket": False, "buttons": 0,
        "wrapper": True, "pattern_scale": 0.44,
    }),
    "skirt-and-blouse": dict(BASE, **{
        "label": "Skirt and Blouse",
        "chest_half": 0.185, "waist_half": 0.155, "hem_half": 0.165, "hem_y": 0.45,
        "sleeve_length": 0.26, "collar": "round", "placket": False, "buttons": 0,
        "wrapper": True, "pattern_scale": 0.36,
    }),
    "peplum-top": dict(BASE, **{
        "label": "Peplum Top and Skirt",
        "chest_half": 0.18, "waist_half": 0.145, "waist_y": 0.36,
        "hem_half": 0.155, "hem_y": 0.44,
        "sleeve_length": 0.28, "collar": "round", "placket": False, "buttons": 0,
        "peplum": {"y": 0.44, "half": 0.255, "depth": 0.10},
        "wrapper": True, "pattern_scale": 0.36,
    }),
    "bubu-boubou": dict(BASE, **{
        "label": "Bubu Boubou",
        "shoulder_half": 0.24, "chest_half": 0.28, "waist_half": 0.30,
        "hem_half": 0.345, "hem_y": 0.95,
        "sleeve_angle": 30.0, "sleeve_length": 0.26, "sleeve_top_half": 0.10,
        "sleeve_cuff_half": 0.10, "collar": "v", "placket": False, "buttons": 0,
        "pattern_scale": 0.55,
    }),
}


def get(template_id):
    return TEMPLATES.get(template_id)


def ids():
    return sorted(TEMPLATES.keys())


# ----------------------------------------------------------------- render ---
def build(template_id, size=None):
    """Return (mask, shading, details) images for a template.

    mask     — L, 255 where the garment is
    shading  — L, 128 neutral, brighter = highlight, darker = fold/shadow
    details  — RGBA overlay of construction lines drawn in neutral tones
    """
    imaging.require_pillow()
    from PIL import ImageDraw

    params = TEMPLATES.get(template_id)
    if params is None:
        raise KeyError("Unknown garment template: %s" % template_id)

    width, height = size or CANVAS
    mask = imaging.Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    shoulder_y = params["shoulder_y"] * height
    body_bottom = params["hem_y"] * height

    # --- torso ------------------------------------------------------------
    profile = _sample_profile([
        (0.0, params["shoulder_half"]),
        (0.06, params["shoulder_half"] * 1.01),
        (0.22, params["chest_half"]),
        (max(0.24, (params["waist_y"] - params["shoulder_y"]) / max(params["hem_y"] - params["shoulder_y"], 1e-3)), params["waist_half"]),
        (1.0, params["hem_half"]),
    ], 96)
    draw.polygon(_profile_polygon(profile, shoulder_y, body_bottom, width), fill=255)

    # --- sleeves ----------------------------------------------------------
    angle = math.radians(params["sleeve_angle"])
    sleeve_length = params["sleeve_length"] * height
    for side in (-1, 1):
        start = (0.5 * width + side * params["shoulder_half"] * width * 0.92, shoulder_y + height * 0.012)
        end = (
            start[0] + side * math.cos(angle) * sleeve_length,
            start[1] + math.sin(angle) * sleeve_length,
        )
        draw.polygon(
            _quad(start, end, params["sleeve_top_half"] * width, params["sleeve_cuff_half"] * width),
            fill=255,
        )
        draw.ellipse(
            [end[0] - params["sleeve_cuff_half"] * width, end[1] - params["sleeve_cuff_half"] * width,
             end[0] + params["sleeve_cuff_half"] * width, end[1] + params["sleeve_cuff_half"] * width],
            fill=255,
        )

    # --- shoulders and neckline ------------------------------------------
    draw.ellipse([
        0.5 * width - params["shoulder_half"] * width, shoulder_y - height * 0.006,
        0.5 * width + params["shoulder_half"] * width, shoulder_y + height * 0.055,
    ], fill=255)

    # --- optional pieces --------------------------------------------------
    if params.get("peplum"):
        peplum = params["peplum"]
        draw.polygon(_profile_polygon(
            _sample_profile([(0.0, params["hem_half"]), (0.35, peplum["half"]), (1.0, peplum["half"] * 0.96)], 48),
            peplum["y"] * height, (peplum["y"] + peplum["depth"]) * height, width,
        ), fill=255)

    if params.get("wrapper"):
        # Iro / skirt: a straight wrapper from the blouse hem to the floor.
        top = (params["hem_y"] + (0.085 if params.get("peplum") else -0.012)) * height
        draw.polygon(_profile_polygon(
            _sample_profile([(0.0, params["hem_half"] * 0.94), (0.35, params["hem_half"] * 1.02), (1.0, params["hem_half"] * 1.16)], 48),
            top, 0.965 * height, width,
        ), fill=255)

    if params.get("trousers"):
        _draw_trousers(draw, params["trousers"], width, height)

    if params.get("overlay") == "agbada":
        _draw_agbada_overlay(draw, params, width, height)

    mask = mask.filter(imaging.ImageFilter.GaussianBlur(2.2))
    mask = mask.point(lambda v: 255 if v > 120 else 0)
    mask = mask.filter(imaging.ImageFilter.GaussianBlur(1.1))

    # Neckline is cut *after* smoothing so it keeps a crisp edge.
    cut = ImageDraw.Draw(mask)
    neck_half = params["neck_half"] * width
    cut.ellipse([
        0.5 * width - neck_half, shoulder_y + height * 0.004,
        0.5 * width + neck_half, shoulder_y + params["neck_depth"] * height + height * 0.016,
    ], fill=0)
    if params["collar"] == "v":
        cut.polygon([
            (0.5 * width - neck_half, shoulder_y + height * 0.006),
            (0.5 * width + neck_half, shoulder_y + height * 0.006),
            (0.5 * width, shoulder_y + params["neck_depth"] * height * 3.0),
        ], fill=0)

    shading = _build_shading(mask, params, width, height)
    details = _build_details(params, width, height)
    return mask, shading, details


def _draw_trousers(draw, trousers, width, height):
    top = trousers["top_y"] * height
    bottom = trousers["hem_y"] * height
    leg = trousers["leg_half"] * width
    cuff = trousers["cuff_half"] * width
    gap = width * 0.012
    for side in (-1, 1):
        center = 0.5 * width + side * (leg + gap)
        draw.polygon([
            (center - leg, top),
            (center + leg, top),
            (center + cuff, bottom),
            (center - cuff, bottom),
        ], fill=255)
    # Close the seat so the two legs read as one garment.
    draw.rectangle([0.5 * width - (leg * 2 + gap), top, 0.5 * width + (leg * 2 + gap), top + height * 0.06], fill=255)


def _draw_agbada_overlay(draw, params, width, height):
    """The wide flowing outer robe that makes an agbada an agbada.

    Drawn as a width profile so the sides fall away from the shoulder in a
    curve (the drape of the sleeve opening) instead of a straight box.
    """
    top = params["shoulder_y"] * height + height * 0.02
    bottom = params["hem_y"] * height
    profile = _sample_profile([
        (0.0, 0.20),
        (0.16, 0.30),
        (0.42, 0.415),
        (0.72, 0.455),
        (0.93, 0.44),
        (1.0, 0.40),
    ], 72)
    draw.polygon(_profile_polygon(profile, top, bottom, width), fill=255)
    # Rounded hem corners.
    draw.ellipse([0.5 * width - 0.44 * width, bottom - height * 0.05,
                  0.5 * width - 0.30 * width, bottom + height * 0.02], fill=255)
    draw.ellipse([0.5 * width + 0.30 * width, bottom - height * 0.05,
                  0.5 * width + 0.44 * width, bottom + height * 0.02], fill=255)


def _build_shading(mask, params, width, height):
    """Soft folds + edge shading so the composed garment reads as cloth."""
    numpy = imaging.numpy_module()
    shading = imaging.Image.new("L", (width, height), 128)
    if numpy is None:
        return shading

    mask_array = numpy.asarray(mask, dtype=numpy.float32) / 255.0
    xs = numpy.linspace(0, 1, width)[None, :]
    ys = numpy.linspace(0, 1, height)[:, None]

    # Vertical drape: a few soft folds running down the garment.
    folds = numpy.sin(xs * math.pi * 7.0) * 9.0 + numpy.sin(xs * math.pi * 3.0 + 0.6) * 7.0
    # Centre light, edges falling away — a cylinder lit from the front.
    body = numpy.cos((xs - 0.5) * math.pi) ** 2 * 20.0 - 9.0
    # Slight top-to-bottom falloff.
    vertical = (1.0 - ys) * 8.0 - 3.0

    field = 128.0 + folds + body + vertical

    # Darken near the silhouette edge: blur the mask and use the gap between
    # the blurred and hard mask as an ambient-occlusion approximation.
    soft = numpy.asarray(mask.filter(imaging.ImageFilter.GaussianBlur(width * 0.02)), dtype=numpy.float32) / 255.0
    edge = numpy.clip(mask_array - soft, 0.0, 1.0)
    field -= edge * 46.0

    field = numpy.clip(field, 40, 220).astype(numpy.uint8)
    return imaging.Image.fromarray(field)


def _build_details(params, width, height):
    """Collar, placket, buttons, cuffs and hems as a translucent overlay."""
    from PIL import ImageDraw

    details = imaging.Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(details)
    shadow = (0, 0, 0, 70)
    highlight = (255, 255, 255, 60)
    shoulder_y = params["shoulder_y"] * height
    neck_half = params["neck_half"] * width
    line = max(2, int(width * 0.004))

    if params["collar"] == "mandarin":
        draw.arc([
            0.5 * width - neck_half * 1.5, shoulder_y - height * 0.028,
            0.5 * width + neck_half * 1.5, shoulder_y + params["neck_depth"] * height + height * 0.05,
        ], start=200, end=340, fill=shadow, width=int(line * 2.6))
        draw.arc([
            0.5 * width - neck_half * 1.5, shoulder_y - height * 0.024,
            0.5 * width + neck_half * 1.5, shoulder_y + params["neck_depth"] * height + height * 0.054,
        ], start=200, end=340, fill=highlight, width=line)
    elif params["collar"] == "v":
        for offset, color in ((0, shadow), (line, highlight)):
            draw.line([
                (0.5 * width - neck_half * 1.25 + offset, shoulder_y),
                (0.5 * width + offset, shoulder_y + params["neck_depth"] * height * 3.4),
                (0.5 * width + neck_half * 1.25 + offset, shoulder_y),
            ], fill=color, width=line)
    else:
        draw.arc([
            0.5 * width - neck_half * 1.35, shoulder_y - height * 0.02,
            0.5 * width + neck_half * 1.35, shoulder_y + params["neck_depth"] * height + height * 0.042,
        ], start=190, end=350, fill=shadow, width=int(line * 1.8))

    if params.get("placket"):
        top = shoulder_y + params["neck_depth"] * height
        bottom = params["hem_y"] * height * 0.99
        draw.line([(0.5 * width - line, top), (0.5 * width - line, bottom)], fill=shadow, width=int(line * 1.6))
        draw.line([(0.5 * width + line * 2, top), (0.5 * width + line * 2, bottom)], fill=highlight, width=line)
        count = params.get("buttons") or 0
        for index in range(count):
            y = top + (bottom - top) * (index + 0.6) / max(count, 1)
            radius = width * 0.0085
            draw.ellipse([0.5 * width - radius, y - radius, 0.5 * width + radius, y + radius],
                         fill=(255, 255, 255, 90), outline=(0, 0, 0, 90))

    # Cuff bands.
    angle = math.radians(params["sleeve_angle"])
    sleeve_length = params["sleeve_length"] * height
    for side in (-1, 1):
        start_x = 0.5 * width + side * params["shoulder_half"] * width * 0.92
        start_y = shoulder_y + height * 0.012
        end_x = start_x + side * math.cos(angle) * sleeve_length
        end_y = start_y + math.sin(angle) * sleeve_length
        cuff = params["sleeve_cuff_half"] * width
        draw.line([(end_x - cuff, end_y - cuff * 0.35), (end_x + cuff, end_y + cuff * 0.35)],
                  fill=shadow, width=int(line * 1.4))

    if params.get("wrapper"):
        top = (params["hem_y"] + (0.085 if params.get("peplum") else -0.012)) * height
        draw.line([(0.5 * width - params["hem_half"] * width, top),
                   (0.5 * width + params["hem_half"] * width, top)], fill=shadow, width=int(line * 2))

    if params.get("trousers"):
        trousers = params["trousers"]
        top = trousers["top_y"] * height
        draw.line([(0.5 * width - trousers["leg_half"] * width * 2, top),
                   (0.5 * width + trousers["leg_half"] * width * 2, top)],
                  fill=shadow, width=int(line * 2.2))
        draw.line([(0.5 * width, top + height * 0.06), (0.5 * width, trousers["hem_y"] * height)],
                  fill=shadow, width=line)
    return details
