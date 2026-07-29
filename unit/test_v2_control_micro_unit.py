import pytest

from dslib.v2 import parse_datasheet
from dslib.v2.chars import _normalize_char


def test_control_glyph_5_is_micro_prefix():
    assert _normalize_char("\x05") == "µ"


def test_ixfx150n15_qrr_control_micro_unit():
    ds = parse_datasheet("datasheets/littelfuse/IXFX150N15.pdf", mfr="littelfuse", mpn="IXFX150N15")
    qrr = ds.fields_filled["Qrr"]
    assert qrr.typ == pytest.approx(1100.0)
    assert qrr.unit == "nC"
