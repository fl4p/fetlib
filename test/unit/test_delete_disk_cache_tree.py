"""delete_disk_cache_tree must actually delete, and refuse to delete outside the cache.

The bug: its shutil.rmtree was commented out from the day it was introduced
(886fb686), so it logged 'deleting %s/**' and removed nothing -- provenance
claiming more than was done. Nothing in the repo ever asserted that a deletion
HAPPENED, which is how it survived; test_deletes_real_subtree below is that
missing assertion. delete_module_disk_cache_tree had a second, independent
no-op: it built its prefix from mod.__name__ (dotted, e.g. 'dslib.pdf.parse')
while keys are written under mod.__file__, so even a working rmtree would have
found nothing. The module-case fixture here is built by calling a real
@disk_cache-decorated function -- NOT by hand-assembling the path -- because a
hand-assembled fixture encoding the same wrong layout is exactly how that
defect went unnoticed.

Everything runs against a tmp_path sandbox with cache_dir monkeypatched;
data/cache (~15 GB, multi-day reparse) is never touched.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import dslib.cache as cache_mod                        # noqa: E402
from dslib.cache import (                              # noqa: E402
    delete_disk_cache_tree,
    delete_module_disk_cache_tree,
    disk_cache,
    get_module_cache_key_prefix,
)


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    cdir = tmp_path / 'cache'
    cdir.mkdir()
    monkeypatch.setattr(cache_mod, 'cache_dir', str(cdir))
    # test_extract_text.py calls disk_cache_disable(True) at MODULE level, which runs at
    # pytest collection -- before any test -- and stays set for the whole session. The
    # roundtrip test asserts a disk-cache HIT, so pin the flag or it fails by test order.
    monkeypatch.setattr(cache_mod, '_disk_cache_disabled', False)
    return tmp_path, cdir


def test_deletes_real_subtree(sandbox):
    """Positive calibration: a deleter never seen to delete is not a deleter."""
    tmp_path, cdir = sandbox
    sub = cdir / 'some' / 'tree'
    sub.mkdir(parents=True)
    entry = sub / 'entry.pickle'
    entry.write_bytes(b'x')

    assert delete_disk_cache_tree('some') is True

    assert not entry.exists()
    assert not (cdir / 'some').exists()
    assert cdir.exists()                    # only the subtree went, not the cache


def test_nonexistent_prefix_returns_false(sandbox):
    assert delete_disk_cache_tree('nothing/here') is False


def test_refuses_dotdot_escape_and_target_survives(sandbox):
    tmp_path, cdir = sandbox
    victim = tmp_path / 'victim'
    victim.mkdir()
    keep = victim / 'keep.txt'
    keep.write_text('keep')

    with pytest.raises(ValueError):
        delete_disk_cache_tree('../victim')
    with pytest.raises(ValueError):
        delete_disk_cache_tree('../../../../etc')

    assert keep.exists() and keep.read_text() == 'keep'


def test_absolute_prefix_is_rerooted_inside_cache(sandbox):
    """An absolute prefix must never reach the real filesystem root.

    It cannot be refused outright -- module prefixes ARE absolute
    (mod.__file__), that is the writer's own layout. Instead the writer's
    string-concat join re-roots it under cache_dir, exactly where the keys
    actually live; /etc itself is untouchable. Assert on the target's
    survival, and that nothing was claimed deleted.
    """
    tmp_path, cdir = sandbox
    assert delete_disk_cache_tree('/etc') is False      # cache/etc doesn't exist
    assert os.path.isdir('/etc')

    # and when cache/<abs> does exist, that tree (not the real one) is deleted
    inside = cdir / 'etc' / 'sub'
    inside.mkdir(parents=True)
    (inside / 'f').write_bytes(b'x')
    assert delete_disk_cache_tree('/etc') is True
    assert not (cdir / 'etc').exists()
    assert os.path.isdir('/etc')


def test_refuses_symlink_escaping_cache(sandbox):
    tmp_path, cdir = sandbox
    outside = tmp_path / 'outside'
    outside.mkdir()
    keep = outside / 'keep.txt'
    keep.write_text('keep')
    (cdir / 'linktree').symlink_to(outside)

    with pytest.raises(ValueError):
        delete_disk_cache_tree('linktree')

    assert keep.exists() and keep.read_text() == 'keep'


def test_refuses_whole_cache_and_junk_prefixes(sandbox):
    tmp_path, cdir = sandbox
    (cdir / 'canary').mkdir()
    for prefix in ('./', 'x/..', '', 'a', None):
        with pytest.raises(ValueError):
            delete_disk_cache_tree(prefix)
    assert (cdir / 'canary').exists()


def test_file_prefix_raises_not_silently_skips(sandbox):
    tmp_path, cdir = sandbox
    (cdir / 'not-a-dir').write_bytes(b'x')
    with pytest.raises(NotADirectoryError):
        delete_disk_cache_tree('not-a-dir')
    assert (cdir / 'not-a-dir').exists()


def test_module_tree_roundtrip_via_real_writer(sandbox):
    """delete_module_disk_cache_tree must delete the layout the writer produces.

    The fixture is written by a real @disk_cache call into the sandbox, so this
    test breaks if prefix derivation and key layout ever drift apart again.
    """
    tmp_path, cdir = sandbox
    calls = []

    @disk_cache(ttl='1d')
    def _fixture_fn(x):
        calls.append(x)
        return x * 2

    assert _fixture_fn(3) == 6
    mod = sys.modules[__name__]

    # the writer really wrote under the prefix the deleter will use
    prefix = get_module_cache_key_prefix(mod)
    tree = os.path.realpath(str(cdir) + '/' + prefix)
    assert os.path.isdir(tree), 'writer did not write where the deleter looks'
    assert any(files for _, _, files in os.walk(tree)), 'no cache entry on disk'

    assert _fixture_fn(3) == 6
    assert calls == [3], 'second call should have been a disk-cache hit'

    assert delete_module_disk_cache_tree(mod) is True
    assert not os.path.exists(tree)

    calls.clear()
    assert _fixture_fn(3) == 6
    assert calls == [3], 'cache tree was deleted, so this must recompute'


def _load_report_tool():
    import importlib.util
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    spec = importlib.util.spec_from_file_location(
        'disk_cache_report', os.path.join(repo, 'apps', 'disk_cache_report.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_report_tool_delete_wiring(sandbox, capsys):
    """apps/disk_cache_report.py --delete routes through the library deleter.

    Same calibration bar as the library: the apply is seen to delete, the dry
    run is seen NOT to, and an escaping prefix is refused with the target
    surviving (as SystemExit -- the CLI's refusal style)."""
    tmp_path, cdir = sandbox
    tool = _load_report_tool()

    sub = cdir / 'tree'
    entry = sub / 'a' / 'entry.pickle'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'x' * 10)

    tool.delete('tree', apply_=False)
    assert entry.exists(), 'dry run must not delete'
    assert 'DRY RUN' in capsys.readouterr().out

    tool.delete('tree', apply_=True)
    assert not sub.exists()
    assert 'deleted' in capsys.readouterr().out

    victim = tmp_path / 'victim'
    victim.mkdir()
    (victim / 'keep.txt').write_text('keep')
    with pytest.raises(SystemExit):
        tool.delete('../victim', apply_=True)
    assert (victim / 'keep.txt').exists()

    with pytest.raises(SystemExit):
        tool.delete('gone', apply_=True)


def test_module_prefix_matches_writer_key():
    """The prefix is the exact head of every key disk_cache_key builds."""
    mod = sys.modules[__name__]
    key = cache_mod.disk_cache_key(mod, test_module_prefix_matches_writer_key,
                                   set(), args=(), kwargs={})
    assert key.startswith(get_module_cache_key_prefix(mod) + '/')
