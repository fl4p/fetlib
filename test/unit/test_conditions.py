import pytest

from dslib.conditions import normalize_conditions


# ---------------------------------------------------------------------------
# Empty / degenerate inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('cond', [None, '', {}, [], (), 0, False])
def test_empty_inputs_return_empty_dict(cond):
    assert normalize_conditions(cond) == {}


def test_non_dict_non_iterable_returns_empty():
    assert normalize_conditions(object()) == {}


def test_all_none_values_dropped():
    # vishay-style cached parse: keys present but every value is None
    assert normalize_conditions({'i_f': None, 'didt': None, 'vds': None}) == {}


def test_dash_and_na_values_dropped():
    assert normalize_conditions({'Vds': '-', 'Vgs': 'N/A', 'I': 'none'}) == {}


# ---------------------------------------------------------------------------
# Qoss: keys should normalize to Vds, Vgs
# ---------------------------------------------------------------------------

def test_qoss_already_canonical():
    assert normalize_conditions({'Vds': 50.0, 'Vgs': 0.0}) == {'Vds': 50.0, 'Vgs': 0.0}


def test_qoss_uppercase_and_spaced_aliases():
    # 'V DS' (Tabula puts a space between sub/superscripts), 'VV GS' (OCR doubled the V)
    assert normalize_conditions({'V DS': 75.0, 'VV GS': 0.0}) == {'Vds': 75.0, 'Vgs': 0.0}


def test_qoss_vdd_is_vds():
    # Many onsemi/vishay datasheets test Qoss at VDD=bus voltage, semantically Vds.
    assert normalize_conditions({'VDD': 50.0, 'VGS': 0.0}) == {'Vds': 50.0, 'Vgs': 0.0}


def test_qoss_numeric_keyed_cell_with_embedded_condition_string():
    # Infineon Tabula row: condition text lives in one cell.
    cond = {0: 'Output charge1)', 1: 'Qoss', 2: '-', 3: '136', 4: '181', 5: 'nC',
            6: 'VDS=75 V, VGS=0 V'}
    assert normalize_conditions(cond, symbol='Qoss') == {'Vds': 75.0, 'Vgs': 0.0}


def test_qoss_numeric_keyed_cell_without_conditions_returns_empty():
    # Bare onsemi cells: just label, value, unit — no test conditions.
    cond = {0: 'Output Charge', 1: 'QOSS', 3: 87.0, 5: 'nC'}
    assert normalize_conditions(cond, symbol='Qoss') == {}


def test_qoss_ocr_vpp_ves_misread():
    # Some Infineon PDFs OCR 'VDD' as 'V pp' and 'VGS' as 'Ves'.
    cond = {0: 'V pp=50 V, Ves=0 V'}
    assert normalize_conditions(cond, symbol='Qoss') == {'Vds': 50.0, 'Vgs': 0.0}


def test_qoss_string_values_coerced_to_float():
    assert normalize_conditions({'Vds': '75', 'Vgs': '0'}) == {'Vds': 75.0, 'Vgs': 0.0}


def test_qoss_string_values_with_units_stripped():
    assert normalize_conditions({'Vds': '75 V', 'Vgs': '0V'}) == {'Vds': 75.0, 'Vgs': 0.0}


# ---------------------------------------------------------------------------
# Qrr: keys should normalize to di/dt, I, Vds
# ---------------------------------------------------------------------------

def test_qrr_already_canonical():
    assert normalize_conditions({'IF': 16.0, 'di/dt': 100.0}) == {'I': 16.0, 'di/dt': 100.0}


def test_qrr_infineon_regex_extracted_keys():
    # Infineon's QRR regex captures 'F/dt' (di stripped) and 'V R', 'I F' with internal spaces.
    cond = {'V R': 50.0, 'I F': 50.0, 'F/dt': 100.0}
    assert normalize_conditions(cond, symbol='Qrr') == {
        'Vds': 50.0, 'I': 50.0, 'di/dt': 100.0}


def test_qrr_vishay_cache_keys():
    # Cached vishay parser output uses lowercase keys with string values.
    cond = {'i_f': '10', 'didt': '100', 'vds': '25'}
    assert normalize_conditions(cond, symbol='Qrr') == {
        'I': 10.0, 'di/dt': 100.0, 'Vds': 25.0}


def test_qrr_isd_dis_dt_aliases():
    # onsemi: 'ISD' = source-drain current, 'dIS/dt' = corresponding slew rate.
    cond = {'ISD': 50.0, 'dIS/dt': 300.0}
    assert normalize_conditions(cond, symbol='Qrr') == {'I': 50.0, 'di/dt': 300.0}


def test_qrr_idr_didr_dt_aliases():
    # toshiba: IDR = drain-reverse current, -dIDR/dt
    cond = {'IDR': 14.0, 'dIDR/dt': 100.0}
    assert normalize_conditions(cond, symbol='Qrr') == {'I': 14.0, 'di/dt': 100.0}


