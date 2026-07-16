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
        # A wholly unknown part, and a part that HAS a Coss curve but no curated Ciss,
        # must both read None -- never a cross-fallback to the Coss dict. The Coss-only
        # example is chosen dynamically so curating its Ciss later can't stale this test
        # (as hardcoding IPP024 once did); if every Coss part gains a Ciss curve the
        # unknown-part assertions still pin the no-fallback contract.
        from dslib.coss_curves import COSS_CURVES, CISS_CURVES
        self.assertIsNone(ciss_curve_for('nope', 'NOPART123'))
        for (mfr, mpn) in COSS_CURVES:
            if (mfr, mpn) not in CISS_CURVES:
                self.assertIsNone(ciss_curve_for(mfr, mpn),
                                  f"{mfr}:{mpn} has Coss but no Ciss -> None, not a fallback")

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


class StoreAttachIndependenceTests(unittest.TestCase):
    """The Ciss attach in store.load_parts() must be gated ONLY on ciss_curve_for.

    Regression for the review finding that the Ciss loop first shipped nested under
    `if coss_curve_for is not None:` — so a broken/renamed coss_curve_for (its import
    raising) would silently disable the Ciss attach too. We simulate that failure by
    deleting coss_curve_for from the module so `from dslib.coss_curves import
    coss_curve_for` raises ImportError, then assert Ciss still attaches.
    """

    CURATED = ('infineon', 'IPP019N08NF2S')

    def setUp(self):
        import dslib.coss_curves as cc
        self._cc = cc
        self._saved = cc.coss_curve_for
        # Make the `from dslib.coss_curves import coss_curve_for` in load_parts fail,
        # exactly as a rename/removal of that symbol would.
        del cc.coss_curve_for

    def tearDown(self):
        self._cc.coss_curve_for = self._saved
        # Drop the specs mutated during the test so later tests re-attach cleanly.
        from dslib.store import parts_db
        parts_db.load(reload=True)

    def test_ciss_attaches_when_coss_lookup_import_fails(self):
        from dslib.store import parts_db, load_parts
        # Fresh specs (the shared _lib_mem cache would otherwise carry a prior run's
        # already-attached curves and skip the attach we want to exercise).
        parts_db.load(reload=True)
        parts = load_parts()
        part = parts.get(self.CURATED)
        self.assertIsNotNone(part, f"{self.CURATED} missing from parts DB")
        # Ciss attached despite coss_curve_for's import having failed:
        self.assertIsNotNone(getattr(part.specs, 'ciss_curve', None),
                             "Ciss attach was suppressed by the coss import failure")
        # ...and Coss did NOT attach (its lookup was unavailable) — proves the two are
        # genuinely independent, not both riding a single successful import.
        self.assertIsNone(getattr(part.specs, 'coss_curve', None),
                          "coss_curve attached even though its lookup import failed")


if __name__ == '__main__':
    unittest.main()
