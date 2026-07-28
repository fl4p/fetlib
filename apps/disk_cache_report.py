"""What is in data/cache/, and how to reclaim it on purpose.

    python3 apps/disk_cache_report.py                  # what is using the space
    python3 apps/disk_cache_report.py --tree dslib.pdf # drill into one subtree
    python3 apps/disk_cache_report.py --delete dslib.pdf.tabular   # dry run
    python3 apps/disk_cache_report.py --delete dslib.pdf.tabular --apply

WHY THIS IS NOT AN AGE-BASED SWEEPER, which is what everyone reaches for first.

`disk_cache` gives every entry its own expiry -- it stores `(value, now() + ttl, meta)` and
refuses to serve anything past `exp`. Nothing deletes files, so the tree grows forever and a
stale entry is merely ignored, never reclaimed. That makes an "evict everything older than N
days" pass look like the obvious fix. It is not: `read_parts_datasheets` is decorated
`@disk_cache(ttl='999d', ...)`, so any N smaller than ~3 years deletes entries the cache
itself considers perfectly valid, and the bill is a multi-day Tabula/OCR re-parse of ~6000
datasheets. dslib/cache.py used to carry exactly that sweeper (7 days, never reachable, and
non-recursive so it had never actually deleted a nested entry); it was removed rather than
repaired.

So this tool does not decide anything. It measures, and it deletes only the subtree you
name. Deciding that a whole function's cached output is worth re-computing is a judgement
about that function's cost, which belongs to a person. The one exception it will do in bulk
is `--orphans`, and only because "the source file this key was derived from no longer
exists" is a fact rather than a judgement -- with the caveat, enforced by a default-off
`--include-foreign`, that a path outside this repo may merely be an unmounted checkout.

Every delete goes through `_rmtree_within_cache`, which refuses anything resolving outside
data/cache. It does NOT use `dslib.cache.delete_disk_cache_tree` -- originally because that
function's rmtree was commented out since 886fb686 (it logged "deleting" and removed
nothing, which made an earlier version of this tool report bytes reclaimed that were still
on disk). The library function has since been fixed; this tool keeps its own guarded delete
for its CLI semantics (see the comment in delete()).

Cost note: it stats files, it never unpickles them. `exp` lives inside the pickle, so
reporting true expiry would mean reading all ~17 GB back through pickle -- hours -- to learn
something the reader already enforces for free on every hit.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.cache import cache_dir  # noqa: E402


def _rmtree_within_cache(path, why):
    """rmtree, but only ever inside data/cache.

    Every destructive path in this file goes through here. `path` is reconstructed from
    strings found under the cache, so a '..' component or a symlinked subtree could
    otherwise point anywhere; refusing (rather than skipping) makes a parsing bug loud
    instead of letting it delete the targets that happened to look fine.
    """
    import shutil
    root = os.path.realpath(cache_dir)
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        raise SystemExit('refusing: %s resolves outside %s (%s)' % (real, root, why))
    if not os.path.isdir(real):
        return False
    shutil.rmtree(real)
    return True


def walk(root):
    """(relative-path, bytes, mtime) for every file under root."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue                      # vanished mid-walk; not worth failing over
            yield os.path.relpath(p, root), st.st_size, st.st_mtime


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024 or unit == 'TB':
            return '%.1f %s' % (n, unit)
        n /= 1024.0


def report(depth, prefix=None, limit=40):
    import time
    if not os.path.isdir(cache_dir):
        raise SystemExit('no cache at %s' % cache_dir)

    groups = defaultdict(lambda: [0, 0, 0.0, float('inf')])   # files, bytes, newest, oldest
    total_files = total_bytes = 0
    for rel, size, mtime in walk(cache_dir):
        if prefix and not rel.startswith(prefix):
            continue
        key = '/'.join(rel.split(os.sep)[:depth]) or '.'
        g = groups[key]
        g[0] += 1
        g[1] += size
        g[2] = max(g[2], mtime)
        g[3] = min(g[3], mtime)
        total_files += 1
        total_bytes += size

    if not total_files:
        print('nothing under %s%s' % (cache_dir, '/' + prefix if prefix else ''))
        return

    now = time.time()
    rows = sorted(groups.items(), key=lambda kv: -kv[1][1])

    # Cache keys are built from the decorated function's FILE PATH, so every row shares a
    # long absolute prefix. Strip whatever is common and print it once -- otherwise the
    # column is all prefix and the part that identifies the function is what gets truncated.
    shown = [k for k, _ in rows[:limit]]
    common = os.path.commonprefix(shown).rsplit('/', 1)[0] if len(shown) > 1 else ''
    cut = len(common) + 1 if common else 0

    print('%s%s' % (cache_dir, '/' + prefix if prefix else ''))
    if common:
        print('(all rows under %s/)' % common)
    w = 52
    print('%-*s %8s %10s %8s %8s' % (w, 'subtree', 'files', 'size', 'newest', 'oldest'))
    for key, (n, b, newest, oldest) in rows[:limit]:
        label = key[cut:] or '.'
        print('%-*s %8d %10s %7.0fd %7.0fd'
              % (w, label[:w], n, human(b), (now - newest) / 86400, (now - oldest) / 86400))
    if len(rows) > limit:
        rest = sum(g[1] for _, g in rows[limit:])
        print('%-*s %8d %10s' % (w, '... %d more' % (len(rows) - limit),
                                 sum(g[0] for _, g in rows[limit:]), human(rest)))
    print('%-*s %8d %10s' % (w, 'TOTAL', total_files, human(total_bytes)))
    print('\nreclaim a subtree with:  --delete <subtree> [--apply]')


