"""Datasheet body-diode reverse-recovery TEST CONDITIONS, keyed by (mfr, mpn).

The parts DB stores `Qrr` and `trr` as flat scalars, but a scalar is meaningless without
the operating point it was measured at: Qrr scales STEEPLY with di/dt, and with IF and Tj.
The conditions live next to the Qrr/trr line in every datasheet ("VR=40V, IF=100A,
diF/dt=500A/us") but are not parsed into the pickle DB, so they are curated here.

How steeply, measured (2026-07-13): IPP022N12NM6 is the only part here whose datasheet quotes
Qrr at TWO di/dt points (IF=50A, Tj=25C): 155.2 nC @ 300 A/us and 412.1 nC @ 1000 A/us. That
is an exponent of **0.81**, NOT the 0.5 ("roughly sqrt") this docstring used to claim. The
Lauritzen-Ma fit reproduces it: fit on one point, predict the other, and Qrr lands within
3.5% / -4.9% with tau agreeing to 4% between the two rows.

Consumers:
  * dcdc-tools/loss lib/lm_diode.py — fits the Lauritzen-Ma charge-control body-diode
    subcircuit (tau, TM) from (Qrr, trr) AT THIS OPERATING POINT, so the transient deck
    reproduces the datasheet recovery SHAPE (which a one-time-constant TT diode cannot).
    NB: this is a FIDELITY fix, not a way to shrink Qrr. At a tight-loop converter's di/dt
    (~10x the datasheet's) the LM diode injects MORE charge than the TT diode it replaces,
    because Qrr grows with di/dt. The claim that TT "over-injects Qrr by ~5x and manufactures
    a fake avalanche" is RETRACTED (see the retraction block in lm_diode.py and
    fl4p/dcdc-tools#15): TT*IF = 15ns * 28A = 420 nC, only ~1.5x IPP019's 285 nC.
  * the analytic Qrr(di/dt) refinement (loss.py --qrr-didt-ref).

Fields per entry:
  IF    forward current the recovery was measured at [A]
  didt  commutation di/dt of the test [A/s]
  VR    reverse (blocking) voltage of the test [V] — informational
  Tj    junction temperature of the test [degC] (Infineon quotes 25C unless noted)

A part ABSENT here has no conditions: consumers MUST fail loud or fall back explicitly
rather than invent an operating point. See fl4p/fetlib#37.

THIS TABLE IS NO LONGER THE MAIN SOURCE. The premise above -- that the conditions are
not in the DB -- was wrong when it was written: dslib/conditions.py (2026-05-18, two
months before this file) already normalized `di/dt` from 20+ raw spellings, and 90.8%
of the Qrr fields in the shipped DB carry one. Nothing read them for Qrr, so this
registry was hand-curated to 8 parts instead. DatasheetFields.qrr_test_conditions()
now reads them, and attach_qrr_registries takes them at LOWEST precedence:

    qrr_points (per-row, two-point)  >  this file (hand-read)  >  parsed

Measured 2026-07-27 at the fugu3 design point (72->27 V, 900 W, 40 kHz; 3795 parts in
the Vds window, through dcdc_buck_ls's --qrr-op path), before -> after wiring parsed
conditions in:

    operating-point fit ran      1.9%  ->  72.3%   (2754 parsed, 52 2pt, 15 curated, 37 GaN)
    kept the flat datasheet Qrr  98.1% ->  26.7%

Agreement where truth exists: all 8 entries of this table are reproduced exactly by the
parsed path, and for the 79 qrr_points dies present in the DB by exact key the parsed
(Qrr, IF, di/dt) triple matches a real datasheet row every time -- none mis-paired.

Rescale magnitude: commutation di/dt at that design point is p50 ~4000 A/us against
datasheet test points of 100-500, and Qrr_op/Qrr_datasheet runs p10 2.4 / p50 6.3 /
p90 12.2, six parts falling.

NO LONGER A MIXED RANKING. Rows that cannot be fitted at the operating point kept the
vendor's gentle test-point charge while every fitted row paid the real (p50 ~6x)
commutation charge, so missing data read as a GOOD part -- 8 of the top 10 LS parts at
that design point were exactly those. generate_LS_power_loss_csv now excludes them
(dclib.powerloss.qrr_rankable_at_operating_point) and writes them to a sibling
`-LS-unranked-` CSV with the refusal reason, so they are dropped from the ranking but
not from the output. The filter is an ALLOWLIST -- a row is rankable only if it carries
an `op-` state the model actually evaluated -- so a future Qrr_src state defaults to
excluded rather than silently rankable. Measured after: 2858 ranked, 1121 excluded
(28.2%), and every ranked row is op-1pt-parsed / op-2pt / op-1pt / op-zero.

Of the 1121 exclusions, ~1031 are "no reverse-recovery test conditions" -- no IF/di-dt
readable off the Qrr row -- and 75 are parts where the HS gate charges (Qgs2/Qg_th/Vpl)
are missing, so no commutation di/dt could be formed at all. The first group is THIS
table's curation target: an entry here (or a fixed parse) puts a part back into the
ranking, and nothing else does. The second needs gate-charge parsing, not conditions.

CURATION IS A SMALL LEVER, measured 2026-07-27 rather than assumed. An excluded part
only distorts the ranking if it would have ranked WELL, and its non-Qrr loss (conduction
+ gate + Coss + dead-time) is a hard lower bound on its P_LS that is known regardless of
the missing test point. Ranking the ~995 exclusions by that floor: only 16 land inside
the current top-100. Reading those 16 datasheets:

  * 7  had a complete, quotable test point that also FITS -> curated here. Six of them
       needed the PDF rather than the extracted text (see the Infineon block below);
       reading the text alone had wrongly written them off as uncurateable.
  * 2  quote a complete point but their DB (Qrr, trr) pair is internally inconsistent
       -- the trr belongs to a different di/dt row -- so no conditions entry can rescue
       them (IPT013N08NM5LF, ISC014N08NM6). They need per-row data, i.e. qrr_points.
  * the rest have no Qrr at all, or no recovery line in the extracted text.

Those 7 (11 DB records with orderable-suffix variants) are now ranked, several near the
top: IAUCN08S7N013 lands at 2.39 W and IAUMN08S5N012G at 2.77 W against a 1.56 W leader.

The REST of the exclusions are mostly not a conditions-curation problem. They split into
per-row data (qrr_points), gate-charge parsing, and datasheets that genuinely omit the
operating point. Curating here is worth it for a part that matters -- it overrides the
parsed point -- but it is not the way to move the coverage number in bulk.

METHOD NOTE, since it changed the answer: judge curatability from the PDF, not from the
extracted text. Five of the six Infineon dies below look bare in `pdftotext` output
because their condition cell SPANS the trr and Qrr rows, and the sixth (IPT014N10N5) is
a print-to-PDF with no text layer at all -- 11 characters extract from the whole file.
`pdftotext -layout` recovered five; the last needed the page rendered and read.

See docs/qrr-parsed-conditions-spotcheck.md for the verification sample.
"""

