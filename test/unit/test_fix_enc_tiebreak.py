"""The non-visual tie-breakers in dslib.pdf.fix_encoding.

The visual matcher separated `l` from `I` by 0.0033 and `p` from `μ` by 0.0082
-- noise -- and lost both, turning three Infineon datasheets into "N-channeI,
normaI IeveI" and "OμtiMOS". Advance width and hole count decide those.

What these tests pin is mostly what the tie-breakers REFUSE to do, because a
tie-breaker that fires when it should not is worse than none: it overrides a
correct visual match with a guess, and it does so silently. So: no scale from
too few samples, no vote from the glyph being arbitrated, no promotion of a
character vision never shortlisted, and no change at all when a feature is
missing.
"""
import numpy as np
import pytest

from dslib.pdf.fix_encoding import (_CONFIDENT_MARGIN, _MAX_MEASURED_WIDTH_RATIO,
                                    _MIN_WIDTH_SAMPLES, _TIE_MARGIN, _break_tie,
                                    _calibrate_width_scale, _hole_count,
                                    _plausible_measured_widths, _reference_advances,
                                    _reference_glyphs, _replace_pdf_array)


# ------------------------------------------------------------------ hole count
def _box(holes=0, size=32):
    """A filled rectangle with `holes` square voids punched out of it."""
    a = np.zeros((size, size), dtype=np.float32)
    a[4:size - 4, 4:size - 4] = 1.0
    for i in range(holes):
        y = 7 + i * 9
        a[y:y + 6, 8:size - 8] = 0.0
    return a


@pytest.mark.parametrize('n', [0, 1, 2])
def test_hole_count_counts_enclosed_regions(n):
    assert _hole_count(_box(holes=n)) == n


def test_hole_count_ignores_open_notches():
    """A bowl that is open to the outside -- the whole point of the feature, it
    is what tells 'μ' from 'p' -- must not count."""
    a = np.zeros((32, 32), dtype=np.float32)
    a[4:28, 4:28] = 1.0
    a[10:18, 12:28] = 0.0  # notch cut in from the right edge, not enclosed
    assert _hole_count(a) == 0


def test_hole_count_ignores_antialiasing_specks():
    a = np.zeros((32, 32), dtype=np.float32)
    a[4:28, 4:28] = 1.0
    a[10, 10] = 0.0  # single pixel
    assert _hole_count(a) == 0


def test_hole_count_of_blank_is_zero_not_an_error():
    assert _hole_count(np.zeros((16, 16), dtype=np.float32)) == 0


@pytest.mark.parametrize('ch,expect', [
    ('p', 1), ('o', 1), ('e', 1), ('a', 1), ('0', 1), ('O', 1), ('Q', 1),
    ('μ', 0), ('u', 0), ('c', 0), ('C', 0), ('l', 0), ('I', 0), ('S', 0),
    ('B', 2), ('8', 2),
])
def test_hole_count_on_real_reference_glyphs(ch, expect):
    """Integration with the actual reference font. The pairs that matter are
    p/μ (the OμtiMOS bug) and C/0 -- the latter is the confusion that
    dslib/viz/curve_extract.py currently works around by hand."""
    variants = _reference_glyphs().get(ch)
    if not variants:
        pytest.skip('reference font lacks %r' % ch)
    assert any(_hole_count(v) == expect for v in variants)


# ------------------------------------------------------------ width calibration
def _ranked(**kw):
    """cid -> [(score, char)], built from {cid: (winner, margin, runner_up)}."""
    return {cid: [(0.9, win), (0.9 - margin, run)]
            for cid, (win, margin, run) in kw.items()}


def test_scale_is_none_below_the_sample_floor_not_one():
    """Absence of evidence must not encode 'reference metrics'. A default of
    1.0 would decide p (556) vs μ (576) -- 3.6% apart -- on an assumption
    about a font that was never measured."""
    ranked = _ranked(**{str(i): ('lImnop'[i], 0.5, 'x') for i in range(2)})
    ranked = {int(k): v for k, v in ranked.items()}
    adv = {cid: 500.0 for cid in ranked}
    assert len(ranked) < _MIN_WIDTH_SAMPLES
    assert _calibrate_width_scale(ranked, adv) is None


def test_scale_is_none_when_no_advances_are_available():
    ranked = {i: [(0.9, c), (0.2, 'x')] for i, c in enumerate('mnopqr')}
    assert _calibrate_width_scale(ranked, {}) is None


