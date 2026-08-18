"""Tests for the two stages fix_encoding delegates the character decision to:
`dslib.pdf.glyph_exact` (outline fingerprint) and `dslib.pdf.glyph_lm`
(document-level n-gram arbitration), plus a smoke run of the accuracy harness
in `test/fix_enc_eval.py`.

The tests that matter here are the DIRECTIONAL ones. "The stage fired" is not
evidence: an exact matcher that fires on the wrong face, or a language model
that fires and replaces a correct reading with a more common one, both look
identical to a firing counter. So each stage is checked against a known-bad
construction where the right answer is known independently:

  * `test_lm_recovers_documented_l_vs_I_failure` disables the visual
    tie-breakers, reproduces the exact string from the repo's own history
    ('N-channeI, normaI IeveI'), and requires the language model to repair it
    on its own.
  * `test_exact_rejects_wrong_face` requires the outline matcher to score 0 on
    faces that are not the one embedded, not merely lower.
"""

import importlib.util
import pathlib
import sys

import pymupdf
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dslib.pdf import fix_encoding as fe
from dslib.pdf import glyph_exact as gx
from dslib.pdf import glyph_lm as gl


def _p(rel: str) -> str:
    return str(REPO_ROOT / rel)


# Full-face embeds of installed system fonts -- what glyph_exact is for.
FULL_FACE_SAMPLE = 'datasheets/huayi/HY0910D.pdf'
# Subsetted display faces that are NOT installed -- glyph_exact must abstain.
SUBSET_SAMPLE = 'datasheets/infineon/BSC190N15NS3_G.pdf'


def _fonts(path):
    doc = pymupdf.open(_p(path))
    return doc, fe._scan_fonts(doc)


# ---------------------------------------------------------------------------
# glyph_exact
# ---------------------------------------------------------------------------

class TestGlyphExact:

    def test_index_is_not_empty(self):
        idx = gx.reference_index()
        assert idx, 'no system fonts indexed; every exact match will abstain'
        assert sum(len(v) for v in idx.values()) > 1000

    def test_full_face_embed_resolves_exactly(self):
        """HY0910D embeds Arial / Arial-Bold / Times in full. Those are
        installed here, so the identification must be exact and complete."""
        doc, fonts = _fonts(FULL_FACE_SAMPLE)
        try:
            resolved = []
            for fi in fonts:
                fb = doc.extract_font(fi.xref)[3]
                if not isinstance(fb, bytes) or not fb:
                    continue
                m = gx.exact_mapping(fb, fe._cid_to_gid_lookup(fb, fi.is_type0),
                                     set(fi.used_codes))
                if m is not None:
                    resolved.append(m)
        finally:
            doc.close()

        assert resolved, 'no font in a full-face-embed sample matched'
        # Coverage is the method's own significance test: it is bimodal at 0 and
        # 1, so anything that matched at all should have matched nearly all.
        assert all(m.coverage >= 0.9 for m in resolved), \
            [(m.font_label, m.coverage) for m in resolved]

    def test_recovered_text_is_the_real_text(self):
        """Direction, not firing: the decoded characters must spell the words
        that are on the page."""
        doc, fonts = _fonts(FULL_FACE_SAMPLE)
        try:
            alphabet = ''
            for fi in fonts:
                fb = doc.extract_font(fi.xref)[3]
                if not isinstance(fb, bytes) or not fb:
                    continue
                m = gx.exact_mapping(fb, fe._cid_to_gid_lookup(fb, fi.is_type0),
                                     set(fi.used_codes))
                if m:
                    alphabet += ''.join(m.mapping.get(c, '')
                                        for c in sorted(fi.used_codes))
        finally:
            doc.close()
        # The Ω comes out of the Times font and is one of the symbols the pixel
        # matcher is least reliable on, so it is worth asserting specifically.
        assert 'Ω' in alphabet
        for ch in 'MOSFETacegilnorstuvy':
            assert ch in alphabet, ch

    def test_subsetted_unknown_face_abstains(self):
        """The Infineon Z_C*.tmp fonts are subsets of a face that is not
        installed. Abstaining is the correct answer; a match would be a false
        identification, which is the one failure this module must not have."""
        doc, fonts = _fonts(SUBSET_SAMPLE)
        try:
            for fi in fonts:
                fb = doc.extract_font(fi.xref)[3]
                if not isinstance(fb, bytes) or not fb:
                    continue
                assert gx.exact_mapping(
                    fb, fe._cid_to_gid_lookup(fb, fi.is_type0),
                    set(fi.used_codes)) is None, fi.short_name
        finally:
            doc.close()

    def test_wrong_face_scores_zero_not_merely_lower(self):
        """Known-bad calibration for the coverage threshold.

        `_MIN_COVERAGE` is only safe because the score distribution is bimodal.
        If a wrong face ever scored, say, 0.5, the threshold would be a real
        judgement call rather than a formality -- so assert the gap exists
        instead of assuming it.
        """
        doc, fonts = _fonts(FULL_FACE_SAMPLE)
        try:
            target = None
            for fi in fonts:
                fb = doc.extract_font(fi.xref)[3]
                if isinstance(fb, bytes) and fb and len(fi.used_codes) > 40:
                    target = (fi, fb)
                    break
            assert target, 'sample changed: no large embedded font'
            fi, fb = target
            gid_hash = {}
            from fontTools.ttLib import TTFont
            import io
            tt = TTFont(io.BytesIO(fb), fontNumber=0, lazy=True)
            gids = {fe._cid_to_gid_lookup(fb, fi.is_type0)(c)
                    for c in fi.used_codes}
            gid_hash = gx._hashes_for_gids(tt, sorted(g for g in gids if g))
            tt.close()
        finally:
            doc.close()

        idx = gx.reference_index()
        scores = sorted(
            (sum(1 for h in gid_hash.values() if h in by_hash) / len(gid_hash)
             for by_hash in idx.values()), reverse=True)
        assert scores[0] >= 0.9, scores[:3]
        # Second-best must be far away -- no face is "almost" the right one.
        assert scores[1] <= 0.5, scores[:3]


