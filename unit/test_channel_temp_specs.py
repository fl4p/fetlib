"""Tests for the reviewed saturation-channel temperature fits."""

import unittest

from dslib.channel_temp_specs import (
    APPROVED_DSDIG_MANIFEST_SHA256,
    channel_temp_specs_for,
)


class ChannelTempSpecsLookup(unittest.TestCase):
    EXPECTED_MANIFEST_SHA256 = (
        "6a7bcc6760c5a7cf8b1287f81dd88e84880350f47f89980d3c4714df7988ff4c"
    )
    EXPECTED_COEFFICIENTS = {
        "IPP019N08NF2S": (-0.0036178205177837377, -0.002284132989698835),
        "IPP022N12NM6": (-0.004961836086164931, -0.0025296556663904515),
        "IPP024N08NF2S": (-0.003589760004361451, -0.002545864179684201),
        "IPP040N08NF2S": (-0.0037180931541531096, -0.0025125488001926204),
        "IPP055N08NF2S": (-0.003625999497727985, -0.002651248131565265),
    }

    def test_all_reviewed_parts_are_verified_and_bounded(self):
        for mpn, expected in self.EXPECTED_COEFFICIENTS.items():
            fit = channel_temp_specs_for("infineon", mpn)
            self.assertEqual(fit["status"], "verified")
            self.assertIs(fit["cold_anchor_conflict"], False)
            self.assertEqual((fit["tmin_c"], fit["tref_c"], fit["tmax_c"]),
                             (25.0, 25.0, 175.0))
            self.assertLess(fit["d_vth_eff_v_per_k"], 0.0)
            self.assertLess(fit["d_log_k_per_k"], 0.0)
            self.assertLess(fit["matched_shift_fit_rms_v"], 0.05)
            self.assertEqual(
                (fit["d_vth_eff_v_per_k"], fit["d_log_k_per_k"]), expected
            )
            self.assertIn(f"{mpn}.pdf page 7 diagram 7", fit["source"])
            self.assertEqual(
                fit["approved_dsdig_manifest_sha256"],
                self.EXPECTED_MANIFEST_SHA256,
            )

        self.assertEqual(
            APPROVED_DSDIG_MANIFEST_SHA256, self.EXPECTED_MANIFEST_SHA256
        )

    def test_orderable_suffix_and_strict_family_matching(self):
        self.assertIsNotNone(channel_temp_specs_for(
            "infineon", "IPP024N08NF2SAKMA1"))
        self.assertIsNone(channel_temp_specs_for("infineon", "IPP024N08NF2"))
        self.assertIsNone(channel_temp_specs_for("onsemi", "IPP024N08NF2S"))

    def test_returns_copy(self):
        fit = channel_temp_specs_for("infineon", "IPP040N08NF2S")
        fit["status"] = "changed"
        self.assertEqual(channel_temp_specs_for(
            "infineon", "IPP040N08NF2S")["status"], "verified")


if __name__ == "__main__":
    unittest.main()
