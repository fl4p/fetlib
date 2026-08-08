"""Build a C(V) digitizer human-review packet for the top-N still-scalar parts of a run.

Motivation: `Coss_provenance` starting with `scalar:` means that row's P_coss is the
UNVERIFIED single-anchor 1/sqrt(V) guess, not a digitized datasheet curve. Which parts
those are changes with every design (fugu2-gan's LS top-10 is 9/10 EPC; the Si LS1p
project's is Infineon/NCE), so the review corpus has to be derived from THIS run's
ranking rather than hand-listed. `main.py --coss-review N` does exactly that.

The heavy lifting belongs to two SEPARATE repos with their own venvs, so every stage is
a subprocess -- there is no importable path from Python 3.9/3.10 fetlib into the
digitizer's 3.14 environment:

  1. `dsdig find`                       -> charts.json (panel detection, ~25 s/PDF)
  2. `dsdig digitize-capacitance`       -> overlays + capacitance_digitization.json
  3. backlog `import_capacitance_batch` -> review-backlog/ + MANIFEST.<prefix>.jsonl
     (this is where the fail-closed eligibility gate lives: axis trust, trace
     validation, Qoss anchors -- an ineligible row becomes a `gap`, never a value)
  4. rank injection (here)              -> cards sort by THIS run's rank, not arbitrarily
  5. backlog `build_html_review_packets` -> the self-contained review HTML

Locations default to the checkouts on this machine and are overridable with
FETLIB_DSDIG_HOME / FETLIB_DSDIG_BACKLOG_HOME. A missing tool RAISES: the packet is an
explicitly requested artifact, and a run that quietly produced no review would read as
"nothing to review", which is the opposite of the truth.
"""

import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

Part = Tuple[str, str]

DSDIG_HOME = os.environ.get('FETLIB_DSDIG_HOME',
                            '/Users/fab/dev/pv/ee/datasheet-chart-digitizer')
BACKLOG_HOME = os.environ.get('FETLIB_DSDIG_BACKLOG_HOME',
                              '/Users/fab/dev/pv/ee/dsdig-verify-backlog')

SCALAR_PREFIX = 'scalar:'
MAX_PACKET_SIZE = 100


def _tool_paths():
    """(python, backlog_tools) or a RuntimeError naming exactly what is missing."""
    py = os.path.join(DSDIG_HOME, 'venv', 'bin', 'python')
    tools = os.path.join(BACKLOG_HOME, 'tools')
    missing = [p for p in (py, os.path.join(tools, 'import_capacitance_batch.py'),
                           os.path.join(tools, 'build_html_review_packets.py'))
               if not os.path.exists(p)]
    if missing:
        raise RuntimeError(
            'coss review needs the datasheet-chart-digitizer and dsdig-verify-backlog '
            'checkouts; missing: %s. Set FETLIB_DSDIG_HOME / FETLIB_DSDIG_BACKLOG_HOME '
            'if they live elsewhere.' % ', '.join(missing))
    return py, tools


def dsdig_source_head() -> str:
    """The digitizer commit the packet was produced by, '-dirty' when the worktree
    carries uncommitted edits. The manifest records this and reviewers compare packets
    across it, so a dirty tree must SAY dirty -- a bare sha would claim the packet is
    reproducible from a commit that never produced it."""
    def git(*a):
        return subprocess.run(('git', '-C', DSDIG_HOME) + a, capture_output=True,
                              text=True, check=True).stdout.strip()
    try:
        head = git('rev-parse', 'HEAD')
        dirty = bool(git('status', '--porcelain'))
    except (subprocess.CalledProcessError, OSError) as e:
        return 'unknown (%s)' % e
    return head + ('-dirty' if dirty else '')


