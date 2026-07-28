"""write_csv's full-precision sidecar.

The display CSV rounds every float to 3 s.f. and P_*/FoM columns to 2, so a booked loss
cannot be re-derived from it better than ~0.5% (P_rr = Vi*f*Qrr_eff audits kept hitting
that floor). write_csv therefore also writes <name>.full.csv with NO rounding, from the
same sorted frame, before the display rounding mutates it.
"""
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dslib import FULL_CSV_ONLY_COLUMNS, write_csv

VI, F = 72.0, 40e3
QRR_EFF_NC = 123.456789  # deliberately > 3 s.f. of information
P_RR = VI * F * QRR_EFF_NC * 1e-9


def _write(tmp_path):
    df = pd.DataFrame([
        dict(mpn="a", P_tot=1.234567, P_rr=P_RR, Qrr_eff=QRR_EFF_NC,
             Qrr_src="op-2pt", Qrr_q0_nC=12.3456789,
             Coss_provenance="curve:test:a",
             P_coss_audit='{"state":"ok"}'),
        dict(mpn="b", P_tot=0.765432, P_rr=P_RR / 3, Qrr_eff=QRR_EFF_NC / 3,
             Qrr_src="datasheet-flat", Qrr_q0_nC=4.1152263,
             Coss_provenance="scalar:Coss=900 pF @ 50 V (Coss_Vds)",
             P_coss_audit='{"state":"ok"}'),
    ])
    path = str(tmp_path / "fets.csv")
    write_csv(df, path)
    return path, path[:-len(".csv")] + ".full.csv"


def test_sidecar_round_trips_exactly(tmp_path):
    _, full = _write(tmp_path)
    r = pd.read_csv(full).set_index("mpn")
    # exact to float repr: the audit identity must close to machine precision
    assert math.isclose(r.loc["a", "Qrr_eff"], QRR_EFF_NC, rel_tol=1e-12)
    assert math.isclose(r.loc["a", "P_rr"], P_RR, rel_tol=1e-12)
    assert math.isclose(r.loc["a", "P_rr"], VI * F * r.loc["a", "Qrr_eff"] * 1e-9,
                        rel_tol=1e-12)


def test_display_csv_stays_rounded(tmp_path):
    path, _ = _write(tmp_path)
    r = pd.read_csv(path).set_index("mpn")
    # P_* at 2 s.f., other floats at 3 s.f. -- the sidecar must not have changed the
    # display contract (the 2 s.f. ranking table is a deliberate readability choice)
    assert r.loc["a", "P_rr"] == 0.36
    assert r.loc["a", "Qrr_eff"] == 123.0


def test_sidecar_and_display_share_the_sort_order(tmp_path):
    path, full = _write(tmp_path)
    assert (pd.read_csv(path)["mpn"].tolist()
            == pd.read_csv(full)["mpn"].tolist() == ["b", "a"])  # sorted by P_tot


def test_coss_provenance_is_in_display_and_full_csv(tmp_path):
    path, full = _write(tmp_path)
    display = pd.read_csv(path).set_index("mpn")
    audit = pd.read_csv(full).set_index("mpn")

    assert "Coss_provenance" not in FULL_CSV_ONLY_COLUMNS
    assert display.loc["a", "Coss_provenance"] == "curve:test:a"
    assert audit.loc["a", "Coss_provenance"] == "curve:test:a"
    assert display.loc["b", "Coss_provenance"] == (
        "scalar:Coss=900 pF @ 50 V (Coss_Vds)"
    )


def test_audit_columns_only_appear_in_full_csv(tmp_path):
    expected_full_only = {
        "Qrr_src",
        "Qrr_q0_nC",
        "Qrr_q0_basis",
        "Qrr_double_booking",
        "Qrr_double_booking_evidence",
        "Qrr_qoss_vr_nC",
        "Qrr_qoss_model_state",
        "Qrr_qoss_evidence",
        "Qrr_qoss_provenance",
        "Qrr_qoss_extrapolation_flags",
        "P_coss_scope",
        "P_coss_state",
        "P_coss_evidence",
        "P_coss_validation",
        "P_coss_audit",
    }
    assert FULL_CSV_ONLY_COLUMNS == expected_full_only

    df = pd.DataFrame([
        dict(mpn="audit-part", P_tot=1.0,
             **{column: f"{column}-value" for column in expected_full_only})
    ])
    path = str(tmp_path / "audit.csv")
    full = str(tmp_path / "audit.full.csv")
    write_csv(df, path)

    display_columns = set(pd.read_csv(path).columns)
    full_columns = set(pd.read_csv(full).columns)

    assert expected_full_only.isdisjoint(display_columns)
    assert expected_full_only <= full_columns
