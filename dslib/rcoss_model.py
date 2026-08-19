"""Typed Rcoss (Coss-branch series damping) objects served from the curated store.

Three kinds, deliberately a TAGGED UNION and not one class with a status string
(dcdc-tools plans/rcoss-curves-into-fetlib.md, re-review finding A1: the loss tool's
`RcossCurve.enabled` is literally `status == "derived"`, so a third status shoehorned
into that class is either refused as unverified or crashes `spice_expr()` on one
point):

  * RcossDerived   — a vendor-port-derived R(V) law with its (bias x frequency)
                     Rsp-share surface. Emittable as a behavioral resistor AND
                     certifiable at serve time against the deck's actual ring band.
  * RcossAnchor    — one (V_ref, R) declared value (bench-fit or single-bias-derived).
                     Emittable as a FIXED resistor; certifiable only along its stored
                     frequency row (single-bias-derived) or not at all (bench-fit).
                     NEVER golden-eligible.
  * RcossTombstone — a stored structural negative ("this vendor model carries no lossy
                     Coss branch"), bound to the model file sha it was established
                     against. Refuses evaluation; expires when the model changes.

`RcossBundle` holds up to one curve-kind (derived or tombstone) plus one anchor per
part — they legitimately coexist (finding A2).

Tri-state rules: absence of evidence is `None` at the bundle/lookup level, a tombstone
refuses with its `why`, and NOTHING in this module ever evaluates to 0 ohms as a
stand-in for "no data" (a zero would silently short the deck's own damping).

This module is stdlib-only (no numpy/scipy) so the loss tool can import it in any
venv it runs under.
"""
import hashlib
import json
import math

ANCHOR_SOURCES = ("bench-fit", "single-bias-derived")

# bench-fit anchors must record what the fit was FITTED TO, not just where the number
# was written (re-review finding A5: a Q-match against one board's L_loop is not
# portable to another board, and "config sha + out dir + date" cannot show that).
BENCH_FIT_REQUIRED = (
    "board",            # design + revision AND unit/assembly identity
    "target",           # {"q": ..., "q_uncertainty": ..., "f_ring_hz" or "band_hz": ...}
    "waveform_window",  # what part of the waveform the fit read
    "method",           # extraction method
    "artifact_sha256",  # content hash of the measurement artifact (not a mutable dir)
    "operating_point",  # Vin/Vout/Iout/fsw of the fitting run
    "l_loop_nh",        # the loop inductance the Q-match depended on (measured/assumed)
    "run_fingerprints", # deck/config/model/Coss fingerprints of the fitting run
    "objective",        # fit objective + tool fingerprint + fitted value
)


class RcossStoreError(Exception):
    """The store (or one of its entries) is malformed/unsupported. NEVER a lookup miss:
    a raise here must abort the consumer, not be misread as 'part absent'."""


class RcossUnverified(Exception):
    """Evaluation was requested from an object that refuses it (tombstone/absence)."""