def document_fingerprint(mfr: str, mpn: str) -> str:
    """A key identifying the DATASHEET a part is reviewed from, so one document is not
    reviewed many times over.

    Vendors republish one document per cross-reference MPN. HXY (Huaxuanyang) ships an
    identical datasheet as `FDP100N10-HXY`, `STP80N10F7-HXY`, `BUK9510-100B-HXY`, ...
    -- 17 of the fugu2 HS top 30, all one device with one C(V) chart. Infineon does a
    milder version of it (`IRFB4110` / `PBF` / `G` / `GPBF` / `PBFXKMA1`). Reviewing
    those separately spends the human's attention on the same picture repeatedly.

    The key is the datasheet's TEXT with the part's own MPN removed, so two documents
    that differ only in the printed part number collapse. Comparing bytes would not:
    the MPN is in the text layer, so the files differ. Comparing specs would over-merge
    -- two genuinely different Infineon dies both read Coss=670 pF @ 50 V.

    **Fails open into "distinct", never into "duplicate".** Any unreadable or missing
    PDF returns a key unique to that part, so it is reviewed on its own. Merging on a
    failed read would silently drop a part from the corpus, and a part missing from a
    review looks exactly like a part reviewed and found clean.
    """
    path = _ds_path(mfr, mpn)
    if not os.path.exists(path):
        return 'nopdf:%s/%s' % (mfr, mpn)
    try:
        proc = subprocess.run(['pdftotext', '-f', '1', '-l', '3', path, '-'],
                              capture_output=True, text=True, timeout=60)
        text = proc.stdout if proc.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        text = ''
    if not text.strip():
        return 'unreadable:%s/%s' % (mfr, mpn)
    # Strip the MPN wherever it appears (and the bare base before a vendor suffix, which
    # is what HXY actually prints), then collapse whitespace: two republished copies of
    # one document differ in nothing else.
    stripped = text.upper()
    for token in {mpn.upper(), mpn.upper().rsplit('-', 1)[0]}:
        if len(token) >= 4:
            stripped = stripped.replace(token, '')
    return 'doc:%s' % hashlib.sha256(
        ' '.join(stripped.split()).encode('utf-8', 'replace')).hexdigest()


def select_scalar_coss_parts(rankings: Sequence[Sequence[Part]],
                             provenance: Dict[Part, str],
                             top_n: int,
                             dedupe_documents: bool = False,
                             ) -> Tuple[List[Part], Dict[str, int]]:
    """The best `top_n` DISTINCT parts still on a `scalar:` Coss, drawn round-robin
    from the given rankings (HS and LS rank different loss mechanisms; taking the best
    of one alone would starve the other, exactly as the DigiKey top-N fetch does).

    Filtering happens BEFORE the cap, so `top_n` counts reviewable parts rather than
    being diluted by already-curved ones. A part whose provenance is unknown is counted
    and skipped, never assumed scalar. top_n <= 0 means uncapped.
    """
    stats = dict(scalar=0, curve=0, unknown=0)
    filtered = []
    for ranking in rankings:
        keep = []
        for part in ranking:
            prov = provenance.get(part)
            if prov is None:
                stats['unknown'] += 1
            elif prov.startswith(SCALAR_PREFIX):
                stats['scalar'] += 1
                keep.append(part)
            else:
                stats['curve'] += 1
        filtered.append(keep)

    if top_n <= 0:
        top_n = sum(len(r) for r in filtered)
    # Document keys are computed LAZILY, as the round-robin walks down the ranking: the
    # scalar list runs to hundreds of parts and shelling out pdftotext for all of them
    # to fill a 30-part corpus would be most of the cost of the packet.
    stats['duplicate_document'] = 0
    docs: Dict[Part, str] = {}
    out, seen, seen_docs, i = [], set(), set(), 0
    while len(out) < top_n and any(i < len(r) for r in filtered):
        for r in filtered:
            if i < len(r) and len(out) < top_n:
                part = r[i]
                if part in seen:
                    continue
                seen.add(part)
                if dedupe_documents:
                    key = docs.get(part) or document_fingerprint(*part)
                    docs[part] = key
                    if key in seen_docs:
                        stats['duplicate_document'] += 1
                        continue
                    seen_docs.add(key)
                out.append(part)
        i += 1
    return out, stats


def _ds_path(mfr: str, mpn: str) -> str:
    # same mapping as DiscoveredPart.get_ds_path (dslib/discovery/__init__.py), which
    # cannot be called with (mfr, mpn) alone -- ds_url/package are required there.
    from dslib.discovery import DiscoveredPart
    return os.path.abspath(
        DiscoveredPart(mfr=mfr, mpn=mpn, ds_url=None, package=None).get_ds_path())


def _run(cmd, log_path, what):
    with open(log_path, 'w') as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError('%s failed (exit %d), see %s\n%s'
                           % (what, proc.returncode, log_path, _tail(log_path)))


def _tail(log_path, n=15):
    try:
        with open(log_path) as fh:
            return ''.join(fh.readlines()[-n:])
    except OSError:
        return '(no log)'