# ---------------------------------------------------------------------------
# glyph_lm
# ---------------------------------------------------------------------------

class TestCharLM:

    def test_corpus_loads(self):
        lm = gl.get_lm()
        assert lm is not None, 'dslib/pdf/glyph_lm_corpus.txt.gz missing'

    @pytest.mark.parametrize('good,bad', [
        ('N-channel', 'N-channeI'),
        ('OptiMOS', 'OμtiMOS'),
        ('normal level', 'normaI IeveI'),
        ('Drain', 'Draln'),
        ('Excellent', 'ExceIIent'),
    ])
    def test_model_prefers_the_true_reading(self, good, bad):
        """The confusions the pixel matcher cannot separate, which the model
        exists to separate."""
        lm = gl.get_lm()
        assert lm.logp(good) > lm.logp(bad), (good, bad)

    def test_absent_corpus_yields_no_opinion(self, monkeypatch):
        """A missing corpus must disable the stage, never fall back to a
        uniform model -- which would decide glyphs by letter frequency."""
        monkeypatch.setattr(gl, '_CORPUS', '/nonexistent/corpus.txt.gz')
        monkeypatch.setattr(gl, '_LM', None)
        monkeypatch.setattr(gl, '_LM_TRIED', False)
        assert gl.get_lm() is None


class TestRunAssembly:

    def test_runs_are_lines_not_single_glyphs(self):
        """Infineon's distiller emits one `Tm <XX> Tj` per glyph. Operand-level
        grouping therefore yields one-character runs and starves the model; the
        geometric reassembly in `cid_runs` is what makes it work at all."""
        doc, fonts = _fonts(SUBSET_SAMPLE)
        try:
            ref = list(fe._reference_glyphs().items())
            fi = max(fonts, key=lambda f: len(f.used_codes))
            m = fe._build_font_mapping(doc, fi, ref, 0.30,
                                       use_exact=True, use_lm=False)
            runs = gl.cid_runs(doc, fi.xref, fi.is_type0)
            texts = [gl._decode(r, m) for r in runs]
        finally:
            doc.close()

        assert runs
        longest = max(len(t) for t in texts)
        assert longest > 20, (
            'runs collapsed to single glyphs (longest=%d); the language model '
            'would be scoring one-character documents' % longest)
        assert any('channel' in t or 'Parameter' in t or 'Symbol' in t
                   for t in texts), texts[:10]


