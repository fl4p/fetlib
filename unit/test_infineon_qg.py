"""Qg typ/max folding in the Infineon product-table scraper.

Infineon's product-table JSON splits one parametric column across SEVERAL QG
entries carrying the SAME valueRemark ('typ @10V') -- one with valueNumber (the
typ), one with valueMax. A single first-match lookup therefore booked a MAX as
Qg_typ for 27 of 4259 items and threw an available max away for 328 more.

The first symptom was a consolidation refusal: IAUCN10S5L094D (typ 23) and its
own OPN IAUCN10S5L094DATMA1 (max 30 read as typ) looked like two parts with
disagreeing gate charge.
"""
import math
import unittest

from dslib.discovery.infineon import _qg_typ_max


def qg(remark='typ @10V', **kw):
    return dict(parameterName='QG', valueRemark=remark, **kw)


class QgTypMax(unittest.TestCase):
    def test_max_entry_first_does_not_become_the_typ(self):
        # IAUCN10S5L094D's real ordering
        self.assertEqual(_qg_typ_max({'QG': [qg(valueMax=30.0), qg(valueNumber=23.0)]}),
                         (23.0, 30.0))

    def test_typ_entry_first_still_keeps_the_max(self):
        # IAUCN10S7N021 / IPB35N10S3L-26 ordering -- the max used to be discarded
        self.assertEqual(_qg_typ_max({'QG': [qg(valueNumber=81.0), qg(valueMax=105.0)]}),
                         (81.0, 105.0))

    def test_single_entry_with_only_a_typ(self):
        typ, mx = _qg_typ_max({'QG': [qg(valueNumber=76.0)]})  # IPP039N10N5
        self.assertEqual(typ, 76.0)
        self.assertTrue(math.isnan(float(mx)))

    def test_both_fields_on_one_entry(self):
        self.assertEqual(_qg_typ_max({'QG': [qg(valueNumber=178.0, valueMax=231.0)]}),
                         (178.0, 231.0))

    def test_disagreeing_entries_take_the_worst_case(self):
        """IAUTN08S5N012L quotes 178/231 and 19/24 under one remark. Overstating
        gate charge demotes a part; understating it promotes one that cannot
        deliver, so the larger value wins."""
        self.assertEqual(_qg_typ_max({'QG': [qg(valueNumber=178.0, valueMax=231.0),
                                             qg(valueNumber=19.0, valueMax=24.0)]}),
                         (178.0, 231.0))

    def test_other_gate_voltages_are_preferred_away(self):
        got = _qg_typ_max({'QG': [qg(remark='typ @4.5V', valueNumber=9.0),
                                  qg(valueNumber=23.0), qg(valueMax=30.0)]})
        self.assertEqual(got, (23.0, 30.0))

    def test_falls_back_when_no_entry_names_10v(self):
        typ, mx = _qg_typ_max({'QG': [qg(remark='typ', valueNumber=23.0)]})
        self.assertEqual(typ, 23.0)
        self.assertTrue(math.isnan(mx))

    def test_the_fallback_does_not_pool_across_gate_voltages(self):
        """No live item hits this path, but folding a typ from one Vgs with a max
        from another would invent a spec neither row states."""
        typ, mx = _qg_typ_max({'QG': [qg(remark='typ @4.5V', valueNumber=9.0),
                                      qg(remark='typ @18V', valueMax=40.0)]})
        self.assertEqual(typ, 9.0)
        self.assertTrue(math.isnan(mx))

    def test_absent_parameter_is_nan_not_zero(self):
        typ, mx = _qg_typ_max({})
        self.assertTrue(math.isnan(typ) and math.isnan(mx))
        typ, mx = _qg_typ_max({'QG': []})
        self.assertTrue(math.isnan(typ) and math.isnan(mx))


if __name__ == '__main__':
    unittest.main()
