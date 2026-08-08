"""Tests for the shared orderable-suffix MPN matcher (dslib/mpn_match.py).

Migration acceptance (2026-07-14): a before/after load_parts() attach diff
across all 10 377 pickle parts showed ZERO changes versus the old per-module
loose startswith fallbacks — every legitimate resolution is preserved while
family variants are refused. The CG/SC allowance is evidence-backed:
IQD016N08NM5 vs its CG and SC datasheets carry identical Qrr rows.
"""
import unittest

from dslib.mpn_match import are_packing_siblings, is_orderable_variant, lookup_base_variant


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


class PackingCodeIsDocumentedNotGuessed(unittest.TestCase):
    """The base direction used to accept any `[A-Z]{2,5}\\d` remainder, which cannot
    tell a packing code from a die/package letter FOLLOWED by one.

    Every case here is corpus-derived, not invented: censusing the 2992 Infineon
    MPNs whose stem is also a corpus part yields 661 width-5 blocks (14 distinct,
    all documented codes) and exactly four width-6 "codes" -- AXTMA1, TATMA1,
    GATMA1, AFKSA1 -- each of which is the real width-5 block with a letter stolen
    off the stem. All four were LIVE mis-attachments into qrr_layout, a
    layout/package-dependent registry.
    """

    def test_package_letter_is_not_part_of_the_packing_code(self):
        # IAUTN15S6N025 is TOLL, ...G is TOLG, ...T is TOLT: three packages, three
        # datasheets. Only the true base may claim the OPN.
        self.assertFalse(is_orderable_variant('IAUTN15S6N025', 'IAUTN15S6N025GATMA1'))
        self.assertFalse(is_orderable_variant('IAUTN15S6N025', 'IAUTN15S6N025TATMA1'))
        self.assertTrue(is_orderable_variant('IAUTN15S6N025G', 'IAUTN15S6N025GATMA1'))
        self.assertTrue(is_orderable_variant('IAUTN15S6N025T', 'IAUTN15S6N025TATMA1'))

    def test_revision_letter_is_not_part_of_the_packing_code(self):
        # IPDQ60T010S7A / IPQC60T010S7A ship their own datasheets
        self.assertFalse(is_orderable_variant('IPDQ60T010S7', 'IPDQ60T010S7AXTMA1'))
        self.assertFalse(is_orderable_variant('IPQC60T010S7', 'IPQC60T010S7AXTMA1'))
        self.assertTrue(is_orderable_variant('IPDQ60T010S7A', 'IPDQ60T010S7AXTMA1'))
        # ... and the un-suffixed base still owns its OWN packing code
        self.assertTrue(is_orderable_variant('IPDQ60T010S7', 'IPDQ60T010S7XTMA1'))

    def test_the_f_block_is_a_real_code(self):
        """FKSA1 occurs 5x with a present stem; leaving F out of the block made
        IPW60R045CPFKSA1 consolidate with nothing and ship as its own ranked row."""
        self.assertTrue(is_orderable_variant('IPW60R045CP', 'IPW60R045CPFKSA1'))
        self.assertTrue(is_orderable_variant('IPW60R045CPA', 'IPW60R045CPAFKSA1'))
        # but the CPA die must not be reachable from CP
        self.assertFalse(is_orderable_variant('IPW60R045CP', 'IPW60R045CPAFKSA1'))

    def test_reviewed_cross_vendor_suffixes_are_accepted(self):
        """The registries share PACKAGING_SUFFIXES with DigiKey matching and
        discovery, so PbF/tape spellings resolve their curated rows."""
        self.assertTrue(is_orderable_variant('IRFP4110', 'IRFP4110PBF'))
        self.assertTrue(is_orderable_variant('IRFH5010', 'IRFH5010TRPBF'))
        self.assertTrue(is_orderable_variant('SUP70042E', 'SUP70042E-GE3'))

    def test_lead_count_suffix_is_not_a_packing_suffix(self):
        """'-7' is a Diodes reel diameter but an IXYS LEAD COUNT: IXTA150N15X4 is
        TO-263-3 (2 leads + tab), IXTA150N15X4-7 is TO-263-7 (6 leads + tab) with
        its own parasitics. All 8 corpus '-7' pairs are the IXYS case."""
        self.assertFalse(is_orderable_variant('IXTA150N15X4', 'IXTA150N15X4-7'))
        self.assertFalse(are_packing_siblings('IXTA150N15X4', 'IXTA150N15X4-7'))

    def test_a_wellformed_looking_code_is_still_refused(self):
        """The calibration case: the OLD rule accepted all of these."""
        for base, mpn in (('BSC070N10NS3', 'BSC070N10NS3G12'),
                          ('IPP040N06N', 'IPP040N06NLA1'),
                          ('IRFB4110', 'IRFB4110XYZ9')):
            self.assertFalse(is_orderable_variant(base, mpn), (base, mpn))


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