def _default_jobs() -> int:
    env = os.environ.get('FETLIB_COSS_REVIEW_JOBS')
    if env:
        return max(1, int(env))
    try:
        return min(8, max(1, (os.cpu_count() or 2) - 2))
    except Exception:
        return 1


def _clear_scan_outputs(run_dir: str) -> None:
    """Delete the previous scan's products before scanning into the same run dir.

    The run dir is keyed by (N, date), so the SECOND run on one day with a changed
    corpus -- the normal case once the ranking moves, and the only case that reaches a
    re-scan at all -- arrives with the previous run's merged `crops/` still in place.
    The merge then finds `crops/<PART>` already there and reports a part-name collision
    that does not exist (the real two-datasheets-one-basename case is caught up front,
    on the PDF list, before any scanning).

    Stale crops must go rather than be merged around: `charts.json` is rewritten
    wholesale from the shards, so a crop left over from a part that has since dropped
    out of the corpus is unreferenced, and the only thing it can ever do is be mistaken
    for current evidence. Leftover `_shard*` dirs from an aborted run go the same way.
    """
    import shutil
    for entry in ('crops', 'charts.json', 'charts.csv', 'scan_errors.json'):
        path = os.path.join(run_dir, entry)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    for shard in glob.glob(os.path.join(run_dir, '_shard*')):
        shutil.rmtree(shard, ignore_errors=True)


def _find_charts(cli, pdfs: List[str], run_dir: str, jobs: int) -> None:
    """`dsdig find`, sharded across `jobs` processes.

    The digitizer scans strictly sequentially (find_charts.main is a plain for-loop over
    the PDFs, ~25 s each), and per-PDF work is independent, so the parallelism lives here
    rather than upstream. Each shard gets its own --out; the results are merged back into
    the layout the sequential path produces, so everything downstream is unchanged.

    A shard that fails ABORTS the run. Merging the survivors would hand the packet a
    silently short corpus -- parts missing from a review look identical to parts that
    were reviewed and found clean.
    """
    _clear_scan_outputs(run_dir)
    jobs = max(1, min(jobs, len(pdfs)))
    if jobs == 1:
        _run(cli + ['find'] + pdfs + ['--out', run_dir],
             os.path.join(run_dir, 'find.log'), 'dsdig find')
        return

    # round-robin, not contiguous blocks: per-PDF cost varies several-fold with page
    # count, and a block split parks all the slow ones in one shard.
    shards = [pdfs[i::jobs] for i in range(jobs)]
    procs = []
    for i, chunk in enumerate(shards):
        out = os.path.join(run_dir, '_shard%d' % i)
        os.makedirs(out, exist_ok=True)
        log = os.path.join(run_dir, 'find-shard%d.log' % i)
        fh = open(log, 'w')
        procs.append((i, log, fh, subprocess.Popen(
            cli + ['find'] + chunk + ['--out', out], stdout=fh,
            stderr=subprocess.STDOUT)))
    failed = []
    for i, log, fh, proc in procs:
        rc = proc.wait()
        fh.close()
        if rc != 0:
            failed.append('shard %d (exit %d, %s):\n%s' % (i, rc, log, _tail(log, 8)))
    if failed:
        raise RuntimeError('dsdig find failed in %d/%d shard(s) -- refusing to build a '
                           'packet from a partial scan:\n%s'
                           % (len(failed), jobs, '\n'.join(failed)))
    _merge_shards(run_dir, len(shards))