def test_qrr_numeric_keyed_cell_with_infineon_condition_string():
    cond = {0: 'Reverse recovery charge', 1: 'Qrr', 4: '177', 5: 'nC',
            6: 'VR=40 V, IF=50 A, diF/dt=100 A/μs'}
    assert normalize_conditions(cond, symbol='Qrr') == {
        'Vds': 40.0, 'I': 50.0, 'di/dt': 100.0}


def test_qrr_numeric_keyed_cell_with_noisy_leading_text():
    # 'dIF/dt' is preceded by label/symbol text in the same cell.
    cond = {0: 'Reverse Recovery Charge3 Qrr dIF/dt=100A/μs', 4: '98', 6: 'nC'}
    assert normalize_conditions(cond, symbol='Qrr') == {'di/dt': 100.0}


def test_qrr_cell_split_dr_dt():
    # toshiba cell splits "dIDR/dt = ..." across cells, leaving "DR/dt = 100 A/μs".
    cond = {0: '-dIReverse recovery charge', 1: 'Q rr', 2: 'DR/dt = 100 A/μs',
            5: '43', 7: 'nC'}
    assert normalize_conditions(cond, symbol='Qrr') == {'di/dt': 100.0}


def test_qrr_freeform_string():
    assert normalize_conditions('IF = 10 A, di/dt = 300 A/ms') == {
        'I': 10.0, 'di/dt': 300.0}


def test_qrr_list_of_cells():
    cond = ['Reverse Recovery Charge', 'Qrr', 'VR=50 V, IF=25 A, diF/dt=100 A/μs',
            '-', '128', '256', 'nC']
    assert normalize_conditions(cond, symbol='Qrr') == {
        'Vds': 50.0, 'I': 25.0, 'di/dt': 100.0}


# ---------------------------------------------------------------------------
# Extras: temperatures, gate resistance, frequency, etc. that often co-occur
# ---------------------------------------------------------------------------

def test_temperature_aliases():
    assert normalize_conditions({'TJ': 125.0}) == {'Tj': 125.0}
    assert normalize_conditions({'Tvj': 150.0}) == {'Tj': 150.0}
    assert normalize_conditions({'T C': 25.0}) == {'Tc': 25.0}


def test_gate_resistance_variants():
    assert normalize_conditions({'RG': 1.8}) == {'Rg': 1.8}
    assert normalize_conditions({'R G': 6.0}) == {'Rg': 6.0}
    assert normalize_conditions({'RGon': 4.7}) == {'Rg_on': 4.7}
    assert normalize_conditions({'RG(ext)': 1.0}) == {'Rg_ext': 1.0}


def test_frequency_aliases():
    assert normalize_conditions({'f': 1e6}) == {'f': 1e6}
    assert normalize_conditions({'Frequency': 100000.0}) == {'f': 100000.0}


def test_tdead_scientific_notation_value():
    # cached value is "1.0000000000000002e-06" (1 µs as seconds)
    assert normalize_conditions({'tdead': '1.0000000000000002e-06'}) == {
        'tdead': pytest.approx(1e-6)}


# ---------------------------------------------------------------------------
# Edge cases / robustness
# ---------------------------------------------------------------------------

def test_unknown_keys_are_dropped():
    assert normalize_conditions({'foo': 1.0, 'Vds': 50.0}) == {'Vds': 50.0}


def test_first_occurrence_wins_when_aliases_collide():
    # 'IF' and 'IS' both collapse to 'I' — the first occurrence is kept.
    out = normalize_conditions({'IF': 10.0, 'IS': 50.0})
    assert out == {'I': 10.0}


def test_mixed_str_and_numeric_keys():
    # String-keyed conditions take precedence, numeric-keyed values fill gaps.
    cond = {'Vgs': 0.0, 0: 'VDS = 75 V'}
    assert normalize_conditions(cond) == {'Vgs': 0.0, 'Vds': 75.0}


def test_numeric_value_in_dict_passes_through():
    # mixed int / float / str values all coerced to float
    assert normalize_conditions({'Vds': 75, 'Vgs': 0.0, 'I': '25'}) == {
        'Vds': 75.0, 'Vgs': 0.0, 'I': 25.0}


def test_negative_di_dt():
    # some onsemi parts list negative slew rates ("-100 A/µs")
    assert normalize_conditions({'di/dt': '-100'}) == {'di/dt': -100.0}


def test_symbol_argument_is_optional():
    # The `symbol` arg is informational only; output is identical with or without it.
    cond = {0: 'VDS=75 V, VGS=0 V'}
    assert normalize_conditions(cond) == normalize_conditions(cond, symbol='Qoss')


def test_does_not_mutate_input():
    cond_in = {'V DS': 75.0, 'VV GS': 0.0}
    snapshot = dict(cond_in)
    normalize_conditions(cond_in)
    assert cond_in == snapshot