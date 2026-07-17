"""Curated Qrr(Tj) tau-exponent evidence (the fetlib#37 temperature axis).

Three-state resolution, decided by Fab 2026-07-17 ("AO measured + conservative
1.2 elsewhere"):

* ``measured-fit`` — per-die exponents fitted from HUMAN-VERIFIED 25/125 C
  reverse-recovery curves (dsdig AO batch, dual-agent green + human gate;
  fit: dslib/qrr_tj_fit.py, evidence packet
  dsdig-verify-backlog/qrr-tj-fit/qrr_tj_fit.json @ dev 5fb244a, fetlib
  3170e28e). Headline values at the calibrated capacitive-share fraction
  f=0.10 (QRR_QOSS_FRACTION); the raw-chart lower bound is ~0.07 smaller.
* ``ao-family-pool`` — other Alpha & Omega parts: pooled median of the five
  distinct measured dies (five independent printed charts agreeing within
  0.011; AOD4126 excluded — its digitized data was a byte-identical copy of
  AOB414's, a staged-data defect, not evidence).
* ``conservative-bound`` — every other manufacturer keeps the legacy
  N_TAU = 1.2 ("Qrr doubles" rule): measured evidence exists for ONE vendor
  family only, and 1.2 over-predicts hot Qrr, which is the conservative
  direction for a loss budget.

Consumers resolve through :func:`dslib.qrr_model.resolve_n_tau`; never read
this table directly, so the state string always rides along.
"""

# Per-die measured exponents, headline f=0.10 (see module docstring).
QRR_TJ_MEASURED = {
    ("ao", "AOB414"): 0.657,
    ("ao", "AOI4126"): 0.657,
    ("ao", "AON6452"): 0.658,
    ("ao", "AOT414"): 0.660,
    ("ao", "AOTF4126"): 0.649,
}

AO_FAMILY_POOL_N_TAU = 0.657   # pooled median of the five distinct dies

MEASURED_SOURCE = ("dsdig-verify-backlog/qrr-tj-fit/qrr_tj_fit.json "
                   "(human-GREEN 2026-07-17, f=0.10 headline)")
