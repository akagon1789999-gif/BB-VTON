"""The prompt is load-bearing now: it is what tells the model the product
image is cloth rather than a finished garment."""
import unittest

from . import context  # noqa: F401
from fabric_studio import prompts

FABRIC = {
    "name": "Royal Blue Geometric Ankara",
    "primary_colors": ["deep blue", "gold"],
    "pattern_type": "geometric",
    "texture_description": "Crisp cotton wax print with a firm hand and a matte finish.",
    "processed": {"metadata": {"patternDensity": "medium",
                               "dominantColors": [{"name": "deep blue"}, {"name": "gold"}]}},
}
OUTFIT = {
    "name": "Grand Agbada",
    "default_prompt": "grand agbada with a wide flowing outer robe over a matching tunic and trousers",
}


class TryOnPromptTest(unittest.TestCase):
    def test_it_says_the_product_image_is_fabric(self):
        prompt = prompts.build_tryon_prompt(OUTFIT, FABRIC)
        self.assertIn("flat length of fabric", prompt)
        self.assertIn("not a finished garment", prompt)

    def test_it_describes_the_garment_to_build(self):
        self.assertIn("agbada", prompts.build_tryon_prompt(OUTFIT, FABRIC))

    def test_it_describes_the_fabric_in_words(self):
        prompt = prompts.build_tryon_prompt(OUTFIT, FABRIC)
        self.assertIn("deep blue", prompt)
        self.assertIn("geometric", prompt)

    def test_it_protects_identity_and_background(self):
        prompt = prompts.build_tryon_prompt(OUTFIT, FABRIC)
        for guard in ("face", "pose", "background"):
            self.assertIn(guard, prompt)

    def test_a_customer_brief_is_folded_in_as_a_sentence(self):
        prompt = prompts.build_tryon_prompt(OUTFIT, FABRIC, "add subtle chest embroidery")
        self.assertIn("Add subtle chest embroidery.", prompt)

    def test_it_stays_within_the_length_ceiling(self):
        wordy = dict(OUTFIT, default_prompt="a " + ("very long garment description " * 60))
        prompt = prompts.build_tryon_prompt(wordy, FABRIC, "and " + ("more detail " * 60))
        self.assertLessEqual(len(prompt), prompts.MAX_PROMPT_CHARS)

    def test_it_works_from_detected_metadata_alone(self):
        bare = {"processed": {"metadata": {"patternType": "floral",
                                           "dominantColors": [{"name": "emerald"}]}}}
        prompt = prompts.build_tryon_prompt({"name": "Ankara Gown"}, bare)
        self.assertIn("emerald", prompt)
        self.assertIn("ankara gown", prompt.lower())

    def test_it_survives_an_empty_catalogue_record(self):
        prompt = prompts.build_tryon_prompt({}, {})
        self.assertIn("flat length of fabric", prompt)
        self.assertTrue(prompt.endswith("."))


class EditPromptTest(unittest.TestCase):
    def test_it_points_at_the_reference_image(self):
        prompt = prompts.build_edit_prompt(OUTFIT, FABRIC)
        self.assertIn("reference image", prompt)
        self.assertIn("agbada", prompt)
        self.assertIn("Do not change", prompt)


class TemplatePromptTest(unittest.TestCase):
    def test_it_only_refines_fit(self):
        """The composed flat-lay already shows the garment, so the prompt must
        not re-describe it and risk a second interpretation."""
        prompt = prompts.build_template_prompt(OUTFIT, FABRIC)
        self.assertNotIn("agbada", prompt)
        self.assertIn("drape", prompt)


class FabricDescriptionTest(unittest.TestCase):
    def test_curated_colours_win_over_detected_ones(self):
        fabric = dict(FABRIC, primary_colors=["burgundy"])
        self.assertIn("burgundy", prompts.describe_fabric(fabric))

    def test_solid_fabrics_are_described_as_solid(self):
        fabric = {"primary_colors": ["charcoal"], "pattern_type": "solid"}
        self.assertIn("solid", prompts.describe_fabric(fabric))


if __name__ == "__main__":
    unittest.main()
