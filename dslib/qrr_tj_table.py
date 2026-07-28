"""GENERATED -- do not edit. Rebuild with:

    python3 apps/emit_qrr_tj_table.py --emit

Qrr(Tj) tau exponents fitted from datasheet TABLE pairs -- sheets (IR/AUIR layout)
that print (Qrr, trr) at 25 C AND 125 C for one (IF, di/dt). Fit:
dslib.qrr_tj_fit.fit_n_tau_2rows (TM held, tau inverted per temperature, printed hot
trr as a fit-free holdout -- its residual is per entry below). See the generator for
the corroboration and q0 gates.

NOT consumed by dslib.qrr_model.resolve_n_tau: this is REVIEW EVIDENCE, like the AO
chart fits were before QRR_TJ_MEASURED was written by hand after a human gate.
Entries with q0_basis='none' were fitted raw (no Coss curve for Qoss(VR)); raw fits
of a contaminated integral bias n_tau LOW, the non-conservative direction.
"""

QRR_TJ_TABLE = {
    ("infineon", "AUIRFP4110"): dict(n_tau=0.6821, q0_basis='none', q0_nc=0,
        qrr_ratio=1.4894, trr_hot_resid=-0.0059, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=75, didt=1e+08, VR=85,
        qrr_cold_nc=94, trr_cold_ns=50, qrr_hot_nc=140, trr_hot_ns=60),
    ("infineon", "AUIRFP4568"): dict(n_tau=0.6663, q0_basis='none', q0_nc=0,
        qrr_ratio=1.4718, trr_hot_resid=-0.0098, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=103, didt=1e+08, VR=100,
        qrr_cold_nc=515, trr_cold_ns=110, qrr_hot_nc=758, trr_hot_ns=133),
    ("infineon", "AUIRFP4568-E"): dict(n_tau=0.6663, q0_basis='none', q0_nc=0,
        qrr_ratio=1.4718, trr_hot_resid=-0.0098, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=103, didt=1e+08, VR=100,
        qrr_cold_nc=515, trr_cold_ns=110, qrr_hot_nc=758, trr_hot_ns=133),
    ("infineon", "AUIRFS4010"): dict(n_tau=0.4192, q0_basis='none', q0_nc=0,
        qrr_ratio=1.2762, trr_hot_resid=-0.0068, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=106, didt=1e+08, VR=85,
        qrr_cold_nc=210, trr_cold_ns=72, qrr_hot_nc=268, trr_hot_ns=81),
    ("infineon", "AUIRFS4010-7P"): dict(n_tau=0.3138, q0_basis='none', q0_nc=0,
        qrr_ratio=1.2, trr_hot_resid=-0.0261, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=110, didt=1e+08, VR=85,
        qrr_cold_nc=150, trr_cold_ns=60, qrr_hot_nc=180, trr_hot_ns=67),
    ("infineon", "AUIRFS4010-7TRL"): dict(n_tau=0.3138, q0_basis='none', q0_nc=0,
        qrr_ratio=1.2, trr_hot_resid=-0.0261, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=110, didt=1e+08, VR=85,
        qrr_cold_nc=150, trr_cold_ns=60, qrr_hot_nc=180, trr_hot_ns=67),
    ("infineon", "AUIRFS4115-7P"): dict(n_tau=0.6988, q0_basis='none', q0_nc=0,
        qrr_ratio=1.5, trr_hot_resid=-0.0592, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=62, didt=1e+08, VR=130,
        qrr_cold_nc=300, trr_cold_ns=86, qrr_hot_nc=450, trr_hot_ns=110),
    ("infineon", "AUIRFS4115-7TRL"): dict(n_tau=0.6043, q0_basis='none', q0_nc=0,
        qrr_ratio=1.4207, trr_hot_resid=-0.0282, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=63, didt=1e+08, VR=130,
        qrr_cold_nc=271, trr_cold_ns=82, qrr_hot_nc=385, trr_hot_ns=99),
    ("infineon", "AUIRFS4115TRL"): dict(n_tau=0.6988, q0_basis='none', q0_nc=0,
        qrr_ratio=1.5, trr_hot_resid=-0.0592, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=62, didt=1e+08, VR=130,
        qrr_cold_nc=300, trr_cold_ns=86, qrr_hot_nc=450, trr_hot_ns=110),
    ("infineon", "AUIRFS4310ZTRL"): dict(n_tau=0.7314, q0_basis='none', q0_nc=0,
        qrr_ratio=1.5345, trr_hot_resid=-0.0157, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=75, didt=1e+08, VR=85,
        qrr_cold_nc=58, trr_cold_ns=40, qrr_hot_nc=89, trr_hot_ns=49),
    ("infineon", "AUIRFS4410Z"): dict(n_tau=0.7462, q0_basis='none', q0_nc=0,
        qrr_ratio=1.5472, trr_hot_resid=0.0006, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=58, didt=1e+08, VR=85,
        qrr_cold_nc=53, trr_cold_ns=38, qrr_hot_nc=82, trr_hot_ns=46),
    ("infineon", "AUIRFSL4010"): dict(n_tau=0.4192, q0_basis='none', q0_nc=0,
        qrr_ratio=1.2762, trr_hot_resid=-0.0068, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=106, didt=1e+08, VR=85,
        qrr_cold_nc=210, trr_cold_ns=72, qrr_hot_nc=268, trr_hot_ns=81),
    ("infineon", "IRF100B201"): dict(n_tau=0.5372, q0_basis='none', q0_nc=0,
        qrr_ratio=1.3667, trr_hot_resid=-0.0144, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=115, didt=1e+08, VR=85,
        qrr_cold_nc=90, trr_cold_ns=47, qrr_hot_nc=123, trr_hot_ns=55),
    ("infineon", "IRF100B202"): dict(n_tau=0.4063, q0_basis='none', q0_nc=0,
        qrr_ratio=1.2667, trr_hot_resid=-0.021, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=58, didt=1e+08, VR=85,
        qrr_cold_nc=105, trr_cold_ns=51, qrr_hot_nc=133, trr_hot_ns=58),
    ("infineon", "IRF100S201"): dict(n_tau=0.5372, q0_basis='none', q0_nc=0,
        qrr_ratio=1.3667, trr_hot_resid=-0.0144, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=115, didt=1e+08, VR=85,
        qrr_cold_nc=90, trr_cold_ns=47, qrr_hot_nc=123, trr_hot_ns=55),
    ("infineon", "IRF135B203"): dict(n_tau=0.4956, q0_basis='none', q0_nc=0,
        qrr_ratio=1.3333, trr_hot_resid=-0.0171, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=77, didt=1e+08, VR=115,
        qrr_cold_nc=270, trr_cold_ns=80, qrr_hot_nc=360, trr_hot_ns=93),
    ("infineon", "IRF135S203"): dict(n_tau=0.4956, q0_basis='none', q0_nc=0,
        qrr_ratio=1.3333, trr_hot_resid=-0.0171, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=77, didt=1e+08, VR=115,
        qrr_cold_nc=270, trr_cold_ns=80, qrr_hot_nc=360, trr_hot_ns=93),
    ("infineon", "IRF135SA204"): dict(n_tau=0.5368, q0_basis='none', q0_nc=0,
        qrr_ratio=1.3651, trr_hot_resid=0.004, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=96, didt=1e+08, VR=115,
        qrr_cold_nc=315, trr_cold_ns=85, qrr_hot_nc=430, trr_hot_ns=98),
    ("infineon", "IRFB4137"): dict(n_tau=0.7496, q0_basis='none', q0_nc=0,
        qrr_ratio=1.4359, trr_hot_resid=-0.0892, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=24, didt=1e+08, VR=255,
        qrr_cold_nc=1739, trr_cold_ns=302, qrr_hot_nc=2497, trr_hot_ns=379),
    ("infineon", "IRFP4768"): dict(n_tau=0.7815, q0_basis='none', q0_nc=0,
        qrr_ratio=1.527, trr_hot_resid=0.103, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=56, didt=1e+08, VR=200,
        qrr_cold_nc=1480, trr_cold_ns=180, qrr_hot_nc=2260, trr_hot_ns=200),
    ("infineon", "IRFP4768PBF"): dict(n_tau=0.7815, q0_basis='none', q0_nc=0,
        qrr_ratio=1.527, trr_hot_resid=0.103, corroborated_row='cold',
        tj_cold=25, tj_hot=125, IF=56, didt=1e+08, VR=200,
        qrr_cold_nc=1480, trr_cold_ns=180, qrr_hot_nc=2260, trr_hot_ns=200),
}


def qrr_tj_table_for(mfr, mpn):
    """(mfr, mpn) -> entry dict or None; base-MPN variant fallback as elsewhere."""
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(QRR_TJ_TABLE, mfr, mpn)
    return dict(hit) if hit else None
