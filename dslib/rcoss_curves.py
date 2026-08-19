"""Curated per-part Rcoss store: load, serve, and transactionally publish.

Data lives in `rcoss_curves.json` next to this module (override with the
RCOSS_STORE_PATH env var — tests and scratch promotions use that). JSON rather than
Python literals so the promoter's read-modify-write is a plain atomic file replace
with no code generation; the review commentary lives in the per-entry review
artifacts, whose sha256 each entry records.

Schema (top level):

    {"schema": "rcoss-store-v1",
     "entries": {"<mfr.lower()>:<MPN.upper()>": {"curve": {...}|null,
                                                 "anchor": {...}|null}}}

Curve sub-entry: {"kind": "derived", "points": [[V,R],...],
                  "vendor_share": [[V,f,Re],...], "provenance": {...},
                  "human_verified": bool, "review": {...}|null,
                  "entry_fingerprint": "..."}
              or {"kind": "tombstone", "why": "...", "model_sha256": "...",
                  "derive_version": N, "provenance": {...}}
Anchor sub-entry: {"kind": "anchor", "anchor": [V_ref, R],
                   "anchor_source": "bench-fit"|"single-bias-derived",
                   "vendor_share_row": [[f,Re],...]|null, "why_no_curve": "...",
                   "provenance": {...}, "human_verified": bool, "review": {...}|null,
                   "entry_fingerprint": "..."}

Serving contract (four distinct outcomes — plans/rcoss-curves-into-fetlib.md §2):
  * rcoss_for() returns a validated RcossBundle for a present part,
  * returns None ONLY on a definite key miss after a successful store load,
  * RAISES RcossStoreError for a missing/unreadable/malformed store or entry —
    a raise must abort the consumer, never be misread as "part absent".

Publishing (used by the dcdc-tools promoter and by tests):
  * publish() holds a cooperative lock, re-reads under it, optionally CAS-checks the
    store bytes against what the caller read earlier, validates the WHOLE store after
    the edit, writes a temp file and os.replace()s it (atomic).
  * A re-publish with an identical entry_fingerprint is a NO-OP that preserves
    human_verified/review; any material change resets both (re-review finding A6/F6:
    "always write False" would destroy a valid review of an unchanged law).
"""
import errno
import hashlib
import json
import os
import time

from .rcoss_model import (RcossAnchor, RcossBundle, RcossDerived, RcossStoreError,
                          RcossTombstone, entry_fingerprint)

SCHEMA = "rcoss-store-v1"
_HERE = os.path.dirname(os.path.abspath(__file__))


def store_path():
    return os.environ.get("RCOSS_STORE_PATH", os.path.join(_HERE, "rcoss_curves.json"))


def store_sha256(path=None):
    """sha256 of the store file bytes (None if absent) — the CAS token for publish()."""
    p = path or store_path()
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _key(mfr, mpn):
    return f"{mfr.strip().lower()}:{mpn.strip().upper()}"


def _load_raw(path, missing_ok=False):
    """Parse + top-level-validate the store file.

    An ABSENT file raises unless `missing_ok` (impl review I1: the shipped store is a
    versioned file — a missing one means a broken checkout or a wrong
    RCOSS_STORE_PATH, and reading it as empty would route every curated part to the
    live tier). Only publish() passes missing_ok=True, to create a fresh store.
    """
    if not os.path.exists(path):
        if missing_ok:
            return {"schema": SCHEMA, "entries": {}}
        raise RcossStoreError(
            f"rcoss store {path} does not exist — this is a STORE FAILURE, not an "
            f"empty store (a fresh store is created by publish, never implied by a "
            f"missing file). Check the fetlib checkout / RCOSS_STORE_PATH.")
    try:
        with open(path) as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise RcossStoreError(f"rcoss store {path}: unreadable/unparseable ({e}) — "
                              f"aborting, this is NOT 'part absent'") from e
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise RcossStoreError(
            f"rcoss store {path}: unsupported schema {raw.get('schema')!r} "
            f"(this code speaks {SCHEMA!r}); refusing to guess")
    if not isinstance(raw.get("entries"), dict):
        raise RcossStoreError(f"rcoss store {path}: 'entries' must be an object")
    return raw


