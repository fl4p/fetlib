"""Curated gate/channel datasheet specs that the parts-lib pickle predates.

The gate-charge table's TEST CURRENT (`Id_gc`) is NOT the continuous rating (dslib
`Id` = ID_25): the datasheet measures Qgs/Qg_th/Qgd/Qsw and Vplateau at a specific
drain current — e.g. IPP040N08NF2S at VDD=40 V, ID=80 A while ID_25=115 A, and
IPP022N12NM6 at ID=50 A while ID_25=203 A (4x apart). A channel reconstruction that
anchors its transconductance on the continuous rating is 1.4-4x too stiff (found
2026-07-14 while validating dslib against the datasheets: both the loss tool's recon
gm and its curve-tier Miller plateau depended on the wrong current).

`gfs` (forward transconductance, usually a MIN-only spec, at its own test current
`Id_gfs`) and `Vgs_th` (gate threshold TYP, at sub-mA sense current) are detected by
the PDF parser (dslib/pdf/expr.py) but were never consumed into MosfetSpecs, so the
pickled DB does not carry them. They are curated here — human-read from the local
datasheets (datasheets/<mfr>/<mpn>.pdf.txt) — and attached at load time by
dslib.store.load_parts(), same pattern as coss_curves/qrr_conditions. A future DB
rebuild can populate them from the parser; this module then only fills gaps.

Cross-validation on the five parts below (2026-07-14): the charge-partition threshold
Vth = Vpl*Qg_th/Qgs lands within 5.4% of the datasheet VGS(th) typ on every part — the
gate-charge table and the threshold spec are mutually consistent, so the channel
anchors derived from them are datasheet-consistent (a sanity check on the partition,
not proof of the full transfer law; see loss/lib/models.derive_channel in dcdc-tools).
"""

# (mfr, base MPN) -> dict:
#   Id_gc  [A] gate-charge table test current (the Qgs/Qgd/Vplateau anchor)
#   gfs_min / gfs_typ [S] forward transconductance spec at Id_gfs [A] (typ often absent)
#   Vgs_th [V] gate threshold TYP (datasheet min/max spread is ~±0.8 V around it)
#   Id_vsd [A] the DIODE-forward test current: the IF at which the datasheet quotes
#          Vsd (VGS=0, Tj=25 °C on all five). Vsd is a TERMINAL voltage at THIS
#          current — a diode-Is calibration must subtract the series-R drop at
#          Id_vsd, and must not reuse Id_gc (a gate-charge current, not a diode
#          condition) — fetmodel anchor blocker 2026-07-14.
# Orderable suffixes (…AKSA1/…AKMA1) resolve via the same startswith fallback as
# qrr_conditions.
GATE_SPECS = {
    ("infineon", "IPP040N08NF2S"): dict(Id_gc=80.0, gfs_min=63.0, Id_gfs=80.0,
                                        Vgs_th=3.0, Id_vsd=80.0),
    ("infineon", "IPP022N12NM6"): dict(Id_gc=50.0, gfs_min=95.0, gfs_typ=190.0,
                                       Id_gfs=100.0, Vgs_th=3.1, Id_vsd=100.0),
    ("infineon", "IPP055N08NF2S"): dict(Id_gc=60.0, gfs_min=46.0, Id_gfs=60.0,
                                        Vgs_th=3.0, Id_vsd=60.0),
    ("infineon", "IPP019N08NF2S"): dict(Id_gc=100.0, gfs_min=110.0, Id_gfs=100.0,
                                        Vgs_th=3.0, Id_vsd=100.0),
    ("infineon", "IPP024N08NF2S"): dict(Id_gc=100.0, gfs_min=94.0, Id_gfs=100.0,
                                        Vgs_th=3.0, Id_vsd=100.0),
    # The two 100 V parts Fugu2 is actually built with (HS 2x IPP050N10NF2S, LS 2x
    # IPP039N10N5, attested 2026-08-11). Added 2026-08-14 from the local datasheets
    # (desk item dslib-curation-gaps): every loss run warned that Id_vsd was missing and
    # the body-diode Vf anchor drifted to 30/50/60 A depending on model tier.
    # IPP050N10NF2S Rev 2.1: Qg table VDD=50 V, ID=60 A; gfs 57 S MIN-only at ID=60 A
    # (|VDS|>=2*ID*RDSon_max); VGS(th) 2.2/3.0/3.8; VSD 0.92/1.2 at VGS=0, IF=60 A.
    ("infineon", "IPP050N10NF2S"): dict(Id_gc=60.0, gfs_min=57.0, Id_gfs=60.0,
                                        Vgs_th=3.0, Id_vsd=60.0),
    # IPP039N10N5 Rev 2.0: Qg table VDD=50 V, ID=50 A; gfs 65 min / 130 typ at ID=50 A;
    # VGS(th) 2.2/3.0/3.8; VSD 0.9/1.2 at VGS=0, IF=50 A. NB the 130 S typ is the value
    # the channel fit already rejects (transfer exponent outside [1.05, 2.8]) — curated
    # faithfully anyway; resolving that rejection needs the transfer-curve digitisation,
    # not a different number here.
    ("infineon", "IPP039N10N5"): dict(Id_gc=50.0, gfs_min=65.0, gfs_typ=130.0,
                                      Id_gfs=50.0, Vgs_th=3.0, Id_vsd=50.0),
}


def _norm(hit):
    # every key present, NaN for unspecified — a half-populated spec object would make
    # consumers see None (attr set) for one part and AttributeError-default for another
    full = dict(Id_gc=float("nan"), gfs_min=float("nan"), gfs_typ=float("nan"),
                Id_gfs=float("nan"), Vgs_th=float("nan"), Id_vsd=float("nan"))
    full.update(hit)
    return full


def gate_specs_for(mfr, mpn):
    """(mfr, mpn) -> dict(Id_gc, gfs_min, gfs_typ, Id_gfs, Vgs_th) (NaN-filled) or None."""
    # exact key + the shared orderable-suffix fallback (dslib/mpn_match.py) —
    # strict so a family variant never inherits another die's gate anchors
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(GATE_SPECS, mfr, mpn)
    return _norm(hit) if hit else None
