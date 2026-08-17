"""Catalogue search, filtering, facets and admin payload validation."""
import unittest

from . import context
from fabric_studio import catalog
from fabric_studio.errors import NotFoundError, ValidationError


class CatalogSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context.reset_stores()
        context.make_fabric("fab_a", "geometric", name="Royal Blue Ankara", category="Ankara",
                            tags=["Traditional"], primary_colors=["deep blue", "gold"],
                            pattern_type="geometric", process=False)
        context.make_fabric("fab_b", "lace", ["#f2ede4", "#c9b48a"], name="Ivory Corded Lace",
                            category="Lace", tags=["Occasion"], primary_colors=["ivory"],
                            pattern_type="floral", process=False)
        context.make_fabric("fab_c", "solid", ["#3a3d42"], name="Charcoal Senator Weave",
                            category="Senator", tags=["Formal"], primary_colors=["charcoal"],
                            pattern_type="solid", process=False)
        catalog.set_fabric_active("fab_c", False)

    def test_inactive_fabrics_are_hidden_from_customers(self):
        names = [item["name"] for item in catalog.search_fabrics()["items"]]
        self.assertNotIn("Charcoal Senator Weave", names)
        self.assertIn("Royal Blue Ankara", names)

    def test_admin_can_see_inactive_fabrics(self):
        ids = [record["id"] for record in catalog.all_fabrics(include_inactive=True)]
        self.assertIn("fab_c", ids)

    def test_search_matches_name_category_and_colour(self):
        for query, expected in (("ankara", "fab_a"), ("lace", "fab_b"), ("ivory", "fab_b")):
            with self.subTest(query=query):
                items = catalog.search_fabrics(query=query)["items"]
                self.assertIn(expected, [item["id"] for item in items])

    def test_category_and_pattern_filters(self):
        self.assertEqual([i["id"] for i in catalog.search_fabrics(category="Lace")["items"]], ["fab_b"])
        self.assertEqual([i["id"] for i in catalog.search_fabrics(pattern="geometric")["items"]], ["fab_a"])
        self.assertEqual(catalog.search_fabrics(category="Nonexistent")["total"], 0)

    def test_colour_filter(self):
        self.assertEqual([i["id"] for i in catalog.search_fabrics(color="ivory")["items"]], ["fab_b"])

    def test_pagination(self):
        page = catalog.search_fabrics(limit=1, offset=0)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(catalog.search_fabrics(limit=1, offset=1)["items"]), 1)

    def test_facets_come_from_live_records(self):
        facets = catalog.facets()
        categories = [f["value"] for f in facets["categories"]]
        self.assertIn("Ankara", categories)
        self.assertNotIn("Senator", categories)  # deactivated

    def test_lookup_by_slug_and_missing_id(self):
        self.assertEqual(catalog.get_fabric("royal-blue-ankara")["id"], "fab_a")
        with self.assertRaises(NotFoundError):
            catalog.require_fabric("does-not-exist")


class OutfitCatalogTest(unittest.TestCase):
    def setUp(self):
        context.reset_stores()
        context.make_outfit("out_1", "modern-senator", name="Modern Senator", category="Men", sort_order=10)
        context.make_outfit("out_2", "ankara-gown", name="Ankara Gown", category="Women", sort_order=5)

    def test_outfits_are_returned_in_sort_order(self):
        self.assertEqual([o["id"] for o in catalog.all_outfits()], ["out_2", "out_1"])

    def test_deactivated_outfits_are_hidden(self):
        catalog.set_outfit_active("out_1", False)
        self.assertEqual([o["id"] for o in catalog.all_outfits()], ["out_2"])
        with self.assertRaises(NotFoundError):
            catalog.require_outfit("out_1", include_inactive=False)


class PayloadValidationTest(unittest.TestCase):
    def test_fabric_requires_a_name(self):
        with self.assertRaises(ValidationError):
            catalog.validate_fabric_payload({})

    def test_fabric_source_url_must_be_http(self):
        with self.assertRaises(ValidationError):
            catalog.validate_fabric_payload({"name": "X", "source_url": "javascript:alert(1)"})

    def test_fabric_lists_accept_comma_separated_strings(self):
        cleaned = catalog.validate_fabric_payload({"name": "X", "tags": "One, Two , Three"})
        self.assertEqual(cleaned["tags"], ["One", "Two", "Three"])

    def test_outfit_requires_a_known_template(self):
        with self.assertRaises(ValidationError):
            catalog.validate_outfit_payload({"name": "X", "template_id": "nope"})
        cleaned = catalog.validate_outfit_payload({"name": "X", "template_id": "modern-senator"})
        self.assertEqual(cleaned["template_id"], "modern-senator")

    def test_outfit_garment_type_is_constrained(self):
        with self.assertRaises(ValidationError):
            catalog.validate_outfit_payload({"name": "X", "template_id": "modern-senator", "garment_type": "hats"})

    def test_pattern_scale_is_clamped(self):
        cleaned = catalog.validate_outfit_payload(
            {"name": "X", "template_id": "modern-senator", "pattern_scale": "9"}
        )
        self.assertEqual(cleaned["pattern_scale"], 1.6)


if __name__ == "__main__":
    unittest.main()
