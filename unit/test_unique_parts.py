"""Duplicate consolidation in discover_parts.unique_parts.

The 2026-08-07 fugu2 CSV ranked IPP039N10N5, IPP039N10N5AKSA1 and
IPP039N10N5XKSA1 as three separate rows (164 duplicate rows out of 1194, ~14%)
— one die competing against itself, with only whichever spelling the curated
registry happened to key getting its Coss curve. The old key stripped four
hardcoded Infineon suffixes and nothing else.

The dangerous direction here is OVER-merging: two different dies collapsing
means one silently vanishes from the ranking. So every test below that asserts
a merge is paired with one asserting a near-miss stays separate.
"""
import unittest

from discover_parts import unique_parts, normal_mpn
from dslib.discovery import DiscoveredPart, MosfetBasicSpecs


def part(mfr, mpn, mpn2=None, source='mfr_list', Vds=100.0, Rds=3.9, Qg=100.0, package='TO220'):
    return DiscoveredPart(
        mfr=mfr, mpn=mpn, mpn2=mpn2, ds_url=None, package=package,
        specs=MosfetBasicSpecs(Vds_max=Vds, Rds_on_10v_max=Rds * 1e-3, ID_25=100.0,
                               Vgs_th_min=2.0, Vgs_th_typ=3.0, Vgs_th_max=4.0,
                               Qg_typ=Qg, Qg_max=Qg, source=[source]))


def mpns(parts):
    return sorted(p.mpn for p in parts)


class InfineonPackingCodes(unittest.TestCase):
    def test_all_three_spellings_collapse(self):
        got = unique_parts([part('infineon', 'IPP039N10N5AKSA1'),
                            part('infineon', 'IPP039N10N5XKSA1', source='digikey'),
                            part('infineon', 'IPP039N10N5')])
        self.assertEqual(mpns(got), ['IPP039N10N5AKSA1'])

    def test_codes_beyond_the_four_hardcoded_ones(self):
        # the old normal_mpn knew only AKSA1/AKMA1/XKSA1/XKMA1
        got = unique_parts([part('infineon', 'IQD016N08NM5'),
                            part('infineon', 'IQD016N08NM5ATMA1'),
                            part('infineon', 'IQD016N08NM5XTSA1')])
        self.assertEqual(mpns(got), ['IQD016N08NM5'])

    def test_whitespace_and_case_spellings_collapse(self):
        got = unique_parts([part('infineon', 'BSC070N10NS3 G'),
                            part('infineon', 'bsc070n10ns3g')])
        self.assertEqual(mpns(got), ['BSC070N10NS3 G'])

    def test_different_die_stays_separate(self):
        got = unique_parts([part('infineon', 'IPP040N06N'),
                            part('infineon', 'IPP040N06NF2S'),
                            part('infineon', 'IPP040N06NL')])
        self.assertEqual(mpns(got), ['IPP040N06N', 'IPP040N06NF2S', 'IPP040N06NL'])


class Mpn2Link(unittest.TestCase):
    def test_manufacturer_sibling_pointer_merges(self):
        # IR PbF renaming: the scraper lists both spellings, cross-linked by mpn2
        got = unique_parts([part('infineon', 'IRFB4110', mpn2='IRFB4110PBF'),
                            part('infineon', 'IRFB4110PBF', mpn2='IRFB4110')])
        self.assertEqual(mpns(got), ['IRFB4110'])

    def test_transitive_through_a_packing_code(self):
        # digikey's IRFB4110PBFXKMA1 -> IRFB4110PBF (packing) -> IRFB4110 (mpn2)
        got = unique_parts([part('infineon', 'IRFB4110', mpn2='IRFB4110PBF'),
                            part('infineon', 'IRFB4110PBF', mpn2='IRFB4110'),
                            part('infineon', 'IRFB4110PBFXKMA1', source='digikey')])
        self.assertEqual(mpns(got), ['IRFB4110'])

    def test_one_letter_continuation_is_a_different_part(self):
        # IRFB4110G has its own datasheet; it must not be eaten by IRFB4110
        got = unique_parts([part('infineon', 'IRFB4110', mpn2='IRFB4110PBF'),
                            part('infineon', 'IRFB4110G', mpn2='IRFB4110GPBF'),
                            part('infineon', 'IRFB4110GPBF', mpn2='IRFB4110G')])
        self.assertEqual(mpns(got), ['IRFB4110', 'IRFB4110G'])