def canonical_fingerprint(obj):
    """sha256 over the canonical JSON form of `obj` (sorted keys, no whitespace)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def entry_fingerprint(entry):
    """Material fingerprint of a store entry: everything EXCEPT the review state.

    Keyed so that any material change (points, surface, provenance, anchor value)
    changes the fingerprint and therefore resets review, while flipping
    human_verified/review does not change it (finding A5/F6: an identical law must
    keep its review; a changed law must lose it).
    """
    material = {k: v for k, v in entry.items()
                if k not in ("human_verified", "review", "entry_fingerprint")}
    return canonical_fingerprint(material)


def _finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def _strictly_increasing(xs):
    return all(b > a for a, b in zip(xs, xs[1:]))


class RcossDerived:
    """A curated vendor-port-derived Rcoss(V) law.

    `points`: [(Vds_V, R_ohm)], >= 2, strictly increasing V, all R finite and > 0.
    `vendor_share`: [(Vds_V, f_hz, re_rsp_ohm)] — the vendor Rsp-attributable Re
    samples over the FULL (bias x frequency) grid; the serve-time certificate
    evaluates the emitted model against this surface over the requested band.
    """

    kind = "derived"

    def __init__(self, points, vendor_share, provenance, *, human_verified=False,
                 review=None, fingerprint=None):
        self.points = [(float(v), float(r)) for v, r in points]
        self.vendor_share = [(float(v), float(f), float(re_)) for v, f, re_ in vendor_share]
        self.provenance = dict(provenance)
        self.human_verified = bool(human_verified)
        self.review = dict(review) if review else None
        self.fingerprint = fingerprint
        if len(self.points) < 2:
            raise RcossStoreError(
                f"RcossDerived: need >= 2 bias points, got {len(self.points)} — a "
                f"single point is an ANCHOR, not a derived curve")
        vs = [p[0] for p in self.points]
        if not _strictly_increasing(vs):
            raise RcossStoreError(
                f"RcossDerived: bias axis must be strictly increasing, got {vs} "
                f"(spice_expr divides by adjacent-V differences)")
        bad = [(v, r) for v, r in self.points if not _finite(r) or r <= 0.0]
        if bad:
            raise RcossStoreError(
                f"RcossDerived: non-positive/non-finite R at {bad[:3]} — would short "
                f"its own damping or make the tank active")
        if not self.vendor_share:
            raise RcossStoreError("RcossDerived: vendor_share surface is empty — the "
                                  "serve-time certificate would have nothing to check "
                                  "against (a derived law without its evidence)")
        share_v = {v for v, _f, _r in self.vendor_share}
        for v in vs:
            if not any(abs(v - sv) <= 1e-9 * max(abs(v), 1.0) for sv in share_v):
                raise RcossStoreError(
                    f"RcossDerived: vendor_share carries no frequency row for bias "
                    f"knot {v:g} V — every emitted knot must be certifiable")
        for v, f, re_ in self.vendor_share:
            if not (_finite(f) and f > 0 and _finite(re_) and re_ > 0):
                raise RcossStoreError(
                    f"RcossDerived: malformed vendor_share sample ({v!r}, {f!r}, {re_!r})")

    def share_rows(self):
        """{bias_V: sorted [(f_hz, re_ohm)]} of the stored surface."""
        rows = {}
        for v, f, re_ in self.vendor_share:
            rows.setdefault(v, []).append((f, re_))
        for v in rows:
            rows[v].sort()
            fs = [f for f, _ in rows[v]]
            if not _strictly_increasing(fs):
                raise RcossStoreError(
                    f"RcossDerived: duplicate frequency sample at bias {v:g} V")
        return rows

    def freq_span(self):
        fs = [f for _v, f, _r in self.vendor_share]
        return min(fs), max(fs)

    def at(self, vds):
        """R at a bias, linearly interpolated, flat tails outside the derived span."""
        v = [p[0] for p in self.points]
        r = [p[1] for p in self.points]
        if vds <= v[0]:
            return r[0]
        if vds >= v[-1]:
            return r[-1]
        for i in range(1, len(v)):
            if vds <= v[i]:
                t = (vds - v[i - 1]) / (v[i] - v[i - 1])
                return r[i - 1] + t * (r[i] - r[i - 1])
        return r[-1]

    def spice_expr(self, dnode="D", snode="S"):
        """Behavioral-resistor expression R(V(D,S)) — hinge form, same construction as
        loss/lib/rcoss_derive.RcossCurve.spice_expr (min/max only: portable across
        ngspice/LTspice/QSPICE; clamped => flat tails match .at())."""
        pts = self.points
        v0, r0 = pts[0]
        vhi = pts[-1][0]
        x = f"V({dnode},{snode})"
        vc = f"(min(max({x},{v0:.9g}),{vhi:.9g}))"
        seg = [(pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0])
               for i in range(len(pts) - 1)]
        parts = [f"{r0:.9g}", f"({seg[0]:.9g})*({vc}-{v0:.9g})"]
        for i in range(1, len(seg)):
            d = seg[i] - seg[i - 1]
            if d != 0.0:
                parts.append(f"({d:.9g})*max({vc}-{pts[i][0]:.9g},0)")
        return "+".join(parts)

    def summary(self):
        lo, hi = self.points[0], self.points[-1]
        rev = "human-verified" if self.human_verified else "UNREVIEWED"
        return (f"Rcoss(V) curated: {lo[1]:.4g}..{hi[1]:.4g} ohm over "
                f"{lo[0]:g}-{hi[0]:g} V ({len(self.points)} pts, {rev})")


class RcossAnchor:
    """One declared (V_ref, R) value, served as a FIXED resistor.

    `vendor_share_row`: [(f_hz, re_rsp_ohm)] at V_ref — REQUIRED for
    source="single-bias-derived" (its row check is the only certificate it has,
    finding A4) and absent for "bench-fit" (which is simply uncertified).
    """

    kind = "anchor"

    def __init__(self, v_ref, r_ohm, source, provenance, *, vendor_share_row=None,
                 why_no_curve="", human_verified=False, review=None, fingerprint=None):
        self.v_ref = float(v_ref)
        self.r_ohm = float(r_ohm)
        self.source = source
        self.provenance = dict(provenance)
        self.vendor_share_row = ([(float(f), float(r)) for f, r in vendor_share_row]
                                 if vendor_share_row else None)
        self.why_no_curve = why_no_curve
        self.human_verified = bool(human_verified)
        self.review = dict(review) if review else None
        self.fingerprint = fingerprint
        if source not in ANCHOR_SOURCES:
            raise RcossStoreError(
                f"RcossAnchor: unknown source {source!r} (want one of {ANCHOR_SOURCES}). "
                f"NOTE 'vendor-element' was deliberately dropped: a literal element ohms "
                f"is not the port-equivalent R of the emitted simplified branch")
        if not (_finite(self.r_ohm) and self.r_ohm > 0.0):
            raise RcossStoreError(
                f"RcossAnchor: R must be finite and > 0, got {r_ohm!r} (zero shorts the "
                f"damping; negative goes active)")
        if not (_finite(self.v_ref) and self.v_ref >= 0.0):
            raise RcossStoreError(f"RcossAnchor: V_ref must be finite and >= 0, got {v_ref!r}")
        if not why_no_curve:
            raise RcossStoreError(
                "RcossAnchor: why_no_curve is required — an anchor is a fallback with a "
                "reason, and 'no reason recorded' hides whether a full derivation was "
                "ever attempted")
        if source == "single-bias-derived":
            if not self.vendor_share_row:
                raise RcossStoreError(
                    "RcossAnchor(single-bias-derived): the frequency row at V_ref is "
                    "required — without it the 'one bias row' certificate is decorative "
                    "(re-review finding A4)")
            fs = [f for f, _ in sorted(self.vendor_share_row)]
            if not _strictly_increasing(fs):
                raise RcossStoreError("RcossAnchor: duplicate frequency in vendor_share_row")
            for f, r in self.vendor_share_row:
                if not (_finite(f) and f > 0 and _finite(r) and r > 0):
                    raise RcossStoreError(
                        f"RcossAnchor: malformed vendor_share_row sample ({f!r}, {r!r})")
        elif source == "bench-fit":
            fit = self.provenance.get("fitted_to")
            if not isinstance(fit, dict):
                raise RcossStoreError(
                    "RcossAnchor(bench-fit): provenance.fitted_to block is required "
                    "(finding A5: the entry must record what was fitted, not just where "
                    "the number was written)")
            missing = [k for k in BENCH_FIT_REQUIRED if k not in fit]
            if missing:
                raise RcossStoreError(
                    f"RcossAnchor(bench-fit): fitted_to is missing {missing} "
                    f"(required: {list(BENCH_FIT_REQUIRED)})")

    def summary(self):
        cert = ("row-certifiable" if self.source == "single-bias-derived"
                else "UNCERTIFIED (no band validity)")
        return (f"Rcoss anchor: {self.r_ohm:.4g} ohm @ {self.v_ref:g} V "
                f"({self.source}, {cert}, "
                f"{'human-verified' if self.human_verified else 'UNREVIEWED'}; "
                f"NEVER golden)")


class RcossTombstone:
    """A stored structural negative bound to a specific vendor model file."""

    kind = "tombstone"

    def __init__(self, why, model_sha256, derive_version, provenance=None):
        self.why = why
        self.model_sha256 = model_sha256
        self.derive_version = derive_version
        self.provenance = dict(provenance or {})
        if not why:
            raise RcossStoreError("RcossTombstone: why is required")
        if not model_sha256:
            raise RcossStoreError(
                "RcossTombstone: model_sha256 is required — 'no lossy branch' is a claim "
                "about a specific model file and must expire with it (finding F2)")
        if derive_version is None:
            raise RcossStoreError("RcossTombstone: derive_version is required")

    def at(self, vds):
        raise RcossUnverified(
            f"Rcoss tombstone: {self.why} — this part's vendor model has no derivable "
            f"Coss-path loss. Handle explicitly; do not substitute 0.")

    def summary(self):
        return f"Rcoss: structural negative — {self.why}"


class RcossBundle:
    """Up to one curve-kind (derived or tombstone) plus one anchor for a part."""

    def __init__(self, curve=None, anchor=None):
        if curve is not None and not isinstance(curve, (RcossDerived, RcossTombstone)):
            raise RcossStoreError(f"RcossBundle.curve: bad type {type(curve).__name__}")
        if anchor is not None and not isinstance(anchor, RcossAnchor):
            raise RcossStoreError(f"RcossBundle.anchor: bad type {type(anchor).__name__}")
        self.curve = curve
        self.anchor = anchor