class ArePackingSiblings(unittest.TestCase):
    def test_two_packing_codes_over_one_die(self):
        self.assertTrue(are_packing_siblings('IPP039N10N5AKSA1', 'IPP039N10N5XKSA1'))
        self.assertTrue(are_packing_siblings('IPP039N10N5', 'IPP039N10N5AKSA1'))
        self.assertTrue(are_packing_siblings('IPP039N10N5AKSA1', 'IPP039N10N5'))

    def test_family_variant_refused(self):
        """'LATMA1' is a well-formed code shape, but the L is part of the DIE."""
        self.assertFalse(are_packing_siblings('IPB017N10N5ATMA1', 'IPB017N10N5LATMA1'))
        self.assertFalse(are_packing_siblings('IRFB4110', 'IRFB4110G'))
        self.assertFalse(are_packing_siblings('IPP040N06N', 'IPP040N06NF2S'))

    def test_layout_variants_are_not_packing_siblings(self):
        # they carry their own datasheets and their own curated curves
        self.assertFalse(are_packing_siblings('IQD020N10NM5', 'IQD020N10NM5SC'))
        self.assertFalse(are_packing_siblings('IQD020N10NM5', 'IQD020N10NM5CGATMA1'))
        # ... but a layout variant still has packing siblings OF ITS OWN
        self.assertTrue(are_packing_siblings('IQD020N10NM5CG', 'IQD020N10NM5CGATMA1'))
        self.assertTrue(are_packing_siblings('IQD020N10NM5', 'IQD020N10NM5ATMA1'))

    def test_short_stem_and_equality_refused(self):
        self.assertFalse(are_packing_siblings('ABCD1', 'ABEF2'))
        self.assertFalse(are_packing_siblings('IPP039N10N5', 'IPP039N10N5'))
        self.assertFalse(are_packing_siblings('IPP039N10N5', ''))
        self.assertFalse(are_packing_siblings(None, None))

    def test_neighbouring_part_numbers_refused(self):
        self.assertFalse(are_packing_siblings('IPP039N10N5', 'IPP039N10N6'))
        self.assertFalse(are_packing_siblings('BSC070N10NS3G', 'BSC070N10NS5G'))

    def test_logic_level_die_letter_is_not_a_packing_code(self):
        """Infineon's L die is logic-level: ISC007N06LM6 has Vgs_th 1.1-2.3 V,
        ISC007N06NM6 has 2.1-3.3 V. 'LM6' vs 'NM6' are both well-formed under the
        loose orderable-code shape AND the same length, exactly like the real
        'AKSA1' vs 'XKSA1' — so only the DOCUMENTED packing block separates them.
        Found by an exhaustive pairwise scan of the 2992 Infineon corpus MPNs."""
        for a, b in (('ISC007N06LM6', 'ISC007N06NM6'),
                     ('ISC009N06LM5', 'ISC009N06NM6'),
                     ('ISC012N04LM6', 'ISC012N04NM6'),
                     ('BSC070N10LS5', 'BSC070N10NS5')):
            self.assertFalse(are_packing_siblings(a, b), (a, b))
            self.assertFalse(are_packing_siblings(b, a), (b, a))
        # the real packing codes it must keep matching
        self.assertTrue(are_packing_siblings('IPP039N10N5AKSA1', 'IPP039N10N5XKSA1'))
        self.assertTrue(are_packing_siblings('IPP070N10N3AKSA1', 'IPP070N10N3ATMA1'))
        self.assertTrue(are_packing_siblings('IPP070N10N3XKMA1', 'IPP070N10N3XUMA1'))

    def test_two_non_empty_remainders_need_the_documented_block(self):
        """With NEITHER side a known base, the loose shape is not enough."""
        self.assertFalse(are_packing_siblings('IPP039N10N5CGATMA1', 'IPP039N10N5SCATMA1'))
        self.assertFalse(are_packing_siblings('IPP039N10N5ABC1', 'IPP039N10N5XYZ2'))


class LookupOrderingSibling(unittest.TestCase):
    """Reverse direction: the registry keys an ORDERING CODE, the query is the base.

    COSS_CURVES landed IPP039N10N5AKSA1 while discovery ranks whichever of
    IPP039N10N5 / ...AKSA1 / ...XKSA1 it saw first, so without this the same die
    got its curve or the unverified scalar fallback by coin flip.
    """
    REG = {("infineon", "IPP039N10N5AKSA1"): "curve"}

    def test_base_resolves_to_curated_ordering_sibling(self):
        self.assertEqual(lookup_base_variant(self.REG, "infineon", "IPP039N10N5"), "curve")

    def test_other_ordering_sibling_resolves_too(self):
        self.assertEqual(lookup_base_variant(self.REG, "infineon", "IPP039N10N5XKSA1"), "curve")

    def test_family_variant_still_refused(self):
        # the reverse direction must not become a loose startswith either way
        reg = {("infineon", "IPP040N06NF2S"): "f2s"}
        self.assertIsNone(lookup_base_variant(reg, "infineon", "IPP040N06N"))
        self.assertIsNone(lookup_base_variant(self.REG, "onsemi", "IPP039N10N5"))

    def test_exact_and_base_direction_still_win(self):
        reg = {("infineon", "IPP039N10N5"): "base",
               ("infineon", "IPP039N10N5AKSA1"): "sibling"}
        self.assertEqual(lookup_base_variant(reg, "infineon", "IPP039N10N5"), "base")
        self.assertEqual(lookup_base_variant(reg, "infineon", "IPP039N10N5XKSA1"), "base")


if __name__ == "__main__":
    unittest.main()