def _merge_shards(run_dir: str, n: int) -> None:
    """Fold the shard dirs into the single-run layout `write_outputs` would have made.

    `crop_png` is relative to the out dir and namespaced per part, so merging is moving
    `crops/<PART>/` and concatenating the JSON -- no path rewriting. A part directory
    appearing in two shards would mean two PDFs mapping to one part name; that is a
    collision whose silent resolution is one card showing ANOTHER part's chart, so it
    raises instead.
    """
    import shutil
    panels, errors, csv_rows, header = [], [], [], None
    crops = os.path.join(run_dir, 'crops')
    os.makedirs(crops, exist_ok=True)
    # which shard contributed each part, so a genuine collision can name both sides.
    # Testing os.path.exists(dest) instead conflated "two shards produced this part"
    # with "a previous run's crops were still lying here", and reported the former.
    from_shard: Dict[str, int] = {}
    for i in range(n):
        shard = os.path.join(run_dir, '_shard%d' % i)
        with open(os.path.join(shard, 'charts.json')) as fh:
            panels.extend(json.load(fh))
        errs = os.path.join(shard, 'scan_errors.json')
        if os.path.exists(errs):
            with open(errs) as fh:
                errors.extend(json.load(fh))
        csv_path = os.path.join(shard, 'charts.csv')
        if os.path.exists(csv_path):
            with open(csv_path) as fh:
                lines = fh.read().splitlines()
            if lines:
                header = header or lines[0]
                csv_rows.extend(lines[1:])
        shard_crops = os.path.join(shard, 'crops')
        for part in (os.listdir(shard_crops) if os.path.isdir(shard_crops) else []):
            if part in from_shard:
                raise RuntimeError(
                    'coss review: part %r was produced by BOTH shard %d and shard %d -- '
                    'two datasheets in this corpus map to the same part name, so their '
                    'crops and review ids would be mixed up' % (part, from_shard[part], i))
            from_shard[part] = i
            shutil.move(os.path.join(shard_crops, part), os.path.join(crops, part))
        shutil.rmtree(shard, ignore_errors=True)

    # same ordering as find_charts.write_outputs, so a sharded run and a sequential run
    # produce byte-identical charts.json for the same corpus
    panels.sort(key=lambda p: (p['part'], p['page'], p['diagram']))
    with open(os.path.join(run_dir, 'charts.json'), 'w') as fh:
        fh.write(json.dumps(panels, indent=2) + '\n')
    with open(os.path.join(run_dir, 'scan_errors.json'), 'w') as fh:
        fh.write(json.dumps(errors, indent=2) + '\n')
    if header is not None:
        with open(os.path.join(run_dir, 'charts.csv'), 'w') as fh:
            fh.write('\n'.join([header] + csv_rows) + '\n')


def _read_manifest_rows(manifest: str) -> List[dict]:
    return [json.loads(line) for line in open(manifest) if line.strip()]


def _inject_rank(manifest: str, ranks: Dict[str, Tuple[int, str]]) -> int:
    """build_html_review_packets sorts cards on a `rank` field the importer does not
    write; without this every card sorts at +inf, i.e. in arbitrary order, and the
    reviewer's attention goes to whatever happens to be first instead of to the part
    the design actually cares about."""
    rows, hit = [], 0
    for row in _read_manifest_rows(manifest):
        info = ranks.get(str(row.get('part')))
        if info:
            row['rank'], row['ranked_coss'] = info
            hit += 1
        rows.append(row)
    rows.sort(key=lambda r: (r.get('rank', float('inf')), r['review_id']))
    with open(manifest, 'w') as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(',', ':')) + '\n')
    return hit


def _write_current_review_ids(manifest: str, ids_path: str) -> int:
    rows = _read_manifest_rows(manifest)
    with open(ids_path, 'w') as fh:
        for row in rows:
            fh.write(str(row['review_id']) + '\n')
    return len(rows)


def _packet_size(card_count: int) -> int:
    return max(1, min(MAX_PACKET_SIZE, card_count or MAX_PACKET_SIZE))