QRR_CONDITIONS = {
    # Infineon OptiMOS -- conditions read from the "Reverse recovery charge" row of each
    # datasheet's body-diode table (dslib/datasheets/infineon/<MPN>.pdf.txt).
    ("infineon", "IPP019N08NF2S"): dict(IF=100.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP024N08NF2S"): dict(IF=100.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP055N08NF2S"): dict(IF=60.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP026N10NF2S"): dict(IF=100.0, didt=500e6, VR=50.0, Tj=25.0),
    # 100 V StrongIRFET2, Fugu2 HS candidate (fl4p/dcdc-tools#15). Rev 2.1: Qrr=247nC,
    # trr=37ns at these conditions. Without this entry the loss tool silently fell back
    # to the flat datasheet Qrr for an LS built from this part.
    ("infineon", "IPP050N10NF2S"): dict(IF=60.0, didt=500e6, VR=50.0, Tj=25.0),
    # fisi HS FET (dcdc-tools loss/examples/fisi.yaml). Qrr=189nC, trr=33ns at these
    # conditions. Needed because --body-diode lm builds the LM diode for BOTH sides of a
    # curve-mode deck (the HS body diode barely matters for a buck's Qrr, but the fit
    # fails loud without an operating point).
    ("infineon", "IPP040N08NF2S"): dict(IF=80.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP018N10N5"): dict(IF=100.0, didt=100e6, VR=50.0, Tj=25.0),
    # IPP022N12NM6 quotes TWO di/dt points (300 and 1000 A/us) -- the primary Qrr/trr row
    # in the parts DB is the 300 A/us one. BOTH rows now live in the generated
    # dslib/qrr_points.py and Qrr_op prefers the per-part two-point (tau, TM, q0) fit;
    # this single-point entry remains as the explicit fallback.
    ("infineon", "IPP022N12NM6"): dict(IF=50.0, didt=300e6, VR=60.0, Tj=25.0),

    # Alpha & Omega. Added 2026-07-27 from a targeted pass over the exclusions that
    # actually cost the ranking (see the note below this dict): AOGT68801 has the lowest
    # non-Qrr loss floor of every excluded part at the fugu3 point, i.e. it would rank
    # FIRST, and it was dropped only because its Qrr row parses to two IF values.
    #
    # Datasheet text: "Body Diode Reverse Recovery Charge ... IF=20A, di/dt=500A/ms".
    # The "A/ms" is the m/µ glyph substitution this corpus shows throughout (see
    # dslib/pdf/fix_encoding.py); read as 500 A/us. That is not a free choice -- at
    # 500 A/ms the pair is physically absurd, while at 500 A/us the LM fit gives
    # IRRM = 14.8 A on IF = 20 A (0.74x, squarely in the soft-recovery band). The fit
    # succeeding at the sane reading and failing at the other IS the corroboration.
    ("ao", "AOGT68801"): dict(IF=20.0, didt=500e6, VR=None, Tj=25.0),

    # --- the six high-impact Infineon exclusions, read off the PDFs 2026-07-27 --------
    # These were initially judged NOT curatable: the plain text extraction returned only
    # "diF/dt = 100 A/us" for them, and the nearest IF belonged to the Vsd row. Re-reading
    # with the table layout preserved (pdftotext -layout) recovers the full condition,
    # which sits in a cell SPANNING the trr and Qrr rows -- that span is why the key-based
    # parser attached it to trr and left Qrr bare.
    #
    # The earlier caution was justified: the recovery IF is NOT the Vsd row's current on
    # any of them. IAUCN08S7N013 recovers at 50 A while its Vsd row says 88 A, and the
    # IAUMN08S5N012G/013G pair recover at 50 A against a 100 A Vsd row. Taking the nearby
    # number would have been wrong by ~2x on four of the five.
    #
    # Each entry verified three ways: the condition string is quoted below, the datasheet
    # Qrr/trr match what the DB holds, and the Lauritzen-Ma fit succeeds with a physical
    # IRRM (0.03-0.18x IF -- these are soft, low-charge trench diodes).
    #
    # "V R=40 V, I F=50A, di F/dt =100 A/us"      Qrr 56 nC / trr 50 ns
    ("infineon", "IAUMN08S5N012G"): dict(IF=50.0, didt=100e6, VR=40.0, Tj=25.0),
    # "V R = 40 V, I F = 50 A, di F/dt = 100 A/us, T j = 25 C"   Qrr 177 nC / trr 86 ns
    ("infineon", "IAUTN08S5N012L"): dict(IF=50.0, didt=100e6, VR=40.0, Tj=25.0),
    # "V R=40 V, I F=50A, di F/dt =100 A/us"      Qrr 55 nC / trr 49 ns
    ("infineon", "IAUMN08S5N013G"): dict(IF=50.0, didt=100e6, VR=40.0, Tj=25.0),
    # "V R=40 V, I F=50A, di F/dt =100 A/us"      Qrr 34 nC / trr 44 ns  (Vsd row: 88 A)
    ("infineon", "IAUCN08S7N013"): dict(IF=50.0, didt=100e6, VR=40.0, Tj=25.0),
    # "VR=50 V, IF=100 A, diF/dt=500 A/us"        Qrr 437 nC / trr 49 ns
    ("infineon", "IPT015N10NF2S"): dict(IF=100.0, didt=500e6, VR=50.0, Tj=25.0),
    # IPT014N10N5 has NO text layer at all ("Microsoft: Print To PDF", 11 chars extracted)
    # -- read off the rendered page 5, Table 7 Reverse diode:
    # "VR=50 V, IF=100 A, diF/dt=100 A/us"        Qrr 316 nC / trr 103 ns
    ("infineon", "IPT014N10N5"): dict(IF=100.0, didt=100e6, VR=50.0, Tj=25.0),
}


def _cond_for(mfr, mpn):
    # exact key + the shared orderable-suffix fallback (dslib/mpn_match.py) —
    # strict so a family variant never inherits another die's conditions
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(QRR_CONDITIONS, mfr, mpn)
    return dict(hit) if hit else None


def qrr_conditions_for(mfr, mpn):
    """(mfr, mpn) -> dict(IF, didt, VR, Tj) or None if the part has no curated conditions."""
    return _cond_for(mfr, mpn)
