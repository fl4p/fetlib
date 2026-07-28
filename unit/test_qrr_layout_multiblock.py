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


# The IR/AUIR layout, verbatim shape of infineon/IRFP4768PBF: label lines carry no
# values; value rows sit above/below, one per Tj, self-tagged; ONE test condition is
# spread vertically over the section, with VDD on the row ABOVE the trr label.
IR_SECTION = "\n".join([
    "                    ––– 180 –––   TJ = 25°C     VDD = 200V",
    "trr    Reverse Recovery Time                ns",
    "                    ––– 200 –––   TJ = 125°C    IF = 56A,",
    "                    ––– 1480 –––  TJ = 25°C  di/dt = 100A/µs",
    "Qrr    Reverse Recovery Charge              nC",
    "                    ––– 2260 –––  TJ = 125°C",
    "IRRM   Reverse Recovery Current   –––  16  –––  A TJ = 25°C",
])


def test_ir_layout_yields_one_candidate_per_tj_row():
    blocks = gen.extract_all_blocks(IR_SECTION)
    assert [(c["Tj"], c["qrr_seen"]) for c, _ in blocks] == [
        (25.0, [1480.0]), (125.0, [2260.0])]
    # same-Tj trr attribution: 180@25, 200@125 -- never the other row's time
    assert [(c["Tj"], c["trr_seen"]) for c, _ in blocks] == [
        (25.0, [180.0]), (125.0, [200.0])]
    # the VDD row above the trr label is part of the section's condition cell
    assert all(c["IF"] == 56 and c["didt"] == 100e6 and c["VR"] == 200
               for c, _ in blocks)


def test_ir_layout_tj_follows_the_matched_row():
    blocks = gen.extract_all_blocks(IR_SECTION)
    c, why = gen.select_block(blocks, qrr=1480, trr=180)
    assert why is None and c["Tj"] == 25.0
    c, why = gen.select_block(blocks, qrr=2260, trr=200)
    assert why is None and c["Tj"] == 125.0


def test_ir_layout_same_tj_trr_comatch_refuses_a_cross_tj_pair():
    # DB (Qrr@25, trr@125) is an inconsistent pair; the co-match against the SAME-Tj
    # trr row must refuse it rather than let the 125C time vouch for the 25C charge.
    c, why = gen.select_block(gen.extract_all_blocks(IR_SECTION), qrr=1480, trr=200)
    assert c is None and why == "trr value mismatch"


def test_ir_layout_typ_max_rows():
    # AUIRFP4110 shape: two numbers per row (typ max)
    sheet = "\n".join([
        "            ––– 50 80    TJ = 25°C    VDD = 75V",
        "trr    Reverse Recovery Time     ns",
        "            ––– 60 90    TJ = 125°C   IF = 75A,",
        "            ––– 94 140   TJ = 25°C di/dt = 100A/µs",
        "Qrr    Reverse Recovery Charge   nC",
        "            ––– 140 210  TJ = 125°C",
    ])
    c, why = gen.select_block(gen.extract_all_blocks(sheet), qrr=94, trr=50)
    assert why is None
    assert c["Tj"] == 25.0 and c["IF"] == 75 and c["qrr_seen"] == [94.0, 140.0]


def test_label_row_with_values_never_takes_the_ir_path():
    # A normal sheet whose label line prints the values must be untouched by the IR
    # parser even if a TJ-tagged row happens to sit nearby.
    sheet = "\n".join([
        "trr Reverse recovery time IF = 20 A, di/dt = 100 A/us - 35 ns",
        "Qrr Reverse recovery charge - 65 nC",
        "  ––– 999 –––  TJ = 125°C",
    ])
    blocks = gen.extract_all_blocks(sheet)
    assert len(blocks) == 1 and blocks[0][0]["qrr_seen"] == [65.0]


def test_empty_sheet_is_refused_not_matched():
    c, why = gen.select_block([], qrr=65, trr=35)
    assert c is None and why == "no recovery block in layout text"


# --- 2026-07-28 layout classes (census of the 776 'no recovery block' rejects) ---

# Infineon OptiMOS 3 (N3G): the recovery current is 'I F=I S', a cross-reference to the
# diode continuous forward current rating row a few lines up. The VSD row carries a
# DIFFERENT current (50 A here, deliberately != IS) so a window that leaks across the
# forward-voltage row is caught as a wrong IF, not as a coincidental pass.
N3G_IF_IS = "\n".join([
    "Diode continous forward current      IS          -    -    100   A",
    "Diode pulse current                  I S,pulse   -    -    400   A",
    "Diode forward voltage                V SD        -    1.0  1.2   V   V GS=0 V, I F=50 A, T j=25 °C",
    "Reverse recovery time                t rr   V R=40 V, I F=I S,   -   73   -   ns",
    "                                     Q rr   di F/dt =100 A/µs",
    "Reverse recovery charge                     -   136   -   nC",
])


