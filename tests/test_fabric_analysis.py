import unittest

from . import context  # noqa: F401
from fabric_studio import swatches
from fabric_studio.color_names import name_for_rgb
from fabric_studio.fabric_analysis import analyze, extract_colors

# Detection is a heuristic, so each swatch asserts a *family* of acceptable
# labels rather than one exact string. What must never happen is a bold print
# being called "solid" or a flat cloth being called "geometric".
CASES = [
    ("geometric", ["#123a75", "#c62f2f", "#d8a63c"], {}, {"geometric", "checked"}),
    ("floral", ["#0f4d3a", "#e0678a", "#f0c94b", "#1d7a52"], {}, {"floral", "abstract"}),
    ("stripes", ["#1a2852", "#e8dbbd"], {}, {"striped"}),
    ("checks", ["#6c202e", "#e8dbbd"], {}, {"checked", "striped"}),
    ("solid", ["#2b3f6b"], {"texture": "silk"}, {"solid"}),
    ("solid", ["#3a1c28"], {"texture": "velvet"}, {"solid"}),
    ("solid", ["#c8b48a"], {"texture": "linen"}, {"textured", "solid"}),
    ("twill", ["#2f4f7a"], {}, {"textured", "striped"}),
    ("lace", ["#f2ede4", "#c9b48a"], {}, {"floral", "abstract", "textured"}),
    ("damask", ["#6c202e", "#c6a04a"], {}, {"floral", "abstract", "geometric"}),
]


class PatternClassificationTest(unittest.TestCase):
    def test_swatch_families(self):
        for kind, palette, options, acceptable in CASES:
            with self.subTest(kind=kind, options=options):
                metadata = analyze(swatches.render(kind, 512, palette, **options))
                self.assertIn(
                    metadata["patternType"], acceptable,
                    "%s%s classified as %s" % (kind, options, metadata["patternType"]),
                )

    def test_solid_swatches_have_no_pattern_density(self):
        metadata = analyze(swatches.render("solid", 512, ["#2b3f6b"], texture="silk"))
        self.assertIn(metadata["patternDensity"], ("none", "low"))

    def test_printed_swatch_reports_pattern_density(self):
        metadata = analyze(swatches.render("stripes", 512, ["#1a2852", "#e8dbbd"]))
        self.assertIn(metadata["patternDensity"], ("medium", "high"))

    def test_vertical_stripes_detected_as_vertical(self):
        metadata = analyze(swatches.render("stripes", 512, ["#1a2852", "#e8dbbd"], orientation="vertical"))
        self.assertEqual(metadata["orientation"], "vertical")

    def test_metadata_shape(self):
        metadata = analyze(swatches.render("geometric", 512, ["#123a75", "#c62f2f", "#d8a63c"]))
        for key in ("dominantColors", "secondaryColors", "patternType", "patternDensity",
                    "texture", "orientation", "description"):
            self.assertIn(key, metadata)
        self.assertTrue(metadata["dominantColors"])
        first = metadata["dominantColors"][0]
        self.assertTrue(first["hex"].startswith("#"))
        self.assertGreater(first["weight"], 0)


class ColorExtractionTest(unittest.TestCase):
    def test_dominant_color_of_a_flat_swatch(self):
        colors = extract_colors(swatches.render("solid", 256, ["#1b3560"], texture="plain"))
        self.assertGreaterEqual(colors[0]["weight"], 0.5)
        self.assertIn(colors[0]["name"], ("navy", "deep blue", "royal blue"))

    def test_weights_sum_to_about_one(self):
        colors = extract_colors(swatches.render("geometric", 256, ["#123a75", "#c62f2f", "#d8a63c"]))
        self.assertAlmostEqual(sum(c["weight"] for c in colors), 1.0, delta=0.35)

    def test_dark_saturated_colors_keep_their_hue(self):
        # The RGB-distance version of this used to call dark forest green
        # "charcoal"; naming happens in HSV precisely to avoid that.
        self.assertIn(name_for_rgb((15, 77, 58)), ("emerald", "green", "teal"))
        self.assertIn(name_for_rgb((26, 40, 82)), ("navy", "deep blue"))
        self.assertIn(name_for_rgb((54, 54, 58)), ("charcoal", "grey", "black"))


if __name__ == "__main__":
    unittest.main()
