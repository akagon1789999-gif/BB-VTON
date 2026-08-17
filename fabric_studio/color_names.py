"""A small reference palette used to give extracted colours human names.

Kept deliberately small and fashion-oriented: the names end up in fabric cards
and in the metadata a stylist reads, so "deep blue" is more useful than
"#1b3a6b" and far more useful than a 900-entry CSS colour list.
"""

REFERENCE_COLORS = (
    ("black", (17, 17, 17)),
    ("charcoal", (54, 54, 58)),
    ("grey", (128, 128, 128)),
    ("silver", (192, 192, 192)),
    ("white", (245, 245, 245)),
    ("ivory", (240, 234, 214)),
    ("cream", (232, 219, 189)),
    ("beige", (214, 196, 160)),
    ("sand", (196, 172, 130)),
    ("gold", (198, 160, 74)),
    ("mustard", (206, 165, 45)),
    ("amber", (222, 145, 40)),
    ("orange", (226, 118, 45)),
    ("terracotta", (188, 100, 66)),
    ("rust", (160, 76, 40)),
    ("brown", (120, 82, 52)),
    ("chocolate", (78, 52, 36)),
    ("burgundy", (108, 32, 46)),
    ("maroon", (128, 40, 54)),
    ("red", (198, 48, 48)),
    ("coral", (226, 110, 100)),
    ("pink", (226, 140, 168)),
    ("fuchsia", (198, 62, 140)),
    ("purple", (118, 66, 156)),
    ("plum", (98, 52, 96)),
    ("navy", (26, 40, 82)),
    ("deep blue", (32, 62, 130)),
    ("royal blue", (44, 88, 182)),
    ("blue", (58, 110, 200)),
    ("sky blue", (126, 176, 222)),
    ("teal", (36, 122, 126)),
    ("emerald", (28, 122, 84)),
    ("green", (62, 140, 76)),
    ("olive", (110, 118, 60)),
    ("sage", (150, 164, 132)),
    ("lime", (168, 196, 78)),
)


def name_for_rgb(rgb):
    """Nearest reference colour, matched in HSV.

    Plain RGB distance mis-names dark saturated colours (deep forest green
    lands nearer "charcoal" than "green" in RGB space), so hue is compared
    circularly and weighted well above lightness.
    """
    hue, saturation, value = _rgb_to_hsv(rgb)
    best_name = "neutral"
    best_distance = None
    for name, reference in REFERENCE_COLORS:
        rh, rs, rv = _rgb_to_hsv(reference)
        hue_gap = abs(hue - rh)
        hue_gap = min(hue_gap, 1.0 - hue_gap)
        # Hue only matters when both colours actually carry colour.
        hue_weight = 6.0 * min(saturation, rs) / 0.5 if min(saturation, rs) < 0.5 else 6.0
        distance = (
            hue_weight * (hue_gap * 2.0) ** 2
            + 2.2 * (saturation - rs) ** 2
            + 2.0 * (value - rv) ** 2
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name


def _rgb_to_hsv(rgb):
    import colorsys
    return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)


def to_hex(rgb):
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))
