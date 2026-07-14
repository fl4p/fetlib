"""Tests for the shared orderable-suffix MPN matcher (dslib/mpn_match.py).

Migration acceptance (2026-07-14): a before/after load_parts() attach diff
across all 10 377 pickle parts showed ZERO changes versus the old per-module
loose startswith fallbacks — every legitimate resolution is preserved while
family variants are refused. The CG/SC allowance is evidence-backed:
IQD016N08NM5 vs its CG and SC datasheets carry identical Qrr rows.
"""
import unittest

from dslib.mpn_match import is_orderable_variant, lookup_base_variant


class OrderableVariant(unittest.TestCase):
    def test_orderable_codes_accepted(self):
        self.assertTrue(is_orderable_variant("IPP022N12NM6", "IPP022N12NM6AKSA1"))
        self.assertTrue(is_orderable_variant("IPP040N08NF2S", "IPP040N08NF2SAKMA1"))
        self.assertTrue(is_orderable_variant("IQD016N08NM5", "IQD016N08NM5ATMA1"))

    def test_source_down_layout_codes_accepted(self):
        # same-die layout variants (verified: identical Qrr spec rows)
        self.assertTrue(is_orderable_variant("IQD016N08NM5", "IQD016N08NM5CG"))
        self.assertTrue(is_orderable_variant("IQD016N08NM5", "IQD016N08NM5SC"))
        self.assertTrue(is_orderable_variant("IQD016N08NM5", "IQD016N08NM5CGSC"))
        self.assertTrue(is_orderable_variant("IQD016N08NM5", "IQD016N08NM5CGSCATMA1"))

    def test_family_variants_refused(self):
        """Different die/technology must NEVER inherit curated data."""
        self.assertFalse(is_orderable_variant("IPP040N06N", "IPP040N06NF2S"))
        self.assertFalse(is_orderable_variant("IPP040N06N", "IPP040N06NL"))
        self.assertFalse(is_orderable_variant("BSC090", "BSC0902NS"))

    def test_layout_codes_scoped_to_source_down_families(self):
        """CG/SC evidence covers Infineon IQD/IQE/ISC ONLY — an unscoped rule
        would let any part ending in SC/CG inherit curated data (review
        blocker 2026-07-14)."""
        self.assertFalse(is_orderable_variant("ARBITRARY", "ARBITRARYSC"))
        self.assertFalse(is_orderable_variant("IPP040N06N", "IPP040N06NCG"))
        self.assertFalse(is_orderable_variant("BSC0902NS", "BSC0902NSCGSC"))
        self.assertTrue(is_orderable_variant("ISC018N08NM6", "ISC018N08NM6SC"))
        self.assertTrue(is_orderable_variant("IQDH88N06LM5", "IQDH88N06LM5CGSC"))

    def test_exact_and_empty_are_not_variants(self):
        self.assertFalse(is_orderable_variant("IPP022N12NM6", "IPP022N12NM6"))
        self.assertFalse(is_orderable_variant("", "IPP022N12NM6"))
        self.assertFalse(is_orderable_variant("IPP022N12NM6", ""))
        self.assertFalse(is_orderable_variant(None, None))


class LookupBaseVariant(unittest.TestCase):
    REG = {
        ("infineon", "IPP040N06N"): "old-60v",
        ("infineon", "IPP040N08NF2S"): "f2s-80v",
    }

    def test_exact_then_suffix(self):
        self.assertEqual(lookup_base_variant(self.REG, "infineon", "IPP040N06N"), "old-60v")
        self.assertEqual(lookup_base_variant(self.REG, "infineon", "IPP040N06NAKSA1"), "old-60v")
        self.assertEqual(lookup_base_variant(self.REG, "infineon", "IPP040N08NF2SAKMA1"), "f2s-80v")

    def test_cross_family_returns_none(self):
        self.assertIsNone(lookup_base_variant(self.REG, "infineon", "IPP040N06NF2S"))
        self.assertIsNone(lookup_base_variant(self.REG, "onsemi", "IPP040N06NAKSA1"))
        self.assertIsNone(lookup_base_variant(self.REG, "infineon", "TOTALLYOTHER"))

    def test_longest_base_wins(self):
        reg = {("infineon", "IQD016N08NM5"): "base",
               ("infineon", "IQD016N08NM5CG"): "cg-specific"}
        # CG variant curated in its own right must win over base+CG-as-suffix
        self.assertEqual(lookup_base_variant(reg, "infineon", "IQD016N08NM5CGATMA1"), "cg-specific")


if __name__ == "__main__":
    unittest.main()
