"""Curated datasheet MIN/TYP/MAX process-corner bounds (dcdc#19 item 5).

Source: parameter tables of the vendor datasheets, HUMAN-READ from pages
rendered with pdftoppm (150 dpi) on 2026-07-20 — the pdftotext extraction of
these tables is column-scrambled and must not be trusted for curation. Each
entry cites the datasheet revision; the conditions columns are stored because
a bound is meaningless without its test condition.

Semantics — read before consuming:
  * `rds_max` is the SAME quantity dslib's MosfetSpecs.Rds_on already stores
    (datasheet max at full gate drive); `rds_typ` is the typ column of the
    SAME table row (same VGS/ID condition). A consumer replacing Rds must
    keep the row's conditions together.
  * `vgs_th_*` are the VGS(th) parameter-table bounds at the table's small
    sense current (`vgs_th_id_a`) — a DIFFERENT threshold definition than the
    power-law Vth_eff derived from gate charge. Consumers must use the
    *differences* (max−typ, typ−min) as corner SHIFTS, never substitute the
    absolute VGS(th) for Vth_eff.
  * `gfs_min` is a guaranteed floor for EVERY die: no corner variant may emit
    a law violating it. `gfs_typ` may be absent (e.g. StrongIRFET 2 tables
    publish min only).
  * Correlation is NOT stored here — corners are a consumer-side policy. The
    datasheet publishes independent per-parameter bounds; whether min-Vth is
    combined with max-Rds is the consumer's (documented) assumption.

Fail-closed: `corner_specs_for` returns the curated entry or None — an
uncurated part gets None, never a guessed corner.
"""

# (mfr, base MPN) -> dict of datasheet parameter-table bounds
CORNER_SPECS = {
    ("infineon", "IPP040N08NF2S"): dict(
        vgs_th_min=2.2, vgs_th_typ=3.0, vgs_th_max=3.8, vgs_th_id_a=85e-6,
        rds_typ=3.6e-3, rds_max=4.0e-3, rds_vgs_v=10.0, rds_id_a=80.0,
        gfs_min=63.0, gfs_typ=None, gfs_id_a=80.0,
        source="IPP040N08NF2S Final Data Sheet Rev 2.1 2022-06-15 Table 4 "
               "(human-read from rendered p.4, 2026-07-20)"),
    ("infineon", "IPP022N12NM6"): dict(
        vgs_th_min=2.6, vgs_th_typ=3.1, vgs_th_max=3.6, vgs_th_id_a=275e-6,
        rds_typ=1.9e-3, rds_max=2.2e-3, rds_vgs_v=10.0, rds_id_a=100.0,
        gfs_min=95.0, gfs_typ=190.0, gfs_id_a=100.0,
        source="IPP022N12NM6 Final Data Sheet Rev 2.0 2023-10-12 Table 4 "
               "(human-read from rendered p.4, 2026-07-20)"),
}


def corner_specs_for(mfr, mpn):
    """(mfr, mpn) -> dict of corner bounds or None (uncurated part).

    Same strict orderable-suffix matching as bv_specs_for — a bare startswith
    once served one part's data to a different family member.
    """
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(CORNER_SPECS, mfr, mpn)
    return dict(hit) if hit else None