def build_coss_review(hs: Sequence[Part], ls: Sequence[Part],
                      provenance: Dict[Part, str], top_n: int, name: str,
                      out_root: str = 'out', jobs: Optional[int] = None,
                      dedupe_documents: bool = True) -> Optional[dict]:
    """Select, digitize and package. Returns a summary dict, or None when no part of
    this run is on a scalar Coss (a real answer -- printed, not silently empty)."""
    py, tools = _tool_paths()
    parts, stats = select_scalar_coss_parts([hs, ls], provenance, top_n,
                                            dedupe_documents=dedupe_documents)
    print('coss-review: ranked parts by Coss evidence: %d scalar, %d curve, '
          '%d unknown-provenance (skipped)'
          % (stats['scalar'], stats['curve'], stats['unknown']))
    if stats.get('duplicate_document'):
        print('coss-review: skipped %d part(s) republishing a datasheet already in the '
              'corpus (vendor cross-reference MPNs); top_n counts DISTINCT documents'
              % stats['duplicate_document'])
    if not parts:
        print('coss-review: no part in this ranking is on a scalar Coss -- nothing to '
              'review. (Every ranked part already has a digitized curve.)')
        return None

    pdfs, no_pdf = [], []
    for mfr, mpn in parts:
        path = _ds_path(mfr, mpn)
        (pdfs if os.path.exists(path) else no_pdf).append(path if os.path.exists(path)
                                                          else '%s/%s' % (mfr, mpn))
    if no_pdf:
        print('coss-review: %d selected part(s) have NO datasheet PDF on disk, excluded '
              'from the packet: %s' % (len(no_pdf), ', '.join(no_pdf[:10])))
    if not pdfs:
        raise RuntimeError('coss review: none of the %d selected parts has a datasheet '
                           'PDF on disk' % len(parts))

    # dsdig keys crops, review ids and manifest rows by the PDF BASENAME, so two
    # manufacturers shipping the same MPN would silently share one crop directory and
    # one review id -- a card showing the other part's chart. Cheap to detect, and it
    # holds for the sequential path too.
    bases = [os.path.basename(p)[:-4] for p in pdfs]
    dupes = sorted({b for b in bases if bases.count(b) > 1})
    if dupes:
        raise RuntimeError('coss review: %d part name(s) map to more than one datasheet '
                           '(%s) -- dsdig keys crops and review ids by basename, so this '
                           'would silently mix them up' % (len(dupes), ', '.join(dupes)))

    # The run dir and packet prefix MUST carry the side. Keying them on (N, date) alone
    # was safe only while the corpus was always the HS+LS interleave; with --coss-review-
    # side, an HS top-30 and an LS top-30 on one day collide on both names, and the second
    # run silently clears the first one's crops and overwrites its packet HTML -- the
    # reviewer opens "the top-30 packet" and reads the other slot's parts.
    side_tag = ('' if (hs and ls) else ('-hs' if hs else '-ls'))
    prefix = '%s-coss-scalar-top%d%s' % (name, len(pdfs), side_tag)
    run_dir = os.path.join(out_root, name, 'coss-review-top%d%s-%s'
                           % (len(pdfs), side_tag,
                              datetime.date.today().isoformat()))
    os.makedirs(run_dir, exist_ok=True)
    charts = os.path.join(run_dir, 'charts.json')
    pdf_list = os.path.join(run_dir, 'pdfs.txt')

    # Reuse an existing scan ONLY when it covers exactly this PDF set. Keying the reuse
    # on the directory alone would silently serve yesterday's corpus after the ranking
    # moved -- same N, same date, different parts.
    same_corpus = (os.path.exists(charts) and os.path.exists(pdf_list)
                   and open(pdf_list).read().split() == pdfs)

    cli = [py, '-m', 'datasheet_chart_digitizer.cli']
    if same_corpus:
        print('coss-review: reusing charts.json (identical %d-PDF corpus)' % len(pdfs))
    else:
        n_jobs = max(1, min(jobs or _default_jobs(), len(pdfs)))
        print('coss-review: scanning %d datasheets for chart panels (~25 s each, %d '
              'parallel shard(s) -> ~%d min)...'
              % (len(pdfs), n_jobs, max(1, round(len(pdfs) * 25 / n_jobs / 60))))
        _find_charts(cli, pdfs, run_dir, n_jobs)
        # AFTER the scan, never before: pdfs.txt is the record of what charts.json
        # actually covers, and the reuse gate above trusts exactly that pairing. Writing
        # it up front meant an aborted scan left the NEW list beside the PREVIOUS run's
        # charts.json, so the next run read "same corpus" and reused a scan of different
        # parts -- the silent wrong-corpus serve this key exists to prevent.
        with open(pdf_list, 'w') as fh:
            fh.write('\n'.join(pdfs) + '\n')

    panels = [c for c in json.load(open(charts)) if c.get('kind') == 'capacitances']
    found = {str(c['part']) for c in panels}
    gap_parts = [os.path.basename(p)[:-4] for p in pdfs
                 if os.path.basename(p)[:-4] not in found]
    print('coss-review: %d capacitance panel(s) on %d/%d parts'
          % (len(panels), len(found), len(pdfs)))
    if gap_parts:
        # finder gaps are a RESULT (the part ships unreviewable), not an absence
        print('coss-review: NO capacitance panel found for %d part(s): %s'
              % (len(gap_parts), ', '.join(gap_parts)))
    if not panels:
        raise RuntimeError('coss review: no capacitance panel found in any of the %d '
                           'datasheets -- nothing to digitize' % len(pdfs))

    # fetlib owns the spec-table anchors the digitizer validates traces against; its own
    # .nop.csv scraper is a second, weaker parser over PDFs we already parse properly
    # (case-sensitive on the printed symbol, so it returned NOTHING for every EPC part
    # while we hold Coss=557 pF @ 50 V for the same device). --anchors replaces it.
    from dslib.coss_anchors import write_anchor_table
    anchors_path = os.path.join(run_dir, 'anchors.json')
    a_stats = write_anchor_table(parts, anchors_path)
    print('coss-review: anchors from fetlib: %d/%d parts have Coss (%d full Ciss/Coss/'
          'Crss, %d with Qoss); %d no DB record, %d no anchorable stat'
          % (a_stats['with_coss'], a_stats['parts'], a_stats['with_all_three'],
             a_stats['with_qoss'], a_stats['no_record'], a_stats['no_anchor']))

    print('coss-review: digitizing %d panel(s)...' % len(panels))
    _run(cli + ['digitize-capacitance', charts, '--anchors', anchors_path,
                '--debug-axis-overlays'],
         os.path.join(run_dir, 'digitize.log'), 'dsdig digitize-capacitance')

    backlog = BACKLOG_HOME
    manifest_tag = '%s-%s-%d' % (
        prefix, datetime.datetime.now().strftime('%Y%m%d%H%M%S'), os.getpid())
    manifest = os.path.join(backlog, 'MANIFEST.%s.jsonl' % manifest_tag)
    os.makedirs(backlog, exist_ok=True)
    head = dsdig_source_head()
    if head.endswith('-dirty'):
        print('coss-review: WARNING the digitizer worktree is DIRTY -- this packet is '
              'not reproducible from a commit; manifest source_head says so.')
    _run([py, os.path.join(tools, 'import_capacitance_batch.py'), charts, run_dir,
          '--root', backlog, '--manifest', manifest, '--source-head', head],
         os.path.join(run_dir, 'import.log'), 'import_capacitance_batch')

    ranks = {mpn: (i + 1, provenance.get((mfr, mpn), ''))
             for i, (mfr, mpn) in enumerate(parts)}
    _inject_rank(manifest, ranks)
    ids_path = os.path.join(run_dir, 'current-review-ids.txt')
    card_count = _write_current_review_ids(manifest, ids_path)

    html_dir = os.path.join(run_dir, 'review-html', prefix)
    # Build against the persistent backlog, not this run's private directory: that lets
    # build_html_review_packets merge previous MANIFEST rows and suppress cards already
    # marked human_verified. --ids keeps the packet scoped to THIS run's freshly selected
    # rows instead of every unverified capacitance card in the shared backlog.
    # --include-gaps is load-bearing: fail-closed rows ARE review work; without it the
    # packet would show only the extractions that already passed. Packet size follows the
    # current row count (bounded only by the backlog tool's 100-card max), so there is no
    # hardcoded 25-card cap.
    _run([py, os.path.join(tools, 'build_html_review_packets.py'),
          '--root', backlog, '--output-dir', html_dir, '--packet-prefix', prefix,
          '--ids', ids_path, '--include-gaps', '--packet-size', str(_packet_size(card_count))],
         os.path.join(run_dir, 'packets.log'), 'build_html_review_packets')

    index_path = os.path.join(html_dir, '%s-index.json' % prefix)
    emitted_ids = {
        item_id
        for packet in json.load(open(index_path))
        for item_id in packet['items']
    } if os.path.exists(index_path) else set()
    rows = [r for r in _read_manifest_rows(manifest) if r.get('review_id') in emitted_ids]
    ok = sum(1 for r in rows if r.get('extract_ok'))
    packets = sorted(f for f in os.listdir(html_dir) if f.endswith('.html'))
    print('coss-review: %d unverified card(s), %d extract_ok / %d gap, %d packet(s)'
          % (len(rows), ok, len(rows) - ok, len(packets)))
    for p in packets:
        print('coss-review: >>>', os.path.join(html_dir, p))
    return dict(parts=len(pdfs), cards=len(rows), extract_ok=ok,
                gaps=len(rows) - ok, finder_gap_parts=gap_parts,
                packets=[os.path.join(html_dir, p) for p in packets],
                source_head=head, run_dir=run_dir)


def open_packet(summary: Optional[dict]) -> None:
    """Open the first packet in the default browser (macOS `open`). Best-effort."""
    if not summary or not summary.get('packets'):
        return
    try:
        subprocess.run(['open', summary['packets'][0]], check=False)
    except OSError as e:
        print('coss-review: could not open the packet:', e, file=sys.stderr)