def _check_fp_and_review(sub, key, slot):
    """Fingerprint + review-binding invariants shared by curve and anchor entries.

    human_verified=True is only meaningful when bound to THIS entry's fingerprint
    and a concrete artifact sha (impl review I2: a hand-edited `true` with
    review=null loaded fine and became golden-eligible)."""
    stored_fp = sub.get("entry_fingerprint")
    fp = entry_fingerprint(sub)
    if stored_fp != fp:
        raise RcossStoreError(
            f"rcoss store entry {key}/{slot}: entry_fingerprint mismatch "
            f"(stored {stored_fp!r}, computed {fp!r}) — the entry was edited "
            f"without re-fingerprinting; its review state is unbound")
    if sub.get("human_verified"):
        rev = sub.get("review")
        if not isinstance(rev, dict) or rev.get("entry_fingerprint") != fp \
                or not rev.get("artifact_sha256") or not rev.get("reviewer"):
            raise RcossStoreError(
                f"rcoss store entry {key}/{slot}: human_verified=True without a "
                f"review bound to this fingerprint (need reviewer + artifact_sha256 "
                f"+ entry_fingerprint == {fp[:12]}...) — a naked flag is not a review")
    return fp


def _prov_with_artifact(sub):
    """Serving provenance = the provenance block plus the entry-level review_artifact
    reference (I2: the loader used to drop it, so refusals printed an empty ref)."""
    prov = dict(sub.get("provenance") or {})
    if sub.get("review_artifact"):
        prov["review_artifact"] = sub["review_artifact"]
    return prov


def _build_curve(sub, key):
    kind = sub.get("kind")
    if kind == "derived":
        fp = _check_fp_and_review(sub, key, "curve")
        return RcossDerived(sub["points"], sub["vendor_share"], _prov_with_artifact(sub),
                            human_verified=sub.get("human_verified", False),
                            review=sub.get("review"), fingerprint=fp)
    if kind == "tombstone":
        # tombstones are fingerprinted too (impl review I4: an unfingerprinted
        # tombstone could be hand-edited into a different structural claim, or its
        # derive_version rewritten, with no detection — a stale "no evidence" claim
        # silently staying load-bearing)
        stored_fp = sub.get("entry_fingerprint")
        fp = entry_fingerprint(sub)
        if stored_fp != fp:
            raise RcossStoreError(
                f"rcoss store entry {key}/curve: tombstone fingerprint mismatch "
                f"(stored {stored_fp!r}, computed {fp!r}) — edited without "
                f"re-promotion")
        return RcossTombstone(sub.get("why", ""), sub.get("model_sha256"),
                              sub.get("derive_version"), sub.get("provenance"))
    raise RcossStoreError(f"rcoss store entry {key}/curve: unknown kind {kind!r}")


def _build_anchor(sub, key):
    if sub.get("kind") != "anchor":
        raise RcossStoreError(
            f"rcoss store entry {key}/anchor: unknown kind {sub.get('kind')!r}")
    if "points" in sub:
        raise RcossStoreError(
            f"rcoss store entry {key}/anchor: carries curve 'points' — an anchor is one "
            f"value; a multi-point law belongs in the curve slot")
    fp = _check_fp_and_review(sub, key, "anchor")
    v_ref, r_ohm = sub["anchor"]
    return RcossAnchor(v_ref, r_ohm, sub.get("anchor_source"),
                       _prov_with_artifact(sub),
                       vendor_share_row=sub.get("vendor_share_row"),
                       why_no_curve=sub.get("why_no_curve", ""),
                       human_verified=sub.get("human_verified", False),
                       review=sub.get("review"), fingerprint=fp)


def _validate_all(raw, path):
    """Build every entry — a store with ANY malformed entry refuses to load whole
    (guard checklist #1: a malformed guard input must never quietly narrow coverage)."""
    out = {}
    for key, slot in raw["entries"].items():
        if not isinstance(slot, dict) or set(slot) - {"curve", "anchor"}:
            raise RcossStoreError(f"rcoss store entry {key}: bad slot shape "
                                  f"{sorted(slot) if isinstance(slot, dict) else slot!r}")
        # ONLY None is absent. A falsey-but-present sub-entry ({}, "", 0) is malformed
        # and must refuse — treating it as absent routed derived mode to the live tier
        # (impl review I1, reproduced).
        curve = (_build_curve(slot["curve"], key)
                 if slot.get("curve") is not None else None)
        anchor = (_build_anchor(slot["anchor"], key)
                  if slot.get("anchor") is not None else None)
        if curve is None and anchor is None:
            raise RcossStoreError(f"rcoss store entry {key}: empty bundle — a part with "
                                  f"no evidence must be ABSENT, not present-and-empty")
        out[key] = RcossBundle(curve, anchor)
    return out


def load_store(path=None):
    """{key: RcossBundle} for the whole validated store."""
    p = path or store_path()
    return _validate_all(_load_raw(p), p)


def rcoss_for(mfr, mpn, path=None):
    """RcossBundle for one part, or None ONLY on a definite miss (store loaded fine)."""
    return load_store(path).get(_key(mfr, mpn))


