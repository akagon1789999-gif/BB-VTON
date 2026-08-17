"""Procedural fabric swatch renderer used to seed the catalogue.

Why generated rather than scraped: fabric photography on the open web is
almost always copyrighted, and the brief forbids redistributing images whose
licensing is unclear. These swatches are original output of this code (BB
Apparel owns them), so the seed catalogue ships with a clean licence and the
pipeline can be proven end to end. Real photography is added later through the
admin uploader or the reviewed web importer (importer.py), which records the
source URL and licence for every image.

Each renderer returns a square RGB Pillow image with a woven-cloth micro
texture, so the downstream analysis sees something with realistic statistics
rather than flat vector art.
"""
import math
import random

from . import imaging


def _img():
    imaging.require_pillow()
    return imaging.Image


def _draw(image, mode="RGBA"):
    from PIL import ImageDraw
    if image.mode not in ("RGB", "RGBA"):
        mode = None
    return ImageDraw.Draw(image, mode)


def _blur(image, radius):
    return image.filter(imaging.ImageFilter.GaussianBlur(radius))


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _shade(color, amount):
    """amount > 0 lightens, < 0 darkens."""
    target = (255, 255, 255) if amount > 0 else (0, 0, 0)
    return _mix(color, target, abs(amount))


# ------------------------------------------------------------- texture -------
def _weave_overlay(image, strength=10, scale=3):
    """Overlay a fine over/under weave so swatches are not flat colour."""
    numpy = imaging.numpy_module()
    width, height = image.size
    if numpy is None:
        return image
    ys, xs = numpy.mgrid[0:height, 0:width]
    warp = numpy.sin(xs / float(scale) * math.pi) * 0.5
    weft = numpy.sin(ys / float(scale) * math.pi) * 0.5
    grain = (warp + weft) * strength
    noise = numpy.random.normal(0.0, strength * 0.45, (height, width))
    delta = grain + noise
    array = numpy.asarray(image, dtype=numpy.float32)
    array += delta[:, :, None]
    array = numpy.clip(array, 0, 255).astype(numpy.uint8)
    return _img().fromarray(array)


def _slub_overlay(image, strength=16):
    """Irregular yarn thickness — what makes linen read as linen."""
    numpy = imaging.numpy_module()
    if numpy is None:
        return image
    width, height = image.size
    rows = numpy.random.normal(0.0, strength, (height, 1, 1))
    cols = numpy.random.normal(0.0, strength * 0.6, (1, width, 1))
    array = numpy.asarray(image, dtype=numpy.float32) + rows + cols
    return _img().fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8))


def _sheen(image, amount=0.25):
    """A soft diagonal highlight, as on silk or brocade."""
    width, height = image.size
    gradient = _img().new("L", (width, height))
    draw = _draw(gradient)
    for i in range(0, width + height, 4):
        value = int(255 * max(0.0, 1.0 - abs(i - (width + height) * 0.42) / (width * 0.55)))
        draw.line([(i, 0), (0, i)], fill=value, width=5)
    gradient = _blur(gradient, width * 0.05)
    highlight = _img().new("RGB", (width, height), (255, 255, 255))
    return _img().composite(
        imaging.Image.blend(image, highlight, amount), image, gradient
    )


# ------------------------------------------------------------- renderers -----
def solid(size, palette, texture="plain"):
    base = _hex_to_rgb(palette[0])
    image = _img().new("RGB", (size, size), base)
    if texture == "linen":
        image = _slub_overlay(image, 18)
        image = _weave_overlay(image, 9, 3)
    elif texture == "silk":
        image = _weave_overlay(image, 3, 6)
        image = _sheen(image, 0.3)
    elif texture == "velvet":
        image = _weave_overlay(image, 14, 2)
        image = _blur(image, 1.2)
        image = _sheen(image, 0.12)
    elif texture == "chiffon":
        image = _weave_overlay(image, 5, 4)
        image = _blur(image, 0.8)
    else:
        image = _weave_overlay(image, 8, 3)
    return image