class PackagingSuffixNeedsAPresentBase(unittest.TestCase):
    def test_vishay_lead_code_merges_when_the_base_is_in_the_corpus(self):
        got = unique_parts([part('vishay', 'SUP70042E'),
                            part('vishay', 'SUP70042E-GE3', source='digikey')])
        self.assertEqual(mpns(got), ['SUP70042E'])

    def test_no_base_no_merge(self):
        """Never invents a base MPN: a lone -GE3 listing stays as it is."""
        got = unique_parts([part('vishay', 'SUP70042E-GE3'),
                            part('vishay', 'SUP70030E-GE3')])
        self.assertEqual(mpns(got), ['SUP70030E-GE3', 'SUP70042E-GE3'])
        self.assertEqual(normal_mpn('SUP70042E-GE3', 'vishay'), 'sup70042e-ge3')

    def test_unreviewed_continuation_stays_separate(self):
        got = unique_parts([part('onsemi', 'NTMFS5C628NL'),
                            part('onsemi', 'NTMFS5C628NLA')])
        self.assertEqual(mpns(got), ['NTMFS5C628NL', 'NTMFS5C628NLA'])


class DisagreeingSiblingsStayVisible(unittest.TestCase):
    """MosfetBasicSpecs.update asserts the sources agree. A failed merge used to
    abort the whole run; silently picking a winner would publish one spelling's
    numbers under the other's name. Both rows survive instead."""

    def test_conflicting_qg_keeps_both(self):
        got = unique_parts([part('infineon', 'IAUCN10S5L094DATMA1', Qg=30.0),
                            part('infineon', 'IAUCN10S5L094D', Qg=23.0)])
        self.assertEqual(mpns(got), ['IAUCN10S5L094D', 'IAUCN10S5L094DATMA1'])

    def test_conflicting_vds_keeps_both(self):
        got = unique_parts([part('infineon', 'IPP70N10S3L12AKSA1', Vds=80.0),
                            part('infineon', 'IPP70N10S3L12', Vds=60.0)])
        self.assertEqual(mpns(got), ['IPP70N10S3L12', 'IPP70N10S3L12AKSA1'])

    def test_a_refused_sibling_still_absorbs_the_ones_that_agree_with_it(self):
        """AKSA1 and AKSA2 agree with each other and disagree only with their
        (stale) base record. Offering a refused part only the FIRST key of its
        group left them as two rows."""
        got = unique_parts([part('infineon', 'IPP70N10S3L12', Qg=60.0),
                            part('infineon', 'IPP70N10S3L12AKSA1', Qg=80.0),
                            part('infineon', 'IPP70N10S3L12AKSA2', Qg=80.0)])
        self.assertEqual(mpns(got), ['IPP70N10S3L12', 'IPP70N10S3L12AKSA1'])

    def test_the_survivor_is_not_left_half_merged(self):
        """The refused merge must not have mutated the winner on its way to the
        assert -- update() writes Vds/Rds before it ever looks at Qg."""
        keep = part('infineon', 'IAUCN10S5L094DATMA1', Qg=30.0, Rds=3.9)
        got = unique_parts([keep, part('infineon', 'IAUCN10S5L094D', Qg=23.0, Rds=5.9)])
        self.assertEqual(len(got), 2)
        self.assertAlmostEqual(keep.specs.Qg_typ_nC, 30.0)
        self.assertAlmostEqual(keep.specs.Rds_on_10v_max, 3.9e-3)


class MergeSemanticsPreserved(unittest.TestCase):
    def test_first_seen_wins_and_a_digikey_duplicate_contributes_nothing(self):
        first = part('infineon', 'IPP039N10N5AKSA1', package=None)
        got = unique_parts([first,
                            part('infineon', 'IPP039N10N5XKSA1', source='digikey',
                                 package='TO-220-3', Qg=1000.0)])
        self.assertEqual(got, [first])
        self.assertIsNone(first.package)  # "digikey data is often wrong"
        self.assertAlmostEqual(float(first.specs.Qg_typ_nC), 100.0)

    def test_a_non_digikey_duplicate_does_fill_a_missing_package(self):
        first = part('infineon', 'IPP039N10N5AKSA1', package=None)
        unique_parts([first, part('infineon', 'IPP039N10N5XKSA1', package='TO220')])
        self.assertEqual(first.package, 'TO220')

    def test_invalid_mpns_are_skipped(self):
        got = unique_parts([part('infineon', 'IPP039N10N5'), part('infineon', 'nan')])
        self.assertEqual(mpns(got), ['IPP039N10N5'])

    def test_same_mpn_different_manufacturer_never_merges(self):
        got = unique_parts([part('infineon', 'IPP039N10N5'), part('onsemi', 'IPP039N10N5')])
        self.assertEqual(len(got), 2)


if __name__ == '__main__':
    unittest.main()
