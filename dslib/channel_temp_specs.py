"""Human-verified saturation-channel temperature fits.

These coefficients come from matched-current fits to the datasheet's 25/175 °C
transfer curves.  They modify only the saturation surrogate's effective Vth and
K; Rds(on,Tj) remains a separate low-Vds input.  The 25 °C gate-charge plateau
anchor is preserved exactly by the consumer.

Fab approved the labelled extraction overlays on 2026-07-14.  A fit is usable
only when its status is ``verified`` and ``cold_anchor_conflict`` is explicitly
false; dcdc-tools independently enforces both fields.
"""

from copy import deepcopy

APPROVED_DSDIG_MANIFEST_SHA256 = (
    "6a7bcc6760c5a7cf8b1287f81dd88e84880350f47f89980d3c4714df7988ff4c"
)


def _verified(mpn, dvth_dt, dlogk_dt, shift_rms, cold_rms, ztc_chart, ztc_model):
    return dict(
        status="verified",
        tref_c=25.0,
        tmin_c=25.0,
        tmax_c=175.0,
        d_vth_eff_v_per_k=dvth_dt,
        d_log_k_per_k=dlogk_dt,
        cold_anchor_conflict=False,
        matched_shift_fit_rms_v=shift_rms,
        cold_anchor_check_rms_v=cold_rms,
        ztc_chart_a=ztc_chart,
        ztc_model_a=ztc_model,
        source=(f"datasheets/infineon/{mpn}.pdf page 7 diagram 7 transfer curves; "
                "dsdig matched-current fit; labelled overlay approved by Fab 2026-07-14"),
        approved_dsdig_manifest_sha256=APPROVED_DSDIG_MANIFEST_SHA256,
    )


CHANNEL_TEMP_SPECS = {
    ("infineon", "IPP019N08NF2S"): _verified(
        "IPP019N08NF2S",
        -0.0036178205177837377, -0.002284132989698835,
        0.005606176552400986, 0.20722377160115144,
        304.6524067247676, 325.385860813067,
    ),
    ("infineon", "IPP022N12NM6"): _verified(
        "IPP022N12NM6",
        -0.004961836086164931, -0.0025296556663904515,
        0.02151884221139561, 0.26876604259792,
        358.48121086849653, 355.2707854280432,
    ),
    ("infineon", "IPP024N08NF2S"): _verified(
        "IPP024N08NF2S",
        -0.003589760004361451, -0.002545864179684201,
        0.005612623693960893, 0.17722644203385807,
        235.46425327071546, 249.38910286822073,
    ),
    ("infineon", "IPP040N08NF2S"): _verified(
        "IPP040N08NF2S",
        -0.0037180931541531096, -0.0025125488001926204,
        0.007045445835264274, 0.2422623455543482,
        134.43392608014875, 135.94800529154483,
    ),
    ("infineon", "IPP055N08NF2S"): _verified(
        "IPP055N08NF2S",
        -0.003625999497727985, -0.002651248131565265,
        0.006117791419160514, 0.1815803550069069,
        97.99755182123295, 99.83564371656749,
    ),
}


def channel_temp_specs_for(mfr, mpn):
    """Return an isolated verified fit for an exact/base-orderable part, or None."""
    from dslib.mpn_match import lookup_base_variant

    hit = lookup_base_variant(CHANNEL_TEMP_SPECS, mfr, mpn)
    return deepcopy(hit) if hit else None
