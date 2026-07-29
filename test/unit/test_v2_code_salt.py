"""Calibration for v2_code_salt: the key must move when the derivation moves, and must
NOT move underneath a process that is already running.

Two properties, and they pull in opposite directions, which is why both are tested here:

  (a) every declared source reaches the signature   -- else an edit serves stale numbers
  (b) the signature is PINNED for the process       -- else a concurrent edit re-keys a
      run that is already in flight

(b) is the one that was missing. The salt was passed to @disk_cache as a bare callable and
disk_cache resolves callable salts at CALL time, so it re-read the files on every
parse_datasheet. Measured 2026-07-28 in this repo, which is routinely worked by several
agents at once: a full run started 21:20:48; another session saved dslib/v2/__init__.py at
21:57 and dslib/v2/tables.py at 22:20 and again at 22:31. The key moved three times mid-run,
each move orphaning what had been parsed so far (~1,670 entries by the first flip) and
re-parsing the same PDFs under the next generation. The cache dir held ten generations for a
~3k corpus. field_repr_salt and chart_digitizer_salt already snapshot theirs for exactly
this reason; v2 was the one that did not.

Hermetic: everything perturbs COPIES under tmp_path. Rewriting live sources in place would
be destroyed silently by a concurrent edit -- see the same note in test_field_repr_salt.py.
"""
import os
import shutil

import pytest

import dslib.v2 as V2
from dslib.v2 import _V2_DEP_SOURCES, _V2_SOURCES, _compute_v2_code_salt, v2_code_salt

# (label, is_dep) for each declared input, in the order the signature consumes them.
_INPUTS = [(n, False) for n in _V2_SOURCES] + \
          [(os.path.basename(p), True) for p in _V2_DEP_SOURCES]
_IDS = [('dep:' if d else 'v2:') + n for n, d in _INPUTS]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the salt at a copy of its declared dependencies and clear the snapshot.

    monkeypatch restores _V2_CODE_SIG afterwards, so a test that forces the snapshot
    does not pin the real one for the rest of the session.
    """
    vdir = tmp_path / 'v2'
    vdir.mkdir()
    copies = {}
    for n in _V2_SOURCES:
        shutil.copyfile(os.path.join(V2._V2_DIR, n), vdir / n)
        copies[(n, False)] = str(vdir / n)

    deps = []
    for i, p in enumerate(_V2_DEP_SOURCES):
        # flattened and index-prefixed: dslib/v2/__init__.py and dslib/pdf/sheet/__init__.py
        # would otherwise collide on basename
        dst = tmp_path / ('dep%d_%s' % (i, os.path.basename(p)))
        shutil.copyfile(p, dst)
        deps.append(str(dst))
        copies[(os.path.basename(p), True)] = str(dst)

    monkeypatch.setattr(V2, '_V2_DIR', str(vdir))
    monkeypatch.setattr(V2, '_V2_DEP_SOURCES', tuple(deps))
    monkeypatch.setattr(V2, '_V2_CODE_SIG', None)

    def perturb(label, is_dep):
        with open(copies[(label, is_dep)], 'ab') as fh:
            fh.write(b'\n# perturbed\n')

    return perturb


def test_snapshot_is_stable_across_calls():
    assert v2_code_salt() == v2_code_salt()


def test_snapshot_shape_is_unchanged():
    """The key VALUE must survive this refactor -- a different shape orphans the whole
    cache. Three components: source signature, backend, the `any` detect regex."""
    salt = v2_code_salt()
    assert isinstance(salt, tuple) and len(salt) == 3
    assert salt[0].startswith('v2-src:')


def test_sandbox_reproduces_a_real_signature(sandbox):
    """Guards the guard. If the copy did not produce a well-formed signature, every
    perturbation below would be measuring something other than production."""
    assert _compute_v2_code_salt()[0].startswith('v2-src:')


@pytest.mark.parametrize('label,is_dep', _INPUTS, ids=_IDS)
def test_every_declared_source_reaches_the_signature(label, is_dep, sandbox):
    """(a). A source that does not reach the signature is a silent hole: the code that
    derives the number changes and the cache keeps serving the pre-change parse."""
    before = _compute_v2_code_salt()
    sandbox(label, is_dep)
    assert _compute_v2_code_salt() != before, '%s does not reach the salt' % label


@pytest.mark.parametrize('label,is_dep', _INPUTS, ids=_IDS)
def test_snapshot_is_pinned_against_a_concurrent_edit(label, is_dep, sandbox):
    """(b). The whole point. Paired with the test above, which proves the SAME
    perturbation does move a fresh signature -- without that pairing this passes
    trivially for a perturbation the salt cannot see anyway."""
    pinned = v2_code_salt()
    sandbox(label, is_dep)
    assert v2_code_salt() == pinned, '%s re-keyed a running process' % label


def test_pinned_snapshot_survives_a_deleted_dependency(sandbox):
    """Once pinned, a dependency vanishing mid-run must not change the key -- and must
    not raise either. The process is still running the code it hashed."""
    pinned = v2_code_salt()
    os.remove(os.path.join(V2._V2_DIR, _V2_SOURCES[0]))
    assert v2_code_salt() == pinned


def test_unreadable_dependency_raises_before_the_snapshot_is_taken(sandbox):
    """Absence of evidence must not encode a narrower key: a missing source RAISES
    rather than being skipped, so it can never be pinned as a valid generation."""
    os.remove(os.path.join(V2._V2_DIR, _V2_SOURCES[0]))
    with pytest.raises(FileNotFoundError):
        _compute_v2_code_salt()
    assert V2._V2_CODE_SIG is None, 'a failed compute must not pin a partial key'