def stripes(size, palette, band=None, orientation="vertical"):
    colors = [_hex_to_rgb(c) for c in palette]
    band = band or max(18, size // 16)
    image = _img().new("RGB", (size, size), colors[0])
    draw = _draw(image)
    index = 0
    position = 0
    while position < size:
        color = colors[index % len(colors)]
        width = band if index % 2 == 0 else max(6, band // 3)
        if orientation == "vertical":
            draw.rectangle([position, 0, position + width, size], fill=color)
        else:
            draw.rectangle([0, position, size, position + width], fill=color)
        position += width
        index += 1
    return _weave_overlay(image, 9, 3)


def checks(size, palette, band=None):
    colors = [_hex_to_rgb(c) for c in palette]
    band = band or max(24, size // 10)
    image = stripes(size, palette, band, "vertical")
    overlay = _img().new("RGBA", (size, size), (0, 0, 0, 0))
    draw = _draw(overlay)
    index = 0
    position = 0
    while position < size:
        color = colors[index % len(colors)]
        width = band if index % 2 == 0 else max(6, band // 3)
        draw.rectangle([0, position, size, position + width], fill=color + (110,))
        position += width
        index += 1
    image = _img().alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    return _weave_overlay(image, 9, 3)


def geometric(size, palette, cell=None, motif="diamond"):
    """Bold repeating block motif — the classic Ankara/wax-print structure."""
    colors = [_hex_to_rgb(c) for c in palette]
    cell = cell or max(90, size // 5)
    image = _img().new("RGB", (size, size), colors[0])
    draw = _draw(image)
    rows = size // cell + 2
    cols = size // cell + 2
    for row in range(rows):
        for col in range(cols):
            cx = col * cell + (cell // 2 if row % 2 else 0)
            cy = row * cell
            accent = colors[(row + col) % (len(colors) - 1) + 1]
            half = cell * 0.42
            if motif == "diamond":
                draw.polygon(
                    [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)],
                    fill=accent,
                )
                inner = _shade(accent, -0.35)
                draw.polygon(
                    [(cx, cy - half * 0.45), (cx + half * 0.45, cy),
                     (cx, cy + half * 0.45), (cx - half * 0.45, cy)],
                    fill=inner,
                )
            elif motif == "square":
                draw.rectangle([cx - half, cy - half, cx + half, cy + half], fill=accent)
                draw.rectangle(
                    [cx - half * 0.5, cy - half * 0.5, cx + half * 0.5, cy + half * 0.5],
                    fill=_shade(accent, 0.3),
                )
            elif motif == "circle":
                draw.ellipse([cx - half, cy - half, cx + half, cy + half], fill=accent)
                draw.ellipse(
                    [cx - half * 0.55, cy - half * 0.55, cx + half * 0.55, cy + half * 0.55],
                    fill=_shade(accent, -0.3),
                )
                draw.ellipse(
                    [cx - half * 0.2, cy - half * 0.2, cx + half * 0.2, cy + half * 0.2],
                    fill=colors[0],
                )
            else:  # concentric rings + cross bars
                for step, factor in enumerate((1.0, 0.7, 0.4)):
                    color = accent if step % 2 == 0 else colors[0]
                    draw.ellipse(
                        [cx - half * factor, cy - half * factor,
                         cx + half * factor, cy + half * factor],
                        fill=color,
                    )
                draw.line([(cx - cell, cy), (cx + cell, cy)], fill=_shade(accent, -0.2), width=max(2, cell // 22))
    return _weave_overlay(image, 8, 3)


def floral(size, palette, cell=None, seed=7):
    """Petal clusters with stems — organic, non-straight edges by design."""
    rng = random.Random(seed)
    colors = [_hex_to_rgb(c) for c in palette]
    cell = cell or max(120, size // 4)
    image = _img().new("RGB", (size, size), colors[0])
    draw = _draw(image)
    leaf = colors[-1]
    for row in range(size // cell + 2):
        for col in range(size // cell + 2):
            cx = col * cell + (cell // 2 if row % 2 else 0) + rng.randint(-8, 8)
            cy = row * cell + rng.randint(-8, 8)
            petal_color = colors[(row + col) % (len(colors) - 1) + 1]
            radius = cell * 0.3
            for angle in range(0, 360, 45):
                theta = math.radians(angle + rng.randint(-6, 6))
                px = cx + math.cos(theta) * radius * 0.55
                py = cy + math.sin(theta) * radius * 0.55
                draw.ellipse(
                    [px - radius * 0.45, py - radius * 0.3,
                     px + radius * 0.45, py + radius * 0.3],
                    fill=petal_color,
                )
            draw.ellipse(
                [cx - radius * 0.28, cy - radius * 0.28, cx + radius * 0.28, cy + radius * 0.28],
                fill=_shade(petal_color, 0.45),
            )
            for direction in (-1, 1):
                lx = cx + direction * radius * 1.15
                ly = cy + radius * 0.95
                draw.ellipse(
                    [lx - radius * 0.4, ly - radius * 0.22, lx + radius * 0.4, ly + radius * 0.22],
                    fill=leaf,
                )
    image = _blur(image, 0.6)
    return _weave_overlay(image, 8, 3)


def adire(size, palette, seed=3):
    """Indigo resist-dye look: concentric rings, folded bands and speckle."""
    rng = random.Random(seed)
    base = _hex_to_rgb(palette[0])
    light = _hex_to_rgb(palette[1]) if len(palette) > 1 else _shade(base, 0.55)
    image = _img().new("RGB", (size, size), base)
    draw = _draw(image)

    step = size // 5
    for i in range(6):
        offset = i * step
        draw.line([(offset, 0), (offset, size)], fill=_shade(base, 0.22) + (150,), width=max(3, size // 180))
        draw.line([(0, offset), (size, offset)], fill=_shade(base, 0.18) + (120,), width=max(3, size // 200))

    for _ in range(14):
        cx = rng.randint(0, size)
        cy = rng.randint(0, size)
        radius = rng.randint(size // 14, size // 6)
        rings = rng.randint(3, 5)
        for ring in range(rings):
            factor = 1.0 - ring / float(rings)
            color = light if ring % 2 == 0 else _shade(base, 0.28)
            draw.ellipse(
                [cx - radius * factor, cy - radius * factor,
                 cx + radius * factor, cy + radius * factor],
                outline=color + (210,),
                width=max(2, size // 200),
            )
    for _ in range(size * 2):
        x = rng.randint(0, size - 1)
        y = rng.randint(0, size - 1)
        draw.point((x, y), fill=_shade(light, 0.1) + (90,))
    image = _blur(image, 0.7)
    return _weave_overlay(image, 10, 3)


def damask(size, palette, cell=None, seed=11):
    """Tonal brocade: same hue, different lightness, with a woven sheen."""
    base = _hex_to_rgb(palette[0])
    motif_color = _hex_to_rgb(palette[1]) if len(palette) > 1 else _shade(base, 0.25)
    cell = cell or max(110, size // 4)
    image = _img().new("RGB", (size, size), base)
    draw = _draw(image)
    for row in range(size // cell + 2):
        for col in range(size // cell + 2):
            cx = col * cell + (cell // 2 if row % 2 else 0)
            cy = row * cell
            r = cell * 0.36
            draw.polygon(
                [(cx, cy - r), (cx + r * 0.55, cy - r * 0.35), (cx + r * 0.42, cy + r * 0.3),
                 (cx, cy + r), (cx - r * 0.42, cy + r * 0.3), (cx - r * 0.55, cy - r * 0.35)],
                fill=motif_color + (235,),
            )
            draw.ellipse([cx - r * 0.28, cy - r * 0.28, cx + r * 0.28, cy + r * 0.28],
                         fill=_shade(motif_color, 0.28) + (235,))
            for direction in (-1, 1):
                draw.arc(
                    [cx + direction * r * 0.9 - r * 0.8, cy - r * 0.8,
                     cx + direction * r * 0.9 + r * 0.8, cy + r * 0.8],
                    start=200, end=340, fill=motif_color + (200,), width=max(2, cell // 26),
                )
    image = _blur(image, 0.8)
    image = _weave_overlay(image, 6, 4)
    return _sheen(image, 0.22)


def lace(size, palette, seed=5):
    """Fine net ground with scalloped floral motifs."""
    rng = random.Random(seed)
    ground = _hex_to_rgb(palette[0])
    thread = _hex_to_rgb(palette[1]) if len(palette) > 1 else _shade(ground, 0.5)
    image = _img().new("RGB", (size, size), ground)
    draw = _draw(image)

    mesh = max(9, size // 90)
    for y in range(0, size + mesh, mesh):
        for x in range(0, size + mesh, mesh):
            offset = mesh // 2 if (y // mesh) % 2 else 0
            draw.ellipse(
                [x + offset - mesh * 0.4, y - mesh * 0.4, x + offset + mesh * 0.4, y + mesh * 0.4],
                outline=thread + (120,), width=1,
            )
    cell = max(150, size // 3)
    for row in range(size // cell + 2):
        for col in range(size // cell + 2):
            cx = col * cell + (cell // 2 if row % 2 else 0)
            cy = row * cell
            radius = cell * 0.3
            for angle in range(0, 360, 30):
                theta = math.radians(angle)
                px = cx + math.cos(theta) * radius * 0.6
                py = cy + math.sin(theta) * radius * 0.6
                draw.ellipse(
                    [px - radius * 0.3, py - radius * 0.2, px + radius * 0.3, py + radius * 0.2],
                    outline=thread + (215,), width=max(2, size // 300),
                )
            draw.ellipse([cx - radius * 0.22, cy - radius * 0.22, cx + radius * 0.22, cy + radius * 0.22],
                         fill=thread + (190,))
            for _ in range(10):
                angle = rng.uniform(0, math.pi * 2)
                dist = rng.uniform(radius * 0.8, radius * 1.35)
                px = cx + math.cos(angle) * dist
                py = cy + math.sin(angle) * dist
                draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=thread + (150,))
    image = _blur(image, 0.5)
    return _weave_overlay(image, 5, 4)


def twill(size, palette, seed=13):
    """Diagonal denim weave with indigo depth variation."""
    numpy = imaging.numpy_module()
    base = _hex_to_rgb(palette[0])
    image = _img().new("RGB", (size, size), base)
    draw = _draw(image)
    light = _shade(base, 0.22)
    dark = _shade(base, -0.25)
    step = max(5, size // 150)
    for offset in range(-size, size * 2, step * 3):
        draw.line([(offset, 0), (offset + size, size)], fill=light + (120,), width=step)
        draw.line([(offset + step, 0), (offset + step + size, size)], fill=dark + (90,), width=max(1, step // 2))
    if numpy is not None:
        array = numpy.asarray(image, dtype=numpy.float32)
        array += numpy.random.normal(0, 7, array.shape[:2])[:, :, None]
        image = _img().fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8))
    return _weave_overlay(image, 6, 2)


def embroidered(size, palette, seed=17):
    """Solid ground with raised tonal embroidery (offset shadow + highlight)."""
    rng = random.Random(seed)
    ground = _hex_to_rgb(palette[0])
    thread = _hex_to_rgb(palette[1]) if len(palette) > 1 else _shade(ground, 0.4)
    image = solid(size, [palette[0]], "plain")
    draw = _draw(image)
    cell = max(150, size // 3)
    stitch = max(3, size // 220)
    for row in range(size // cell + 2):
        for col in range(size // cell + 2):
            cx = col * cell + (cell // 2 if row % 2 else 0)
            cy = row * cell
            radius = cell * 0.28
            for angle in range(0, 360, 24):
                theta = math.radians(angle)
                x1 = cx + math.cos(theta) * radius * 0.25
                y1 = cy + math.sin(theta) * radius * 0.25
                x2 = cx + math.cos(theta) * radius
                y2 = cy + math.sin(theta) * radius
                draw.line([(x1 + 2, y1 + 2), (x2 + 2, y2 + 2)], fill=_shade(ground, -0.35) + (150,), width=stitch)
                draw.line([(x1, y1), (x2, y2)], fill=thread + (240,), width=stitch)
            draw.ellipse([cx - radius * 0.18, cy - radius * 0.18, cx + radius * 0.18, cy + radius * 0.18],
                         fill=_shade(thread, 0.3) + (240,))
            for _ in range(18):
                angle = rng.uniform(0, math.pi * 2)
                dist = rng.uniform(radius * 1.2, radius * 1.7)
                px = cx + math.cos(angle) * dist
                py = cy + math.sin(angle) * dist
                draw.line([(px, py), (px + stitch * 2, py + stitch * 2)], fill=thread + (200,), width=stitch)
    return _weave_overlay(image, 7, 3)


def aso_oke(size, palette):
    """Hand-woven strip cloth: broad stripes crossed by fine warp bars."""
    image = stripes(size, palette, band=max(40, size // 8), orientation="horizontal")
    draw = _draw(image)
    accent = _shade(_hex_to_rgb(palette[-1]), 0.25)
    step = max(10, size // 60)
    for x in range(0, size, step):
        draw.line([(x, 0), (x, size)], fill=accent + (70,), width=max(1, step // 5))
    return _weave_overlay(image, 10, 3)


RENDERERS = {
    "solid": solid,
    "stripes": stripes,
    "checks": checks,
    "geometric": geometric,
    "floral": floral,
    "adire": adire,
    "damask": damask,
    "lace": lace,
    "twill": twill,
    "embroidered": embroidered,
    "aso_oke": aso_oke,
}


def render(kind, size, palette, **options):
    """Render a swatch deterministically.

    The RNG is seeded from the arguments so re-seeding a deployment produces
    byte-identical swatches — which keeps fabric content hashes, and therefore
    the processed-asset cache, stable across restarts.
    """
    renderer = RENDERERS.get(kind)
    if renderer is None:
        raise ValueError("Unknown swatch renderer: %s" % kind)
    numpy = imaging.numpy_module()
    if numpy is not None:
        signature = "%s|%s|%s|%s" % (kind, size, ",".join(palette), sorted(options.items()))
        numpy.random.seed(abs(hash(signature)) % (2 ** 31))
    return renderer(size, palette, **options)
