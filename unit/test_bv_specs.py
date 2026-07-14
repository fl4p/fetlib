"""Tests for the curated V(BR)DSS(Tj) breakdown-onset lines (dslib/bv_specs.py).

Values pinned to the human-verified 2026-07-14 dsdig digitization
(ee/out/bv_digitization): min-anchored 25 C intercept == parameter-table
minimum, typical-die slope.
"""
import unittest

from dslib.bv_specs import bv_specs_for


class BvSpecsLookup(unittest.TestCase):
    def test_exact_parts(self):
        bv = bv_specs_for("infineon", "IPP040N08NF2S")
        self.assertEqual(bv["bv_min_25c"], 80.0)
        self.assertAlmostEqual(bv["bv_tc"], 0.040)
        bv = bv_specs_for("infineon", "IPP022N12NM6")
        self.assertEqual(bv["bv_min_25c"], 120.0)
        self.assertAlmostEqual(bv["bv_tc"], 0.075)
        bv = bv_specs_for("infineon", "IPP040N06N")
        self.assertEqual(bv["bv_min_25c"], 60.0)
        self.assertAlmostEqual(bv["bv_tc"], 0.030)

    def test_orderable_suffix_resolves_to_base(self):
        self.assertEqual(bv_specs_for("infineon", "IPP022N12NM6AKSA1")["bv_min_25c"], 120.0)
        self.assertEqual(bv_specs_for("infineon", "IPP040N08NF2SAKMA1")["bv_min_25c"], 80.0)

    def test_family_variant_must_not_inherit(self):
        """IPP040N06NF2S is a DIFFERENT part than IPP040N06N; a bare startswith
        fallback served the old part's breakdown line to it (live 2026-07-14).
        An uncurated part gets None, never a neighbor's data."""
        self.assertIsNone(bv_specs_for("infineon", "IPP040N06NF2S"))

    def test_uncurated_and_empty(self):
        self.assertIsNone(bv_specs_for("infineon", "BSC0902NS"))
        self.assertIsNone(bv_specs_for(None, None))
        self.assertIsNone(bv_specs_for("onsemi", "IPP040N08NF2S"))

    def test_returns_copy_not_registry_entry(self):
        a = bv_specs_for("infineon", "IPP040N08NF2S")
        a["bv_min_25c"] = 1.0
        self.assertEqual(bv_specs_for("infineon", "IPP040N08NF2S")["bv_min_25c"], 80.0)


if __name__ == "__main__":
    unittest.main()
