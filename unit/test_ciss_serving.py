"""Ciss(V) serving chain: CISS_CURVES lookup + fidelity-card grading.

The Ciss curve is optional everywhere; these tests pin the two monotone properties:
a part without a curated Ciss curve reads None (never a stand-in), and the fidelity
card grades a missing Ciss curve UNVERIFIED — absence of evidence is not PASS.
"""

import unittest

from dslib.coss_curves import ciss_curve_for, coss_curve_for


class CissCurveForTests(unittest.TestCase):
    def test_curated_part_returns_pairs(self):
        curve = ciss_curve_for('infineon', 'IPP019N08NF2S')
        self.assertIsNotNone(curve)
        for knot in curve:
            self.assertEqual(len(knot), 2)
        vs = [k[0] for k in curve]
        self.assertEqual(vs, sorted(vs))
        self.assertEqual(vs[0], 0)

    def test_unknown_part_returns_none_not_fallback(self):
        self.assertIsNone(ciss_curve_for('infineon', 'IPP024N08NF2S'))
        self.assertIsNone(ciss_curve_for('nope', 'NOPART123'))

    def test_ciss_above_crss_on_shared_span(self):
        # Downstream derives Cgs = Ciss - Crss; a curated pair of curves whose traces
        # cross would poison that silently. Guard every curated part that has both.
        from dslib.coss_curves import CISS_CURVES
        for (mfr, mpn), ciss in CISS_CURVES.items():
            triple = coss_curve_for(mfr, mpn)
            if not triple:
                continue
            for v, c in ciss:
                crss = _interp([(k[0], k[2]) for k in triple], v)
                if crss is None:
                    continue
                self.assertGreater(c, crss,
                                   f"{mfr}:{mpn} Ciss({v}V)={c} <= Crss={crss}")


def _interp(pairs, v):
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    if v < xs[0] or v > xs[-1]:
        return None
    for i in range(1, len(xs)):
        if v <= xs[i]:
            t = 0.0 if xs[i] == xs[i - 1] else (v - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


class FidelityCardCissRowTests(unittest.TestCase):
    def _fake(self, ciss_curve, ciss_typ):
        class Field:
            def __init__(self, typ, cond):
                self.typ, self.cond = typ, cond

        class DS(dict):
            pass

        class Specs:
            coss_curve = None
            ciss_curve = None
            Coss_Vds = None
            qrr_cond = None

        specs = Specs()
        specs.ciss_curve = ciss_curve
        ds = DS()
        if ciss_typ is not None:
            ds['Ciss'] = Field(ciss_typ, {'vds': '40'})
        ds['Qrr'] = None
        return specs, ds

    def test_missing_ciss_curve_is_unverified_not_pass(self):
        from dslib.viz.fidelity_card import build_card
        specs, ds = self._fake(None, 8700.0)
        rows = build_card(specs, ds)
        row = next(r for r in rows if r.name.startswith('Ciss'))
        self.assertIsNone(row.model)
        self.assertIn('no digitised Ciss curve', row.note)

    def test_present_ciss_curve_is_graded_at_nameplate_vds(self):
        from dslib.viz.fidelity_card import build_card
        curve = [(0.0, 10500.0), (10.0, 9200.0), (40.0, 8700.0), (80.0, 8500.0)]
        specs, ds = self._fake(curve, 8700.0)
        rows = build_card(specs, ds)
        row = next(r for r in rows if r.name.startswith('Ciss'))
        self.assertIsNotNone(row.model)
        self.assertAlmostEqual(row.model, 8700.0, delta=1.0)
        self.assertEqual(row.ref, 8700.0)
        self.assertEqual(row.verdict, 'PASS')


if __name__ == '__main__':
    unittest.main()
