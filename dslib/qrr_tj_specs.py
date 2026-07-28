"""Curated Qrr(Tj) tau-exponent evidence (the fetlib#37 temperature axis).

Four-state resolution. AO wiring decided by Fab 2026-07-17 ("AO measured +
conservative 1.2 elsewhere"); IR wiring decided by Fab 2026-07-28 (fetlib#41
"do 1": per-die table fits + family pool):

* ``measured-fit`` — per-die exponents from direct evidence:
  - AO: fitted from HUMAN-VERIFIED 25/125 C reverse-recovery curves (dsdig AO
    batch, dual-agent green + human gate; fit: dslib/qrr_tj_fit.py, evidence
    packet dsdig-verify-backlog/qrr-tj-fit/qrr_tj_fit.json @ dev 5fb244a,
    fetlib 3170e28e). Headline values at the calibrated capacitive-share
    fraction f=0.10 (QRR_QOSS_FRACTION); the raw-chart lower bound is ~0.07
    smaller.
  - IR/AUIR: fitted from the datasheet TABLE pairs — those sheets print
    (Qrr, trr) at 25 C AND 125 C for one (IF, di/dt) (fit_n_tau_2rows;
    evidence packet dslib/qrr_tj_table.py @ 17f2df2f, corroboration + q0
    gates in apps/emit_qrr_tj_table.py; holdout trr residuals -8.9..+10.3%,
    median -1.4%). These are RAW fits (no Coss curve was available for any of
    the 21 at harvest time): a q0-contaminated raw fit biases n_tau LOW, the
    non-conservative direction — but the IR dies carry 1.5-2.3 uC of Qrr
    against tens of nC of capacitive share, so the bias is small. This table
    is a FROZEN, gate-reviewed copy; regenerating dslib/qrr_tj_table.py does
    NOT flow here without a new review.
* ``ao-family-pool`` — other Alpha & Omega parts: pooled median of the five
  distinct measured dies (five independent printed charts agreeing within
  0.011; AOD4126 excluded — its digitized data was a byte-identical copy of
  AOB414's, a staged-data defect, not evidence).
* ``ir-family-pool`` — other IR-heritage parts (mpn IRF*/IRL*/AUIRF*/AUIRL*
  under the infineon tag): pooled median of the 14 distinct table-fitted dies
  (0.666, IQR 0.496-0.731, range 0.314-0.781 — spanning planar HEXFET and
  StrongIRFET generations, ALL far below the 1.2 bound, and independently
  agreeing with the AO trench pool's 0.657 across vendor, method and
  technology).
* ``conservative-bound`` — everyone else keeps the legacy N_TAU = 1.2 ("Qrr
  doubles" rule): 1.2 over-predicts hot Qrr, which is the conservative
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

# Per-die exponents from the IR/AUIR paired 25/125 C table rows — frozen copy of
# dslib/qrr_tj_table.py @ 17f2df2f (harvest 2026-07-28), gate passed on fetlib#41.
# Raw fits (q0_basis='none' for all 21): see the module docstring for the bias note.
QRR_TJ_MEASURED_IR = {
    ("infineon", "AUIRFP4110"): 0.6821,
    ("infineon", "AUIRFP4568"): 0.6663,
    ("infineon", "AUIRFP4568-E"): 0.6663,
    ("infineon", "AUIRFS4010"): 0.4192,
    ("infineon", "AUIRFS4010-7P"): 0.3138,
    ("infineon", "AUIRFS4010-7TRL"): 0.3138,
    ("infineon", "AUIRFS4115-7P"): 0.6988,
    ("infineon", "AUIRFS4115-7TRL"): 0.6043,
    ("infineon", "AUIRFS4115TRL"): 0.6988,
    ("infineon", "AUIRFS4310ZTRL"): 0.7314,
    ("infineon", "AUIRFS4410Z"): 0.7462,
    ("infineon", "AUIRFSL4010"): 0.4192,
    ("infineon", "IRF100B201"): 0.5372,
    ("infineon", "IRF100B202"): 0.4063,
    ("infineon", "IRF100S201"): 0.5372,
    ("infineon", "IRF135B203"): 0.4956,
    ("infineon", "IRF135S203"): 0.4956,
    ("infineon", "IRF135SA204"): 0.5368,
    ("infineon", "IRFB4137"): 0.7496,
    ("infineon", "IRFP4768"): 0.7815,
    ("infineon", "IRFP4768PBF"): 0.7815,
}

IR_FAMILY_POOL_N_TAU = 0.666   # pooled median of the 14 distinct table-fitted dies

IR_TABLE_SOURCE = ("dslib/qrr_tj_table.py table-pair fits (frozen 2026-07-28, "
                   "fetlib#41 gate; raw fits, low-bias note in qrr_tj_specs)")

# IR-heritage MPN prefixes the family pool may claim (under the infineon mfr tag,
# which absorbed International Rectifier). Non-IR Infineon naming (IPP/BSC/IPT/...)
# must NEVER resolve here — those dies have no measured relatives.
IR_MPN_PREFIXES = ("IRF", "IRL", "AUIRF", "AUIRL")