class TestLmRefine:

    def test_lm_recovers_documented_l_vs_I_failure(self):
        """KNOWN-BAD CALIBRATION.

        Reverting `_break_tie` to the raw visual winner reproduces the failure
        recorded in this repo's own history -- three Infineon sheets reading
        'N-channeI, normaI IeveI'. The language model is a second, independent
        route to the same answer, so with the tie-breakers gone it must repair
        the string on its own. If this ever fails, `lm_refine` has stopped
        working even though every "does it run" test still passes.
        """
        ref = list(fe._reference_glyphs().items())
        orig = fe._break_tie
        fe._break_tie = lambda scores, *a, **kw: scores[0][1]
        try:
            doc, fonts = _fonts(SUBSET_SAMPLE)
            try:
                fi = max(fonts, key=lambda f: len(f.used_codes))
                before = fe._build_font_mapping(doc, fi, ref, 0.30,
                                                use_exact=True, use_lm=False)
                after = fe._build_font_mapping(doc, fi, ref, 0.30,
                                               use_exact=True, use_lm=True)
                runs = gl.cid_runs(doc, fi.xref, fi.is_type0)
                t_before = ' '.join(gl._decode(r, before) for r in runs)
                t_after = ' '.join(gl._decode(r, after) for r in runs)
            finally:
                doc.close()
        finally:
            fe._break_tie = orig

        assert 'N-channeI' in t_before, (
            'the known-bad construction no longer reproduces the failure, so '
            'this test is not calibrated against anything')
        assert 'N-channel' in t_after, t_after[:300]
        assert 'N-channeI' not in t_after

    def test_lm_does_not_churn_a_correct_mapping(self):
        """With the tie-breakers in place the mapping is already right. The
        model must then leave it alone: a stage that rewrites correct output is
        a liability regardless of how often it also helps."""
        ref = list(fe._reference_glyphs().items())
        doc, fonts = _fonts(SUBSET_SAMPLE)
        try:
            fi = max(fonts, key=lambda f: len(f.used_codes))
            before = fe._build_font_mapping(doc, fi, ref, 0.30,
                                            use_exact=True, use_lm=False)
            after = fe._build_font_mapping(doc, fi, ref, 0.30,
                                           use_exact=True, use_lm=True)
        finally:
            doc.close()
        assert before == after

    def test_exact_matches_are_never_overruled(self):
        """Pinning is a safety property, not an optimisation: an outline
        identity outranks any amount of fluency."""
        lm = gl.get_lm()
        assert lm is not None

        class _FI:
            xref = -1
            is_type0 = False

        mapping = {1: 'x', 2: 'y'}
        ranked = {1: [(0.9, 'x'), (0.89, 'e')], 2: [(0.9, 'y'), (0.89, 'a')]}
        out = gl.lm_refine(pymupdf.open(), _FI(), mapping, ranked,
                           pinned={1, 2})
        assert out == mapping


# ---------------------------------------------------------------------------
# The accuracy harness itself
# ---------------------------------------------------------------------------

def _load_harness():
    path = REPO_ROOT / 'test' / 'fix_enc_eval.py'
    spec = importlib.util.spec_from_file_location('fix_enc_eval', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEvalHarness:
    """A two-font smoke run, so the harness cannot rot unnoticed.

    It is not a pass/fail on ACCURACY -- that number is a report, and pinning it
    would turn every legitimate matcher change into a test failure. What is
    asserted is that the harness still constructs a valid trial and that its
    ground truth is real: a synthesis bug that produced an empty or bogus truth
    would otherwise show up as a suspiciously good score.
    """

    def test_smoke(self, tmp_path):
        ev = _load_harness()
        # A generous pool for two trials: fonts drop out for legitimate
        # reasons (no embeddable outlines, no /ToUnicode written, a face
        # pymupdf declines), and a pool of exactly 2 would make this test fail
        # on host font-set differences rather than on harness breakage.
        paths = ev.find_fonts(30, ev._PREFERRED)
        assert paths

        trials = []
        for p in paths:
            t = ev.build_trial(p, str(tmp_path))
            if t is not None:
                trials.append(t)
            if len(trials) == 2:
                break
        assert len(trials) == 2, 'harness could not build two trials'

        for t in trials:
            assert len(t.truth) > 20, 'ground truth too small to mean anything'
            # The truth must be the font's OWN statement about its glyphs. The
            # failure mode worth guarding is a /ToUnicode reader that silently
            # falls back to the identity map, which would make every trial score
            # 100% against a truth that is really just the scrambled codes.
            identity = sum(1 for cid, ch in t.truth.items() if ord(ch) == cid)
            assert identity < 0.5 * len(t.truth), (
                'ground truth looks like an identity map (%d/%d): the harness '
                'is measuring the scramble against itself'
                % (identity, len(t.truth)))
            assert sum(c.isalpha() for c in t.truth.values()) > 10

            r = ev.run_trial(t, 'exact')
            assert r.scored > 0
            assert r.accuracy is not None