def test_ambiguous_glyphs_do_not_vote_on_the_scale():
    """A glyph inside the tie band is the one the scale will arbitrate. Letting
    it set that scale makes the arbitration self-confirming."""
    ref = _reference_advances()
    if not all(c in ref for c in 'mnopqr'):
        pytest.skip('reference advances unavailable')

    # Six confident glyphs, all exactly at reference width -> scale 1.0.
    confident = {i: [(0.9, c), (0.9 - _CONFIDENT_MARGIN * 2, 'x')]
                 for i, c in enumerate('mnopqr')}
    adv = {i: ref[c][0] for i, c in enumerate('mnopqr')}

    # Add one AMBIGUOUS glyph whose width is wildly off. If it were counted it
    # would drag the median; excluded, the scale stays 1.0.
    amb_cid = 99
    confident[amb_cid] = [(0.9, 'm'), (0.9 - _TIE_MARGIN / 2, 'n')]
    adv[amb_cid] = ref['m'][0] * 4.0

    assert _calibrate_width_scale(confident, adv) == pytest.approx(1.0, abs=1e-6)


def test_scale_tracks_a_uniformly_wider_font():
    ref = _reference_advances()
    if not all(c in ref for c in 'mnopqr'):
        pytest.skip('reference advances unavailable')
    ranked = {i: [(0.9, c), (0.1, 'x')] for i, c in enumerate('mnopqr')}
    adv = {i: ref[c][0] / 1.25 for i, c in enumerate('mnopqr')}
    assert _calibrate_width_scale(ranked, adv) == pytest.approx(1.25, rel=0.02)


# ------------------------------------------------------------------ tie-break
def test_no_rival_in_band_returns_the_visual_winner():
    scores = [(0.99, 'l'), (0.50, 'I')]
    assert _break_tie(scores, hole_count=0, emb_width=277.8, scale=1.0) == 'l'


def test_missing_features_change_nothing():
    """Every abstention path lands on the visual winner, never on a rival."""
    scores = [(0.9985, 'I'), (0.9952, 'l')]
    assert _break_tie(scores, None, None, None) == 'I'
    assert _break_tie(scores, None, 226.7, None) == 'I'      # no scale
    assert _break_tie(scores, None, None, 1.0) == 'I'        # no width
    assert _break_tie(scores, 0, 0.0, 1.0) == 'I'            # zero width


def test_width_flips_I_to_l_the_real_regression():
    """The exact numbers from BSC190N15NS3_G.pdf font Z_C00222 cid=60: vision
    said I by 0.0033, the embedded advance is 226.7, Arial is l=222.2 I=277.8.

    Asserting the DIRECTION, not merely that something changed -- 'the
    tie-break fired' passes just as well when it drops the correct answer.
    """
    scores = [(0.9985, 'I'), (0.9952, 'l')]
    assert _break_tie(scores, hole_count=0, emb_width=226.7, scale=1.0) == 'l'


def test_width_leaves_a_genuine_I_alone():
    """Same font, cid=35, advance 280 -> I really is I. The guard has to be
    two-sided or it just moves the error to the other letter."""
    scores = [(0.9794, 'I'), (0.9762, 'l')]
    assert _break_tie(scores, hole_count=0, emb_width=280.0, scale=1.0) == 'I'


def test_topology_flips_mu_to_p():
    """Z_C00221 cid=37: vision said μ by 0.0082. The glyph encloses a bowl;
    'p' does and 'μ' does not. Width cannot settle this one -- 556 vs 576 is
    inside the calibration's own error -- so topology has to."""
    scores = [(0.8437, 'μ'), (0.8355, 'p')]
    assert _break_tie(scores, hole_count=1, emb_width=534.0, scale=1.0) == 'p'


def test_topology_leaves_a_genuine_mu_alone():
    scores = [(0.8437, 'μ'), (0.8355, 'p')]
    assert _break_tie(scores, hole_count=0, emb_width=578.8, scale=1.0) == 'μ'


def test_topology_abstains_when_it_agrees_with_everyone():
    """If every shortlisted candidate has the observed hole count, the feature
    carries no information and must hand over to width rather than reorder."""
    scores = [(0.9985, 'I'), (0.9952, 'l')]           # both 0 holes
    assert _break_tie(scores, hole_count=0, emb_width=226.7, scale=1.0) == 'l'


def test_topology_abstains_when_it_agrees_with_nobody():
    """An observed count no candidate matches means the raster lied (a hairline
    bowl closed, or opened). Eliminating everything must not empty the
    shortlist and must not pick arbitrarily."""
    scores = [(0.9985, 'I'), (0.9952, 'l')]
    assert _break_tie(scores, hole_count=7, emb_width=None, scale=None) == 'I'