def _source_of(rel):
    """The source file a cache key was derived from, or None.

    Keys are built from the decorated function's path, so a relative key looks like
    `Users/.../dslib/pdf/parse.py/<codehash>/<func>/...`. Everything up to and including
    the first `.py` component names the file it came from.
    """
    parts = rel.split(os.sep)
    for i, p in enumerate(parts):
        if p.endswith('.py'):
            return '/' + '/'.join(parts[:i + 1])
    return None


def orphans(apply_, include_foreign=False):
    """Subtrees whose source file no longer exists.

    The safest reclaim there is, and the only one this tool will do in bulk: the cache key
    embeds the source path, so if that file is gone -- renamed, moved into a package,
    deleted -- nothing can ever compute this key again. These entries are not stale, they
    are unreachable. That is a fact about the filesystem, not a judgement about whether a
    result is still worth keeping, which is why it is safe to automate and an age-based
    sweep is not.
    """
    by_src = defaultdict(lambda: [0, 0])
    for rel, size, _mtime in walk(cache_dir):
        src = _source_of(rel)
        if src is None:
            continue
        g = by_src[src]
        g[0] += 1
        g[1] += size

    dead = {s: g for s, g in by_src.items() if not os.path.exists(s)}
    if not dead:
        print('no orphaned subtrees: every cached key maps to a source file that exists')
        return

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    foreign = {s for s in dead if not s.startswith(repo + os.sep)}

    total = sum(g[1] for g in dead.values())
    print('%-62s %8s %10s' % ('orphaned source (file no longer exists)', 'files', 'size'))
    for src, (n, b) in sorted(dead.items(), key=lambda kv: -kv[1][1]):
        print('%-62s %8d %10s%s' % (src[-62:], n, human(b),
                                    '  <-- OTHER CHECKOUT' if src in foreign else ''))
    print('%-62s %8d %10s' % ('TOTAL RECLAIMABLE', sum(g[0] for g in dead.values()),
                              human(total)))

    if foreign:
        # os.path.exists proves "not here, right now" -- not "gone forever". A path outside
        # this repo root is a different checkout or an unmounted share (a Parallels
        # /media/psf/... mount, a second worktree), and it can come back. Deleting its cache
        # then costs a full reparse in THAT tree. Called out rather than silently swept up,
        # because the rest of this file argues its way out of exactly that kind of
        # not-currently-visible-therefore-dead reasoning.
        print('\nWARNING: %d of these are outside %s.' % (len(foreign), repo))
        print('They may belong to a worktree or shared folder that is simply not mounted')
        print('right now; "absent" there is not proof of "gone". Reclaiming them costs a')
        print('full reparse if that checkout returns. Pass --include-foreign to include.')

    if not apply_:
        print('\nDRY RUN -- nothing deleted. Re-run with --orphans --apply.')
        return

    freed = 0
    for src, (_n, b) in dead.items():
        if src in foreign and not include_foreign:
            print('  skipped %-58s %s (other checkout)' % (src[-58:], human(b)))
            continue
        if os.path.exists(src):
            raise SystemExit('refusing: %s exists after all -- re-run the dry run' % src)
        path = os.path.join(cache_dir, os.path.relpath(src, '/'))
        if _rmtree_within_cache(path, 'orphan %r' % src):
            freed += b
            print('  removed %-58s %s' % (src[-58:], human(b)))
    print('reclaimed %s' % human(freed))


def delete(prefix, apply_):
    path = os.path.join(cache_dir, prefix)
    if not os.path.isdir(path):
        raise SystemExit('not a cache subtree: %s' % path)

    n = b = 0
    for _rel, size, _mtime in walk(path):
        n += 1
        b += size
    print('%s\n  %d files, %s' % (path, n, human(b)))

    if not apply_:
        print('\nDRY RUN -- nothing deleted. Re-run with --apply.')
        print('Re-computing this costs whatever the decorated function costs; for the '
              'datasheet parse that is minutes per part.')
        return

    # Deliberately NOT dslib.cache.delete_disk_cache_tree. Historically its shutil.rmtree
    # was commented out (since 886fb686, 2025-09-16), so routing this through it made
    # --delete --apply print a reclaim total for bytes that were still on disk -- a
    # destructive command reporting success it had not earned. That function has since
    # been fixed (real rmtree + containment, 2026-07-28), but this tool keeps its own
    # _rmtree_within_cache: it already carries the dry-run/size accounting around the
    # delete, and its SystemExit refusals fit a CLI better than ValueError.
    if not _rmtree_within_cache(path, 'delete %r' % prefix):
        raise SystemExit('nothing deleted: %s is not a directory' % path)
    print('deleted %s (%s reclaimed)' % (path, human(b)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tree', metavar='PREFIX', help='only report under this subtree')
    ap.add_argument('--depth', type=int, default=2, help='grouping depth (default 2)')
    ap.add_argument('--limit', type=int, default=40, help='rows to print')
    ap.add_argument('--delete', metavar='PREFIX', help='delete a subtree (dry run by default)')
    ap.add_argument('--orphans', action='store_true',
                    help='find subtrees whose source file no longer exists (unreachable)')
    ap.add_argument('--include-foreign', action='store_true',
                    help='with --orphans, also reclaim caches belonging to OTHER checkouts '
                         '/ unmounted shares (absent there is not proof of gone)')
    ap.add_argument('--apply', action='store_true',
                    help='with --delete/--orphans, actually delete')
    args = ap.parse_args()

    if args.orphans:
        return orphans(args.apply, args.include_foreign)
    if args.delete:
        return delete(args.delete, args.apply)
    report(args.depth, args.tree, args.limit)


if __name__ == '__main__':
    main()
