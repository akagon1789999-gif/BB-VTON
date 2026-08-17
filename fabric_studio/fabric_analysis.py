"""Lightweight computer-vision layer for fabric swatches.

This is deliberately a *preprocessing* layer, not a learned model: dominant
colour extraction (Pillow median-cut), edge/gradient statistics and 1-D
autocorrelation (numpy) are enough to describe a swatch well enough to drive
garment composition, catalogue metadata and search facets, and they run in
milliseconds on CPU with no GPU and no model download.

Every value returned here is an *approximation*. Curated catalogue metadata
always wins over detected values (see catalog.fabric_view).
"""
from . import imaging
from .color_names import name_for_rgb, to_hex

ANALYSIS_VERSION = 1

PATTERN_TYPES = (
    "solid",
    "striped",
    "checked",
    "geometric",
    "floral",
    "dotted",
    "abstract",
    "textured",
)


def analyze(image):
    """Return the structured metadata block for a fabric image."""
    rgb = imaging.to_rgb(image)
    work = imaging.fit_within(rgb, 384)

    colors = extract_colors(work)
    stats = _basic_stats(work)
    pattern = _pattern_metrics(work)

    pattern_type = _classify_pattern(pattern, colors, stats)
    density = _density_label(pattern["edgeDensity"])
    orientation = pattern["orientation"]
    texture = _texture_description(pattern, stats, pattern_type)

    dominant = colors[:2]
    secondary = colors[2:5]
    return {
        "analysisVersion": ANALYSIS_VERSION,
        "dominantColors": dominant,
        "secondaryColors": secondary,
        "allColors": colors,
        "patternType": pattern_type,
        "patternDensity": density,
        "patternScale": pattern["patternScale"],
        "orientation": orientation,
        "texture": texture,
        "brightness": round(stats["brightness"], 3),
        "saturation": round(stats["saturation"], 3),
        "contrast": round(stats["contrast"], 3),
        "edgeDensity": round(pattern["edgeDensity"], 4),
        "periodicity": {
            "horizontal": round(pattern["periodX"], 3),
            "vertical": round(pattern["periodY"], 3),
        },
        "orientationConcentration": round(pattern["orientationConcentration"], 3),
        "description": describe(colors, pattern_type, density, texture),
    }


# ------------------------------------------------------------------ colour ---
def extract_colors(image, max_colors=6):
    """Dominant colours by median-cut quantisation, merged and weighted."""
    rgb = imaging.to_rgb(image)
    small = rgb.resize((160, 160), imaging.Image.BILINEAR)
    quantize_method = getattr(getattr(imaging.Image, "Quantize", None), "MEDIANCUT", 0)
    try:
        quantized = small.quantize(colors=max_colors * 2, method=quantize_method)
    except Exception:
        quantized = small.convert("P", palette=imaging.Image.ADAPTIVE, colors=max_colors * 2)

    palette = quantized.getpalette() or []
    counts = quantized.getcolors() or []
    total = float(sum(count for count, _ in counts)) or 1.0

    buckets = []
    for count, index in sorted(counts, reverse=True):
        base = index * 3
        if base + 2 >= len(palette):
            continue
        color = (palette[base], palette[base + 1], palette[base + 2])
        weight = count / total
        merged = False
        for bucket in buckets:
            if _color_distance(bucket["rgb"], color) < 34:
                # Weighted average keeps the merged swatch representative.
                total_weight = bucket["weight"] + weight
                bucket["rgb"] = tuple(
                    int((bucket["rgb"][i] * bucket["weight"] + color[i] * weight) / total_weight)
                    for i in range(3)
                )
                bucket["weight"] = total_weight
                merged = True
                break
        if not merged:
            buckets.append({"rgb": color, "weight": weight})

    buckets.sort(key=lambda b: b["weight"], reverse=True)
    result = []
    for bucket in buckets[:max_colors]:
        result.append({
            "hex": to_hex(bucket["rgb"]),
            "rgb": list(bucket["rgb"]),
            "name": name_for_rgb(bucket["rgb"]),
            "weight": round(bucket["weight"], 3),
        })
    return result


def _color_distance(a, b):
    return (sum((a[i] - b[i]) ** 2 for i in range(3))) ** 0.5


# ------------------------------------------------------------------ stats ----
def _basic_stats(image):
    gray = image.convert("L")
    stat = imaging.ImageStat.Stat(gray)
    hsv = image.convert("HSV")
    hsv_stat = imaging.ImageStat.Stat(hsv)
    return {
        "brightness": stat.mean[0] / 255.0,
        "contrast": stat.stddev[0] / 128.0,
        "saturation": hsv_stat.mean[1] / 255.0,
    }