class _Lock:
    """Cooperative exclusive lock via O_EXCL lockfile, stale-broken after 60 s."""

    def __init__(self, path, timeout=20.0):
        self.lockfile = path + ".lock"
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                # steal ONLY a lock whose recorded holder pid is dead (impl review
                # I5: age alone let the original holder later unlink a successor's
                # lock). Age is the fallback when the pid is unreadable.
                try:
                    with open(self.lockfile) as lf:
                        pid = int(lf.read().strip() or "0")
                except (OSError, ValueError):
                    pid = 0
                dead = False
                if pid > 0:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        dead = True
                    except PermissionError:
                        pass           # alive under another uid
                try:
                    stale = time.time() - os.path.getmtime(self.lockfile) > 60.0
                    if dead or (pid == 0 and stale):
                        os.unlink(self.lockfile)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise RcossStoreError(
                        f"rcoss store: could not acquire {self.lockfile} within "
                        f"{self.timeout}s — another promotion is running (or a stale "
                        f"lock < 60 s old)") from e
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            os.unlink(self.lockfile)


def publish(mfr, mpn, kind, sub_entry, path=None, expected_store_sha=None):
    """Insert/replace one sub-entry ('curve' or 'anchor') transactionally.

    `sub_entry` is the JSON-shaped dict WITHOUT entry_fingerprint/human_verified/review
    (the store owns those). Returns {"action": "published"|"noop", "entry_fingerprint",
    "path"}.
    """
    if kind not in ("curve", "anchor"):
        raise RcossStoreError(f"publish: kind must be 'curve' or 'anchor', got {kind!r}")
    p = path or store_path()
    key = _key(mfr, mpn)
    with _Lock(p):
        if expected_store_sha is not None and store_sha256(p) != expected_store_sha:
            raise RcossStoreError(
                f"publish: store {p} changed since it was read (CAS mismatch) — "
                f"re-read and retry; refusing a lost-update overwrite")
        raw = _load_raw(p, missing_ok=True)        # publish CREATES a fresh store
        sub = dict(sub_entry)
        sub.pop("entry_fingerprint", None)
        prev = (raw["entries"].get(key) or {}).get(kind)
        if sub.get("kind") == "tombstone":
            # tombstones carry no review state but ARE fingerprinted (I4)
            fp = entry_fingerprint(sub)
            new = dict(sub, entry_fingerprint=fp)
            if prev and prev.get("entry_fingerprint") == fp:
                return {"action": "noop", "entry_fingerprint": fp, "path": p}
        else:
            # fingerprint over the material entry with review state at its reset values
            new = dict(sub, human_verified=False, review=None)
            fp = entry_fingerprint(new)
            new["entry_fingerprint"] = fp
            if prev and prev.get("entry_fingerprint") == fp:
                # identical material content: preserve the existing review (A6/F6)
                return {"action": "noop", "entry_fingerprint": fp, "path": p}
        slot = dict(raw["entries"].get(key) or {"curve": None, "anchor": None})
        slot[kind] = new
        entries = dict(raw["entries"])
        entries[key] = slot
        candidate = {"schema": SCHEMA, "entries": entries}
        _validate_all(candidate, p)                # a bad write must die HERE, pre-replace
        tmp = p + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(candidate, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, p)
        return {"action": "published", "entry_fingerprint": fp, "path": p}


def set_human_verified(mfr, mpn, kind, reviewer, artifact_sha256, path=None):
    """The HUMAN review step: bind a review to the entry's current fingerprint.

    Never called by agents/promoters — repo rule: agent review does not set
    human_verified.
    """
    p = path or store_path()
    key = _key(mfr, mpn)
    with _Lock(p):
        raw = _load_raw(p)
        sub = (raw["entries"].get(key) or {}).get(kind)
        if not sub:
            raise RcossStoreError(f"set_human_verified: no {kind} entry for {key}")
        if sub.get("kind") == "tombstone":
            raise RcossStoreError("set_human_verified: tombstones carry no review state")
        # The review must name the artifact the entry actually records (impl review
        # I2: any supplied sha used to be accepted, unbinding the review from what
        # was reviewed).
        rec = (sub.get("review_artifact") or {}).get("sha256")
        if rec and artifact_sha256 != rec:
            raise RcossStoreError(
                f"set_human_verified: artifact sha {artifact_sha256[:12]}... does not "
                f"match the entry's recorded review artifact {rec[:12]}... — review "
                f"the artifact this entry points to, not another one")
        sub["human_verified"] = True
        sub["review"] = {"reviewer": reviewer,
                         "reviewed_at": time.strftime("%Y-%m-%d"),
                         "entry_fingerprint": sub["entry_fingerprint"],
                         "artifact_sha256": artifact_sha256}
        _validate_all(raw, p)
        tmp = p + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(raw, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, p)