def test_a_character_outside_the_tie_band_can_never_win():
    """The features reorder a shortlist; they do not add to it. 'l' has the
    perfect width here but vision put it far down, so it must stay out."""
    scores = [(0.99, 'I'), (0.98, 'i'), (0.40, 'l')]
    got = _break_tie(scores, hole_count=0, emb_width=222.2, scale=1.0)
    assert got in ('I', 'i')


def test_width_needs_a_clear_margin_not_merely_a_smaller_error():
    """Two candidates a few percent apart are inside the calibration error.
    Flipping there trades one coin-toss for another."""
    ref = _reference_advances()
    if 'p' not in ref or 'μ' not in ref:
        pytest.skip('reference advances unavailable')
    # Sits between p and μ, slightly nearer p -- not a clear enough edge.
    between = (ref['p'][0] + ref['μ'][0]) / 2 - 2
    scores = [(0.8437, 'μ'), (0.8355, 'p')]
    assert _break_tie(scores, hole_count=None, emb_width=between, scale=1.0) == 'μ'


# ------------------------------------------------ nested /W array replacement
def test_replace_pdf_array_handles_nested_arrays():
    """A CIDFont /W array nests: `[ 9 [ 722 ] 11 12 333 ]`. The lazy regex this
    replaced stopped at the first INNER `]`, stranding `11 12 333 ]` at dict
    level; mupdf then rejected the object with 'invalid key in dict' and the
    exception aborted the whole repair, /ToUnicode included.
    """
    obj = ('<< /Type /Font /W [ 9 [ 722 ] 11 12 333 16 [ 333 278 ] ] '
           '/DW 1000 >>')
    out = _replace_pdf_array(obj, 'W', '[ 1 [500] ]')
    assert out == '<< /Type /Font /W [ 1 [500] ] /DW 1000 >>'


def test_replace_pdf_array_handles_flat_arrays():
    obj = '<< /FirstChar 32 /Widths [ 278 0 556 ] /LastChar 34 >>'
    out = _replace_pdf_array(obj, 'Widths', '[ 1 2 3 ]')
    assert out == '<< /FirstChar 32 /Widths [ 1 2 3 ] /LastChar 34 >>'


@pytest.mark.parametrize('obj', [
    '<< /Type /Font /DW 1000 >>',            # key absent
    '<< /Type /Font /W 5 0 R >>',            # key present but not an array
    '<< /Type /Font /W [ 9 [ 722 ] >>',      # unbalanced
])
def test_replace_pdf_array_returns_none_rather_than_a_broken_object(obj):
    """Every failure path yields None so the caller leaves the object alone.
    Emitting a half-rewritten dict is what produced the abort being fixed."""
    assert _replace_pdf_array(obj, 'W', '[ 1 [500] ]') is None


# ------------------------------------------------- measured-width plausibility
class _FI:
    def __init__(self, is_type3=False, is_type0=True, xref=1):
        self.is_type3 = is_type3
        self.is_type0 = is_type0
        self.xref = xref
        self.short_name = 'X'


def test_measured_widths_are_dropped_when_unverifiable():
    """No hmtx to check against -> no override. `_actual_advances` measures the
    gap between consecutive Tm operators, which is the glyph advance only when
    the text is set as a run; in HY0910D.pdf the median came out 54x the
    designed width (worst 832x) and declaring those as /W split every word
    apart. Unverifiable therefore has to mean 'do not apply', not 'apply'.
    """
    measured = {3: 500.0, 4: 600.0}

    class _Doc:
        def extract_font(self, xref):
            return ('F', 'ttf', 'Type0', b'')   # no usable binary

    assert _plausible_measured_widths(_Doc(), _FI(), measured) == {}


def test_type3_measured_widths_are_dropped():
    """Type3 glyphs are drawing procedures with no hmtx, so nothing can
    corroborate a measurement for them."""
    class _Doc:
        def extract_font(self, xref):
            raise AssertionError('must not be reached for Type3')

    assert _plausible_measured_widths(_Doc(), _FI(is_type3=True), {3: 500.0}) == {}


def test_empty_measurement_is_not_an_error():
    class _Doc:
        pass
    assert _plausible_measured_widths(_Doc(), _FI(), {}) == {}


def test_ratio_bound_is_two_sided():
    """Both an absurdly wide and an absurdly narrow measurement are wrong, and
    the bound has to reject both -- a one-sided check would still declare a
    5-unit advance for a 500-unit glyph."""
    assert _MAX_MEASURED_WIDTH_RATIO > 1