def _pattern_metrics(image):
    """Edge energy, directional periodicity and orientation concentration."""
    numpy = imaging.numpy_module()
    gray = image.convert("L").resize((256, 256), imaging.Image.BILINEAR)

    if numpy is None:
        # Pillow-only fallback: edge energy only, no periodicity analysis.
        edges = gray.filter(imaging.ImageFilter.FIND_EDGES)
        energy = imaging.ImageStat.Stat(edges).mean[0] / 255.0
        return {
            "edgeDensity": energy,
            "orientation": "none",
            "periodX": 0.0,
            "periodY": 0.0,
            "patternScale": 0.0,
            "orientationConcentration": 0.0,
            "directionalBalance": 0.0,
        }

    array = numpy.asarray(gray, dtype=numpy.float32) / 255.0
    dy, dx = numpy.gradient(array)
    magnitude = numpy.sqrt(dx * dx + dy * dy)
    edge_density = float(magnitude.mean())

    # Directional energy: stripes running vertically produce strong horizontal
    # gradients and almost no vertical ones.
    energy_x = float(numpy.abs(dx).mean())
    energy_y = float(numpy.abs(dy).mean())
    total_energy = energy_x + energy_y + 1e-6
    if energy_x > energy_y * 1.7:
        orientation = "vertical"
    elif energy_y > energy_x * 1.7:
        orientation = "horizontal"
    else:
        orientation = "none"

    period_x, scale_x = _profile_periodicity(numpy, array.mean(axis=0))
    period_y, scale_y = _profile_periodicity(numpy, array.mean(axis=1))

    # Orientation concentration: share of edge energy sitting in the four
    # busiest of eighteen angle bins. Printed motifs and weaves concentrate on
    # a few angles (~0.5-0.95); painted/organic motifs spread out (~0.25-0.35).
    # A uniform spread would score ~0.22.
    strong = magnitude > max(float(numpy.percentile(magnitude, 75)), 1e-4)
    if int(strong.sum()) > 32:
        angles = numpy.arctan2(dy[strong], dx[strong]) % numpy.pi
        histogram, _edges = numpy.histogram(angles, bins=18, range=(0.0, float(numpy.pi)))
        histogram = histogram / float(max(histogram.sum(), 1))
        concentration = float(numpy.sort(histogram)[-4:].sum())
    else:
        concentration = 0.0

    scale = max(scale_x, scale_y) / 256.0
    return {
        "edgeDensity": edge_density,
        "orientation": orientation,
        "periodX": period_x,
        "periodY": period_y,
        "patternScale": round(scale, 4),
        "orientationConcentration": concentration,
        "directionalBalance": round(abs(energy_x - energy_y) / total_energy, 3),
    }


def _profile_periodicity(numpy, profile):
    """Repeat strength of a 1-D intensity profile → (strength, period px).

    The profile is high-pass filtered first: without it, any smooth image
    scores a near-perfect autocorrelation at short lags and everything looks
    striped.
    """
    kernel = numpy.ones(9) / 9.0
    centered = profile - numpy.convolve(profile, kernel, mode="same")
    norm = float((centered * centered).sum())
    if norm < 1e-9:
        return 0.0, 0.0
    correlation = numpy.correlate(centered, centered, mode="full")[len(centered) - 1:] / norm
    window = correlation[8:len(correlation) // 2]
    if window.size == 0:
        return 0.0, 0.0
    index = int(numpy.argmax(window))
    strength = float(window[index] - window.mean())
    return max(0.0, strength), float(index + 8)


# --------------------------------------------------------- classification ----
def _classify_pattern(pattern, colors, stats):
    """Heuristic label. Curated catalogue metadata always overrides this."""
    edge = pattern["edgeDensity"]
    period_max = max(pattern["periodX"], pattern["periodY"])
    period_min = min(pattern["periodX"], pattern["periodY"])
    concentration = pattern.get("orientationConcentration", 0.0)
    distinct_colors = len([c for c in colors if c["weight"] > 0.05])

    if edge < 0.012 and stats["contrast"] < 0.3:
        return "solid"
    # One axis repeats far more strongly than the other -> bands.
    if period_max > 0.45 and period_min < period_max * 0.7 and concentration > 0.4:
        return "striped"
    # Both axes repeat and the edges are axis-aligned -> a grid of bands.
    if period_min > 0.4 and concentration > 0.55:
        return "checked"
    if concentration > 0.5 and period_max > 0.15 and distinct_colors >= 3:
        return "geometric"
    # Weave structure rather than a print: little colour variety and either
    # very low edge energy or edges all running the same way (twill, slub).
    if edge < 0.045 and distinct_colors <= 2 and (concentration >= 0.35 or edge < 0.02):
        return "textured"
    # Organic motifs: edges spread across many angles. Tie-dye/resist prints
    # look similar but repeat strongly, which keeps them out of this bucket.
    if distinct_colors >= 3 and concentration < 0.42 and period_max < 0.7:
        return "floral"
    if concentration < 0.32 and period_max < 0.3:
        return "floral"
    return "abstract"


def _density_label(edge_density):
    if edge_density < 0.008:
        return "none"
    if edge_density < 0.022:
        return "low"
    if edge_density < 0.05:
        return "medium"
    return "high"


def _texture_description(pattern, stats, pattern_type):
    parts = []
    if stats["brightness"] > 0.72:
        parts.append("light")
    elif stats["brightness"] < 0.3:
        parts.append("deep")
    if stats["saturation"] > 0.55:
        parts.append("richly saturated")
    elif stats["saturation"] < 0.15:
        parts.append("muted")
    if pattern["edgeDensity"] > 0.09:
        parts.append("busy weave")
    elif pattern["edgeDensity"] < 0.015:
        parts.append("smooth flat finish")
    else:
        parts.append("fine weave")
    if pattern_type in ("striped", "checked", "geometric"):
        parts.append("crisp repeating motif")
    elif pattern_type == "floral":
        parts.append("organic motif")
    return ", ".join(parts)


def describe(colors, pattern_type, density, texture):
    """One-line human summary, e.g. for the fabric card and the design prompt."""
    color_names = []
    for color in colors[:3]:
        if color["name"] not in color_names:
            color_names.append(color["name"])
    if not color_names:
        color_names = ["neutral"]
    if pattern_type == "solid":
        motif = "solid"
    else:
        motif = "%s %s pattern" % (density if density != "none" else "subtle", pattern_type)
    return "%s %s (%s)" % (" and ".join(color_names), motif, texture)