def test_n3g_if_is_resolves_from_the_rating_row():
    blocks = gen.extract_all_blocks(N3G_IF_IS)
    assert len(blocks) == 1
    c = blocks[0][0]
    # 100 (the IS rating row) -- not 400 (pulse row), not 50 (VSD row's IF)
    assert c["IF"] == 100.0 and c["didt"] == 100e6 and c["VR"] == 40.0
    assert c["qrr_seen"] == [136.0]


def test_n3g_if_is_without_a_rating_row_is_refused_not_guessed():
    # Known-bad: the cross-reference dangles. The block must vanish rather than ship
    # any fallback current.
    sheet = "\n".join(N3G_IF_IS.split("\n")[2:])   # drop the IS and pulse rows
    assert gen.extract_all_blocks(sheet) == []


# onsemi 6H-series: 'Charge Time ta' / 'Discharge Time tb' rows space the trr label
# 4 rows above the Qrr label (old scan depth 3 never found it -> no conditions). The
# VSD row above must stay outside the window: its IS = 20 A is the wrong current.
ONSEMI_TA_TB = "\n".join([
    "Forward Diode Voltage        VSD    VGS = 0 V, IS = 20 A   TJ = 25°C   0.77  1.2  V",
    "Reverse Recovery Time        tRR    VGS = 0 V, dIS/dt = 100 A/µs,   59   ns",
    "                                    IS = 50 A",
    "Charge Time                  ta     33",
    "Discharge Time               tb     25",
    "Reverse Recovery Charge      QRR    73   nC",
])


def test_onsemi_ta_tb_rows_reach_the_trr_conditions():
    blocks = gen.extract_all_blocks(ONSEMI_TA_TB)
    assert len(blocks) == 1
    c = blocks[0][0]
    assert c["IF"] == 50.0 and c["didt"] == 100e6   # 50 A -- never VSD's 20 A
    assert c["qrr_seen"] == [73.0]
    assert 59.0 in c["trr_seen"]


# ST F7: the label wraps over three lines ('Reverse / Qrr recovery / charge'); no line
# prints 'recovery charge'. The anchor is the Qrr-before-'recover' value row.
ST_WRAPPED = "\n".join([
    "         VSD (1)   ISD = 110 A, VGS = 0    -   1.2   V",
    "                   Reverse",
    "  trr                                      -   60   -   ns",
    "                   recovery time",
    "                   ISD = 110 A,",
    "                   Reverse",
    "                   di/dt = 100 A/µs,",
    "  Qrr    recovery                          -   83   -   nC",
    "         charge    VDD = 80 V, Tj = 25°C (see Figure 14. Test",
    "                   circuit for inductive load switching and diode",
    "                   recovery times)",
])


def test_st_wrapped_label_extracts_the_full_condition_set():
    blocks = gen.extract_all_blocks(ST_WRAPPED)
    assert len(blocks) == 1
    c = blocks[0][0]
    assert c["IF"] == 110.0 and c["didt"] == 100e6 and c["VR"] == 80.0
    assert c["Tj"] == 25.0 and c["qrr_seen"] == [83.0]


def test_anchor_matches_the_separator_variants():
    for line in ("Reverse RecoveryCharge ––– 94 140 nC",
                 "Body Diode Reverse-Recovery Charge QRR — 45 — nC",
                 "Qrr Reverse−Recovery Charge − 65 65 nC",
                 "Qr recovered charge IS = 100 A; dIS/dt = -100 A/µs",
                 "Qrr recovery - 83 - nC"):
        assert gen.RE_QRR_ROW.search(line), line


def test_marketing_bullet_still_never_becomes_a_block():
    # Bullets anchor (they always did) but carry no conditions, so no block may
    # survive -- for the Qrr-first form the bullet's '(Qrr)' trails 'recovery' and
    # must not even anchor.
    body = "\n".join([
        "  Fast intrinsic diode with low reverse recovery charge (Qrr)",
        "  100% avalanche tested, di/dt = 100 A/µs ruggedness",
    ])
    assert gen.extract_all_blocks(body) == []
    assert not gen.RE_QRR_ROW.search("low reverse recovery (Qrr)")
