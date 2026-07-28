"""Multi-block selection in the qrr layout-conditions extractor.

apps/emit_qrr_layout_conditions.py used to return the FIRST recovery block on the sheet
and refuse the part when the DB's Qrr did not match it -- 209 parts per harvest, all the
multi-di/dt sheets whose DB charge came from a later block. select_block() now serves
the block that PRINTS the DB's value. These tests pin the selection direction with a
synthetic two-block sheet: not just that a guard fires, but WHICH conditions survive
(a selector that "worked" by always taking block 1 would pass a mere it-fired test).

The extractor regexes themselves stay pinned by `--calibrate` against the hand-read
entries; this file only covers the selection layer on top.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

# apps/ is not a package; load the generator module directly.
_spec = importlib.util.spec_from_file_location(
    "emit_qrr_layout_conditions",
    os.path.join(_HERE, "..", "apps", "emit_qrr_layout_conditions.py"))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

# Two recovery blocks, one row per line, the shape pdftotext -layout produces for the
# single-line-row sheets (goford/crmicro style). Block 1: 100 A/us. Block 2: 1000 A/us.
TWO_BLOCKS = "\n".join([
    "Reverse recovery time trr IF=25 A, di/dt=100 A/us 35 ns",
    "Reverse recovery charge Qrr 65 nC",
    "Reverse recovery time trr IF=25 A, di/dt=1000 A/us 25 ns",
    "Reverse recovery charge Qrr 120 nC",
])
# Same charge under two condition sets, but DIFFERENT printed trr: resolvable.
SAME_QRR_TRR_DIFFERS = "\n".join([
    "Reverse recovery time trr IF=5 A, di/dt=100 A/us 35 ns",
    "Reverse recovery charge Qrr 65 nC",
    "Reverse recovery time trr IF=5 A, di/dt=1000 A/us 12 ns",
    "Reverse recovery charge Qrr 65 nC",
])
# Same charge AND same trr under two condition sets: genuinely ambiguous.
AMBIGUOUS = "\n".join([
    "Reverse recovery time trr IF=5 A, di/dt=100 A/us 30 ns",
    "Reverse recovery charge Qrr 65 nC",
    "Reverse recovery time trr IF=5 A, di/dt=1000 A/us 30 ns",
    "Reverse recovery charge Qrr 65 nC",
])


def test_extract_all_blocks_sees_both_blocks():
    blocks = gen.extract_all_blocks(TWO_BLOCKS)
    assert [c["didt"] for c, _ in blocks] == [100e6, 1000e6]
    assert [c["qrr_seen"] for c, _ in blocks] == [[65.0], [120.0]]


def test_first_block_contract_unchanged():
    # extract() keeps the first-block contract --calibrate depends on.
    c = gen.extract(TWO_BLOCKS)
    assert c["didt"] == 100e6 and c["qrr_seen"] == [65.0]


def test_db_value_from_the_second_block_selects_the_second_block():
    # THE recovered class: DB Qrr belongs to the later block. The old first-block
    # check refused this part outright ('wrong block').
    c, why = gen.select_block(gen.extract_all_blocks(TWO_BLOCKS), qrr=120, trr=25)
    assert why is None
    assert c["didt"] == 1000e6 and c["IF"] == 25  # block 2's conditions, not block 1's


def test_db_value_from_the_first_block_still_selects_the_first():
    c, why = gen.select_block(gen.extract_all_blocks(TWO_BLOCKS), qrr=65, trr=35)
    assert why is None
    assert c["didt"] == 100e6


def test_no_block_printing_the_db_value_is_refused():
    # Known-bad: a DB charge no block prints (e.g. from a table the extractor cannot
    # see, or a corrupt value). Absence of a match must refuse, never fall back to
    # "closest block".
    c, why = gen.select_block(gen.extract_all_blocks(TWO_BLOCKS), qrr=300, trr=35)
    assert c is None and why == "Qrr value mismatch (no block prints the DB value)"


def test_trr_comatch_guards_a_coincidental_qrr_match():
    # Block 2 prints Qrr=120 but its trr row says 25 ns; a DB trr of 80 ns means the
    # match is not the DB's row after all.
    c, why = gen.select_block(gen.extract_all_blocks(TWO_BLOCKS), qrr=120, trr=80)
    assert c is None and why == "trr value mismatch"


def test_same_charge_is_disambiguated_by_the_printed_trr():
    # Both blocks print 65 nC, but their trr rows differ (35 vs 12 ns): the co-match
    # picks the block whose PAIR matches the DB. (First discovered by writing the
    # ambiguity test below with differing trr and watching it resolve instead.)
    c, why = gen.select_block(gen.extract_all_blocks(SAME_QRR_TRR_DIFFERS),
                              qrr=65, trr=12)
    assert why is None
    assert c["didt"] == 1000e6


def test_exact_print_beats_a_within_tolerance_print():
    # FDH055N15A's shape: two blocks print 342 and 348 nC; the DB stored 342. 348 sits
    # inside _near's 2% parse-rounding band, but ambiguity means EQUALLY close -- the
    # block printing the value exactly must win, and with block 1's conditions.
    sheet = "\n".join([
        "Reverse recovery time trr IF=120 A, di/dt=100 A/us 105 ns",
        "Reverse recovery charge Qrr 342 nC",
        "Reverse recovery time trr IF=30 A, di/dt=100 A/us 105 ns",
        "Reverse recovery charge Qrr 348 nC",
    ])
    c, why = gen.select_block(gen.extract_all_blocks(sheet), qrr=342, trr=105)
    assert why is None
    assert c["IF"] == 120


def test_same_charge_and_same_trr_is_refused_as_ambiguous():
    # Both blocks print (65 nC, 30 ns) under different di/dt: no way to know which row
    # the DB stored. First-wins here would silently serve a wrong test point.
    blocks = gen.extract_all_blocks(AMBIGUOUS)
    assert len(blocks) == 2
    c, why = gen.select_block(blocks, qrr=65, trr=30)
    assert c is None
    assert why == "ambiguous: DB Qrr matches blocks with different conditions"


def test_uc_printed_charge_is_compared_in_nc():
    # ao/AOTL66515 shape: sheet prints '1.18 uC', the DB (correctly normalised)
    # holds 1180 nC. The cross-check must compare in one unit or it refuses every
    # uC-printing sheet -- 4 of 15 sampled mismatches were exactly this.
    sheet = "\n".join([
        "trr Body Diode Reverse Recovery Time IF=20A, di/dt=500A/us 84 ns",
        "Qrr Body Diode Reverse Recovery Charge IF=20A, di/dt=500A/us 1.18 µC",
    ])
    blocks = gen.extract_all_blocks(sheet)
    assert blocks and blocks[0][0]["qrr_seen"][-1] == 1180.0
    c, why = gen.select_block(blocks, qrr=1180, trr=84)
    assert why is None and c["didt"] == 500e6


def test_uc_blocks_disambiguate_on_the_printed_tj():
    # st/STP25N018M9 shape: 0.9 uC at 25 C and 1.9 uC at 150 C, same IF/didt. The DB
    # stored 900 nC; only the 25 C block prints it, and its conditions must carry
    # Tj=25 -- not the other block's 150.
    sheet = "\n".join([
        "trr Reverse recovery time ISD = 55 A, di/dt = 100 A/us, - 151 ns",
        "Qrr Reverse recovery charge VDD = 100 V - 0.9 µC",
        "trr Reverse recovery time ISD = 55 A, di/dt = 100 A/us, - 213 ns",
        "Qrr Reverse recovery charge VDD = 100 V, TJ = 150 °C - 1.9 µC",
    ])
    c, why = gen.select_block(gen.extract_all_blocks(sheet), qrr=900, trr=151)
    assert why is None
    assert c["Tj"] == 25.0 and c["IF"] == 55.0


def test_bare_c_unit_is_not_scaled():
    # A mangled unit ('1.3 2.0 C', the lost-micro class) matches no prefix: the
    # printed value stays unscaled and the part keeps refusing, instead of the
    # comparison guessing a magnitude that makes it pass.
    sheet = "\n".join([
        "trr Reverse recovery time IF = 20 A, di/dt = 100 A/us - 35 ns",
        "Qrr Reverse recovery charge - 1.3 2.0 C",
    ])
    blocks = gen.extract_all_blocks(sheet)
    assert blocks and blocks[0][0]["qrr_seen"] == [1.3, 2.0]
    c, why = gen.select_block(blocks, qrr=1300, trr=35)
    assert c is None and why == "Qrr value mismatch (no block prints the DB value)"


def test_empty_sheet_is_refused_not_matched():
    c, why = gen.select_block([], qrr=65, trr=35)
    assert c is None and why == "no recovery block in layout text"
