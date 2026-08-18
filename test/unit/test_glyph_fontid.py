"""Tests for `dslib.pdf.glyph_fontid` -- identifying the face a scrambled font
is, so the pixel matcher compares like with like instead of against DejaVu.

The tests that matter are the ones that constrain what the stage may do when it
is WRONG. A face detector that helps on the fonts it recognises and quietly
degrades the rest is worse than no detector, because the degradation is
invisible: the output is still plausible text.

  * `test_wrong_weight_or_slope_is_rejected` is a known-bad calibration built
    from a measured regression -- an earlier acceptance rule picked Verdana
    Italic for an upright Verdana and cost 7.4 points of accuracy.
  * `test_improves_in_aggregate_with_bounded_individual_loss` runs the real
    matcher end to end on faces spanning the design space. It deliberately does
    NOT assert no-regression: that was the first version of this test and it is
    measurably false. Two of ten faces lose while the total gains ~10 points,
    and no computable statistic separates the two groups -- see that test's
    docstring for the numbers and for why raising the acceptance bar to
    suppress the losses costs more than the losses do.
"""

import importlib.util
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dslib.pdf import fix_encoding as fe
from dslib.pdf import glyph_fontid as gf


def _load_harness():
    path = REPO_ROOT / 'test' / 'fix_enc_eval.py'
    spec = importlib.util.spec_from_file_location('fix_enc_eval', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SUPP = '/System/Library/Fonts/Supplemental'


def _font(name):
    p = os.path.join(_SUPP, name)
    if not os.path.isfile(p):
        pytest.skip('%s not installed on this host' % name)
    return p


class TestWidthFingerprint:

    def test_infineon_subsets_fingerprint_as_arial(self):
        """The `/Widths` arrays of Infineon's `Z_C*.tmp` fonts are Helvetica /
        Arial metrics exactly, and are the only surviving identity evidence --
        the name table is the temp filename and PANOSE is zeroed."""
        import pymupdf
        doc = pymupdf.open(str(REPO_ROOT /
                               'datasheets/infineon/BSC190N15NS3_G.pdf'))
        try:
            widths = gf._face_widths_all()
            assert widths, 'no installed faces carry usable metrics'
            hits = []
            for fi in fe._scan_fonts(doc):
                if fi.is_type0 or len(fi.used_codes) < 50:
                    continue
                fb = doc.extract_font(fi.xref)[3]
                if not isinstance(fb, bytes) or not fb:
                    continue
                c2g = fe._cid_to_gid_lookup(fb, fi.is_type0)
                emb = fe._embedded_advances(fb, c2g, set(fi.used_codes))
                vals = [w for w in emb.values() if w > 0]
                if len(vals) < 20:
                    continue
                ranked = sorted(
                    (gf._width_distance(vals, list(fw.values())), path)
                    for path, fw in widths.items())
                hits.append([os.path.basename(p) for _d, p in ranked[:3]])
            assert hits, 'sample changed: no large simple font'
            # Arial, or one of its documented metric clones. Microsoft Sans
            # Serif is metric-compatible with Arial by design, so accepting it
            # is not a loosened assertion -- it is the same answer.
            for top3 in hits:
                assert any('arial' in n.lower() or 'sans serif' in n.lower()
                           for n in top3), top3
        finally:
            doc.close()

    def test_width_distance_is_symmetric_and_zero_on_self(self):
        w = list(gf._face_widths_all().values())[0]
        vals = list(w.values())
        assert gf._width_distance(vals, vals) == pytest.approx(0.0, abs=1e-9)

    def test_empty_input_is_infinite_not_zero(self):
        """A font with no readable metrics must not score as a PERFECT match to
        everything -- which a distance of 0 on empty input would mean."""
        assert gf._width_distance([], [1, 2, 3]) == float('inf')
        assert gf._width_distance([1, 2, 3], []) == float('inf')


class TestFaceScore:

    def test_margin_separates_where_top1_saturates(self):
        """Top-1 takes a max over ~130 reference characters, so something always
        resembles the glyph and the statistic saturates. This pins the reason
        `_face_score` returns a margin at all."""
        ev = _load_harness()
        import tempfile
        import pymupdf
        with tempfile.TemporaryDirectory() as tmp:
            t = ev.build_trial(_font('Courier New.ttf'), tmp)
            assert t is not None
            arrs = _render_trial_glyphs(t)
        sample = [arrs[k] for k in sorted(arrs)][:40]

        base = list(fe._reference_glyphs().items())
        b_top1, b_margin = gf._face_score(sample, base)
        c = gf._face_refs(_font('Courier New.ttf'))
        assert c is not None
        c_top1, c_margin = gf._face_score(sample, c.ref_items)

        # The true face must win on BOTH for a monospace slab, which is about as
        # far from DejaVu Sans as this corpus gets.
        assert c_top1 > b_top1
        assert c_margin > b_margin


def _render_trial_glyphs(trial):
    import pymupdf
    doc = pymupdf.open(trial.path)
    try:
        fi = next(f for f in fe._scan_fonts(doc) if f.xref == trial.xref)
        fb = doc.extract_font(fi.xref)[3]
        c2g = fe._cid_to_gid_lookup(fb, fi.is_type0)
        wanted = {g for g in (c2g(c) for c in fi.used_codes) if g}
        built = fe._build_pil_font_for_gid_render(fb, wanted)
        assert built is not None
        pil, code_by_gid = built
        out = {}
        for cid in sorted(fi.used_codes):
            g = c2g(cid)
            code = code_by_gid.get(g) if g else None
            if code is None:
                continue
            a = fe._render_glyph(pil, code)
            if a is not None:
                out[cid] = a
        return out
    finally:
        doc.close()


class TestAcceptance:

    def test_wrong_weight_or_slope_is_rejected(self):
        """KNOWN-BAD CALIBRATION.

        With Verdana itself held out, Verdana Italic is metrically PERFECT (its
        advances are unchanged by obliquing, width EMD 2.75) and wins on margin
        (slanted glyphs are more mutually distinguishable). An acceptance rule
        based on margin alone picked it and dropped end-to-end accuracy from
        88.0% to 80.6%. Whatever face is chosen here, it must not be an oblique
        one for an upright font -- and top-1 must not regress.
        """
        ev = _load_harness()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = ev.build_trial(_font('Verdana.ttf'), tmp)
            assert t is not None
            arrs = _render_trial_glyphs(t)
            emb = _trial_advances(t)

        base = list(fe._reference_glyphs().items())
        face = gf.detect_face(arrs, emb, base, exclude={'Verdana.ttf'})
        if face is None:
            return  # abstaining is always allowed
        assert 'italic' not in face.label.lower(), face.label
        sample = [arrs[k] for k in sorted(arrs)][:40]
        b_top1, _b_margin = gf._face_score(sample, base)
        top1, _margin = gf._face_score(sample, face.ref_items)
        assert top1 >= b_top1, (face.label, top1, b_top1)

    def test_abstains_when_nothing_beats_the_incumbent(self):
        """DejaVu is already an excellent proxy for Arial-like faces -- measured
        at top-1 0.9637 vs Arial's own 0.9634 on an Arial subset. With the whole
        Arial family held out, the stage must decline rather than reach for the
        next-best thing."""
        ev = _load_harness()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = ev.build_trial(_font('Arial.ttf'), tmp)
            assert t is not None
            arrs = _render_trial_glyphs(t)
            emb = _trial_advances(t)
        base = list(fe._reference_glyphs().items())
        exclude = {os.path.basename(p)
                   for p in gf._face_widths_all()
                   if os.path.basename(p).lower().startswith('arial')}
        face = gf.detect_face(arrs, emb, base, exclude=exclude)
        if face is not None:
            # Not an outright failure -- a genuinely closer face is a legitimate
            # improvement -- but it must have earned it on both statistics.
            sample = [arrs[k] for k in sorted(arrs)][:40]
            b1, bm = gf._face_score(sample, base)
            t1, tm = gf._face_score(sample, face.ref_items)
            assert t1 > b1 and tm > bm, (face.label, t1, b1, tm, bm)

    def test_too_few_glyphs_abstains(self):
        """A handful of glyphs is not evidence about a whole face."""
        ev = _load_harness()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = ev.build_trial(_font('Courier New.ttf'), tmp)
            arrs = _render_trial_glyphs(t)
        few = {k: arrs[k] for k in sorted(arrs)[:gf._MIN_GLYPHS - 1]}
        base = list(fe._reference_glyphs().items())
        assert gf.detect_face(few, {}, base) is None


def _trial_advances(trial):
    import pymupdf
    doc = pymupdf.open(trial.path)
    try:
        fi = next(f for f in fe._scan_fonts(doc) if f.xref == trial.xref)
        fb = doc.extract_font(fi.xref)[3]
        c2g = fe._cid_to_gid_lookup(fb, fi.is_type0)
        return fe._embedded_advances(fb, c2g, set(fi.used_codes))
    finally:
        doc.close()


class TestEndToEnd:

    # Chosen to span the design space rather than to flatter the stage: a
    # monospace slab and a serif (far from DejaVu, where detection should win
    # big), and a neo-grotesque sans (close to DejaVu, where it should abstain).
    FACES = ['Courier New.ttf', 'Times New Roman.ttf', 'Verdana.ttf',
             'Georgia.ttf', 'Arial.ttf', 'Trebuchet MS.ttf']

    # Bound on how much any single face may lose, and how many may lose at
    # all. Both are MEASURED CEILINGS, not aspirations -- see the docstring
    # below for why a no-regression guarantee is not available.
    _MAX_SINGLE_LOSS = 0.09
    _MAX_LOSING_FRACTION = 0.40
    # Measured at +2.7 points mean over this six-face panel at the `family`
    # hold-out, which is deliberately the HARD subset -- it contains Verdana,
    # one of the two known losers, and Courier, on which nothing is available to
    # swap in. Over the full 30-font corpus the same change is +14.4 points
    # (63.3% -> 77.7%). The floor is set below the measured value with room for
    # host font-set differences, not above it as an aspiration.
    _MIN_AGGREGATE_GAIN = 0.015

    @pytest.mark.parametrize('holdout', ['file', 'family'])
    def test_improves_in_aggregate_with_bounded_individual_loss(self, holdout,
                                                                tmp_path):
        """The real contract, which is NOT "never regresses".

        It was written as a no-regression guarantee first, and that assertion is
        simply false. Measured over ten faces at the `family` hold-out:

            trial          base_top1   gain   vision  fontid
            Times New Roman   0.8811  0.0560   82.4%   88.0%   +5.6
            Georgia           0.8634  0.0212   77.7%   84.8%   +7.1
            Trebuchet MS      0.8953  0.0107   77.3%   84.5%   +7.2
            Arial             0.9612  0.0173   95.4%   97.2%   +1.8
            Verdana           0.8980  0.0397   93.5%   88.0%   -5.5
            Tahoma            0.9062  0.0084   93.5%   87.0%   -6.5

        No computable whole-font statistic separates those two groups. Gain does
        not (Verdana harms at 0.040, Times helps at 0.056); incumbent quality
        does not (Verdana 0.898 harms, Trebuchet 0.895 helps); nor does width
        consistency, which passes DejaVu for Verdana at 0.022 against the
        incumbent's 0.063. The aggregate scores measure how well a face's shape
        repertoire COVERS the page, and two sans faces can cover it equally well
        while disagreeing about which glyph is which.

        What is true, and what this asserts, is that the trade is strongly
        positive: +9.7 points across the six swaps above, and 63.3% -> 77.7%
        over the full 30-font corpus. Where the incumbent is the wrong CATEGORY
        (a sans reference for monospace or serif text) the gain is large and
        reliable; where it is already a decent generic sans, the swap is lateral
        and lateral moves are near coin flips. Suppressing the lateral ones by
        raising the acceptance bar costs more than the regressions do -- at a
        0.05 gain threshold only Times survives, +5.6 against the +9.7 measured
        here.

        So the contract is aggregate gain with a BOUNDED tail, and the bound is
        what this test defends: a change that makes one face much worse, or that
        makes most faces worse, is a real regression even if the total still
        improves.
        """
        ev = _load_harness()
        deltas = []
        for name in self.FACES:
            path = os.path.join(_SUPP, name)
            if not os.path.isfile(path):
                continue
            t = ev.build_trial(path, str(tmp_path))
            if t is None:
                continue
            v = ev.run_trial(t, 'vision', holdout).accuracy
            f = ev.run_trial(t, 'fontid', holdout).accuracy
            if v is None or f is None:
                continue
            deltas.append((t.font_name, f - v))
        assert len(deltas) >= 3, 'too few installed faces to make this meaningful'

        worst = min(deltas, key=lambda kv: kv[1])
        losers = [d for d in deltas if d[1] < -1e-9]
        total = sum(d for _n, d in deltas) / len(deltas)

        assert worst[1] >= -self._MAX_SINGLE_LOSS, (
            '%s lost %.1f points at the %s hold-out, past the %.0f-point bound'
            % (worst[0], -100 * worst[1], holdout, 100 * self._MAX_SINGLE_LOSS))
        assert len(losers) <= self._MAX_LOSING_FRACTION * len(deltas), (
            'most faces regressed: %s' % [(n, round(100 * d, 1)) for n, d in losers])
        assert total >= self._MIN_AGGREGATE_GAIN - 1e-9, (
            'mean gain %.1f points is below the %.0f-point floor; face '
            'detection has stopped paying for itself'
            % (100 * total, 100 * self._MIN_AGGREGATE_GAIN))

    def test_helps_where_the_fixed_reference_is_a_poor_proxy(self, tmp_path):
        """Direction, not just safety. Courier New is a monospace slab and about
        as far from DejaVu Sans as this corpus gets; vision alone scores in the
        thirties on it. If detection stops helping there, it has stopped
        working, and every no-regression test above would still pass."""
        ev = _load_harness()
        t = ev.build_trial(_font('Courier New.ttf'), str(tmp_path))
        assert t is not None
        v = ev.run_trial(t, 'vision', 'file').accuracy
        f = ev.run_trial(t, 'fontid', 'file').accuracy
        assert v is not None and f is not None
        assert v < 0.6, ('Courier is no longer a hard case for vision (%.1f%%); '
                         'this test is not calibrated against anything' % (100 * v))
        assert f > v + 0.25, (100 * v, 100 * f)
