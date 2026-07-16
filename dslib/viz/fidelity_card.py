"""
fidelity_card — declare each dslib model's error against the datasheet's own
quoted spec points, so "not shown" can never read as "fine".

The idea is borrowed from vendor SPICE-model docs (TI WEBENCH's SIMULATED-vs-
MEASURED table, Vishay's model note): a model should ship proof of where it is
trustworthy. Here we grade the artifacts that actually feed the sim deck against
the datasheet's *own* nameplate value at the *same* condition -- NOT the derived
scalar (``specs.Coss`` is itself extracted from the datasheet, so that would be a
round-trip, not a check).

Rows graded per part:

  * Coss(V) digitised curve @ nameplate Vds   vs  ds['Coss'].typ   -- digitisation fidelity
  * Crss(V) digitised curve @ nameplate Vds   vs  ds['Crss'].typ
  * Qoss = integral Coss(V) dV to the same Vds vs ds['Qoss'].typ   -- INDEPENDENT integral cross-check
  * Qrr_op (Lauritzen-Ma model) @ nameplate    vs  ds['Qrr'].typ   -- does the fit honour its anchor

Guard-checklist discipline (the whole point):
  A row we cannot evaluate -- no digitised curve, missing datasheet field, the
  Qrr model refuses -- renders UNVERIFIED, never PASS. Absence of evidence must
  never encode absence of the problem, and UNVERIFIED is tallied separately.
  In particular Qoss is only graded when the integration limit can be aligned to
  the datasheet's Qoss Vds (or the documented ``Coss_Vds`` anchor); an unknown
  limit is UNVERIFIED, not a condition-misaligned false FAIL.

CLI::

    python -m dslib.viz.fidelity_card                     # audit every digitised-curve part
    python -m dslib.viz.fidelity_card Infineon:IPP024N08NF2S Toshiba:TK100E10N1
    python -m dslib.viz.fidelity_card --html out/fidelity-card.html
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass
from typing import Optional

import numpy as np

import dslib.store
from dslib import mfr_tag
from dslib.field import MpnMfr
from dslib.conditions import normalize_conditions

PASS, WARN, FAIL, UNV = "PASS", "WARN", "FAIL", "UNVERIFIED"

# verdict thresholds (fractional abs error): (pass, warn); above warn => FAIL
TOL = {
    "cap": (0.05, 0.15),   # a digitised cap point should land on its own nameplate tightly
    "qoss": (0.10, 0.25),  # integral vs a separately-quoted scalar; looser
    "qrr": (0.10, 0.30),
}
_ANSI = {PASS: "\033[32mok \033[0m", WARN: "\033[33m~  \033[0m",
         FAIL: "\033[31mXX \033[0m", UNV: "\033[90m?? \033[0m"}


@dataclass
class Row:
    name: str
    model: Optional[float]
    ref: Optional[float]
    unit: str
    cond: str
    kind: str
    note: str = ""
    verdict: str = ""

    def __post_init__(self):
        self.verdict = self._judge()

    @property
    def err(self) -> Optional[float]:
        if self.model is None or self.ref is None:
            return None
        if not np.isfinite(self.model) or not np.isfinite(self.ref) or self.ref == 0:
            return None
        return (self.model - self.ref) / self.ref

    def _judge(self) -> str:
        e = self.err
        if e is None:
            if not self.note:
                self.note = "model artifact or nameplate value missing"
            return UNV
        p, w = TOL[self.kind]
        a = abs(e)
        return PASS if a <= p else WARN if a <= w else FAIL


@dataclass
class Card:
    mfr: str
    mpn: str
    bv: Optional[float]
    rows: list


# ---------------------------------------------------------------- helpers

def _field(ds, sym):
    try:
        f = ds[sym]
    except Exception:
        return None
    return f if (f is not None and f.typ is not None and np.isfinite(f.typ)) else None


def _cond_vds(field) -> Optional[float]:
    """Datasheet test Vds for a Field, via canonicalised conditions (raw keys vary)."""
    if field is None or not field.cond:
        return None
    return normalize_conditions(field.cond).get("Vds")


def _interp_curve(curve, col: int, vds: Optional[float]) -> Optional[float]:
    """curve = list[(Vds, ...)] knot rows — Coss triples (col 1=Coss, 2=Crss) or
    Ciss pairs (col 1=Ciss). pF at vds, or None.
    Refuses to extrapolate past the digitised span."""
    if not curve or vds is None:
        return None
    a = np.array(curve, float)
    V = a[:, 0]
    if vds < V.min() - 1e-9 or vds > V.max() + 1e-9:
        return None
    return float(np.interp(vds, V, a[:, col]))


def _qoss_from_curve(curve, vhi: Optional[float]) -> Optional[float]:
    """integral_0^vhi Coss(V) dV, in nC. None if the curve can't cover [~0, vhi]."""
    if not curve or vhi is None:
        return None
    a = np.array(curve, float)
    V, Coss_pF = a[:, 0], a[:, 1]
    if vhi > V.max() + 1e-9 or V.min() > 1e-9:  # need coverage from ~0 up to vhi
        return None
    trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")  # numpy 2.x rename
    grid = np.linspace(0.0, vhi, 400)
    q = trapz(np.interp(grid, V, Coss_pF) * 1e-12, grid)  # C
    return q * 1e9


# ---------------------------------------------------------------- card build

def build_card(specs, ds) -> list:
    """Grade one part's model artifacts against its datasheet nameplate."""
    rows: list = []
    curve = getattr(specs, "coss_curve", None)

    # Coss(V) curve vs nameplate
    fc = _field(ds, "Coss")
    if curve is None:
        rows.append(Row("Coss(V) curve @Vds", None, fc.typ if fc else None, "pF",
                        "", "cap", note="no digitised Coss curve in dslib"))
    elif fc is None:
        rows.append(Row("Coss(V) curve @Vds", None, None, "pF", "", "cap",
                        note="datasheet has no Coss field"))
    else:
        vds = _cond_vds(fc)
        m = _interp_curve(curve, 1, vds)
        note = "" if m is not None else f"nameplate Vds={vds} outside curve span"
        rows.append(Row("Coss(V) curve @Vds", m, fc.typ, "pF", f"Vds={vds}V", "cap", note))

    # Crss(V) curve vs nameplate
    fr = _field(ds, "Crss")
    if curve is None:
        rows.append(Row("Crss(V) curve @Vds", None, fr.typ if fr else None, "pF",
                        "", "cap", note="no digitised curve"))
    elif fr is None:
        rows.append(Row("Crss(V) curve @Vds", None, None, "pF", "", "cap",
                        note="datasheet has no Crss field"))
    else:
        vds = _cond_vds(fr)
        m = _interp_curve(curve, 2, vds)
        note = "" if m is not None else f"nameplate Vds={vds} outside curve span"
        rows.append(Row("Crss(V) curve @Vds", m, fr.typ, "pF", f"Vds={vds}V", "cap", note))

    # Ciss(V) curve vs nameplate (optional pairs; serves the Cgs = Ciss - Crss basis)
    ciss_curve = getattr(specs, "ciss_curve", None)
    fi = _field(ds, "Ciss")
    if ciss_curve is None:
        rows.append(Row("Ciss(V) curve @Vds", None, fi.typ if fi else None, "pF",
                        "", "cap", note="no digitised Ciss curve in dslib"))
    elif fi is None:
        rows.append(Row("Ciss(V) curve @Vds", None, None, "pF", "", "cap",
                        note="datasheet has no Ciss field"))
    else:
        vds = _cond_vds(fi)
        m = _interp_curve(ciss_curve, 1, vds)
        note = "" if m is not None else f"nameplate Vds={vds} outside curve span"
        rows.append(Row("Ciss(V) curve @Vds", m, fi.typ, "pF", f"Vds={vds}V", "cap", note))

    # Qoss integral cross-check (independent of the scalar model).
    # Integrate to the SAME Vds the datasheet quotes Qoss at, else it is a
    # condition-misalignment false FAIL. Prefer the Qoss field's Vds; fall back
    # to Coss_Vds (documented anchor); if neither is known -> UNVERIFIED.
    fq = _field(ds, "Qoss")
    vq = _cond_vds(fq)
    vq_src = "Qoss cond"
    if vq is None and getattr(specs, "Coss_Vds", None):
        vq, vq_src = specs.Coss_Vds, "Coss_Vds (Qoss Vds unrecorded)"
    q = _qoss_from_curve(curve, vq)
    if curve is None:
        rows.append(Row("Qoss = integral Coss dV", None, fq.typ if fq else None, "nC",
                        "", "qoss", note="no digitised curve to integrate"))
    elif vq is None:
        rows.append(Row("Qoss = integral Coss dV", None, fq.typ if fq else None, "nC",
                        "", "qoss", note="no Vds to align integration limit -> cannot verify"))
    elif q is None:
        rows.append(Row("Qoss = integral Coss dV", None, fq.typ if fq else None, "nC",
                        f"0-{vq:.0f}V", "qoss", note="curve does not span [0, Vds]"))
    elif fq is None:
        rows.append(Row("Qoss = integral Coss dV", q, None, "nC", f"0-{vq:.0f}V",
                        "qoss", note="datasheet quotes no Qoss (integral shown, unverified)"))
    else:
        rows.append(Row("Qoss = integral Coss dV", q, fq.typ, "nC", f"0-{vq:.0f}V",
                        "qoss", note=f"Vds via {vq_src}" if "unrecorded" in vq_src else ""))

    # Qrr: does the Lauritzen-Ma model reproduce its own nameplate anchor?
    fqrr = _field(ds, "Qrr")
    cond = getattr(specs, "qrr_cond", None)
    if fqrr is None:
        rows.append(Row("Qrr_op @nameplate", None, None, "nC", "", "qrr",
                        note="datasheet has no Qrr (Schottky/GaN or unparsed)"))
    elif cond is None:
        rows.append(Row("Qrr_op @nameplate", None, fqrr.typ, "nC", "", "qrr",
                        note="no curated qrr_cond -> LM model cannot be evaluated"))
    else:
        try:
            m = specs.Qrr_op(IF=cond["IF"], didt=cond["didt"], Tj=cond.get("Tj", 25.0)) * 1e9
            c = f"{cond['IF']:.0f}A {cond['didt']/1e6:.0f}A/us {cond.get('Tj', 25):.0f}C"
            rows.append(Row("Qrr_op @nameplate", m, fqrr.typ, "nC", c, "qrr"))
        except Exception as e:
            rows.append(Row("Qrr_op @nameplate", None, fqrr.typ, "nC", "", "qrr",
                            note=f"LM model refused: {type(e).__name__}"))
    return rows


def audit(keys) -> list:
    """Build cards for a list of (mfr, mpn) keys. Loads dslib once."""
    parts = dslib.store.load_parts()
    cards = []
    for mfr, mpn in keys:
        part = parts.get((mfr, mpn))
        if part is None:
            cards.append(Card(mfr, mpn, None, [Row(
                "part", None, None, "", "", "cap", note="not in parts DB")]))
            continue
        specs = part.specs
        try:
            ds = dslib.store.datasheets_db.load_obj(MpnMfr(mfr, mpn=mpn))
        except Exception as e:
            cards.append(Card(mfr, mpn, getattr(specs, "Vds", None), [Row(
                "datasheet", None, None, "", "", "cap",
                note=f"no datasheet fields ({type(e).__name__})")]))
            continue
        cards.append(Card(mfr, mpn, getattr(specs, "Vds", None), build_card(specs, ds)))
    return cards


def keys_with_curves():
    """Every (mfr, mpn) that has a digitised Coss curve -- the default audit set."""
    parts = dslib.store.load_parts()
    return sorted(k for k, p in parts.items() if getattr(p.specs, "coss_curve", None))


def dedupe_base_variants(keys):
    """Collapse orderable-suffix variants (IPP024N08NF2SAKMA1 -> keep IPP024N08NF2S)."""
    kept = []
    for mfr, mpn in sorted(keys, key=lambda k: (k[0], len(k[1]), k[1])):
        if any(m == mfr and mpn.startswith(base) for m, base in kept):
            continue
        kept.append((mfr, mpn))
    return kept


def tally(cards) -> dict:
    t = {PASS: 0, WARN: 0, FAIL: 0, UNV: 0}
    for c in cards:
        for r in c.rows:
            t[r.verdict] = t.get(r.verdict, 0) + 1
    return t


# ---------------------------------------------------------------- terminal

def _fmt(v):
    return f"{v:.4g}" if (v is not None and np.isfinite(v)) else "--"


def print_cards(cards) -> None:
    for c in cards:
        hdr = f"  {c.mfr}:{c.mpn}"
        if c.bv:
            hdr += f"   (BV={c.bv:.0f}V)"
        print("\n" + "=" * 78 + "\n" + hdr + "\n" + "-" * 78)
        print(f"  {'':3}{'quantity':<26}{'model':>11}{'nameplate':>11}{'err':>8}  condition")
        for r in c.rows:
            e = f"{r.err*100:+.1f}%" if r.err is not None else "  --"
            print(f"  {_ANSI[r.verdict]}{r.name:<26}{_fmt(r.model):>11}{_fmt(r.ref):>11}{e:>8}  {r.cond}")
            if r.note:
                print(f"     {'':56}\033[90m{r.note}\033[0m")
    t = tally(cards)
    print("\n" + "=" * 78)
    print(f"  SUMMARY  ok={t[PASS]}  warn={t[WARN]}  FAIL={t[FAIL]}  "
          f"UNVERIFIED={t[UNV]}   over {len(cards)} parts")
    print("  (UNVERIFIED is not PASS -- it flags a model artifact or nameplate value we could not check)")


# ---------------------------------------------------------------- HTML

_STYLE = """
<style>
:root{
  --bg:#f6f7f8; --panel:#fff; --ink:#16181b; --mut:#6b7078; --hair:#e4e6e9; --hair2:#eef0f2;
  --acc:#0b8f9c;
  --ok:#1a7f37; --okbg:#e6f4ea; --warn:#8a5a00; --warnbg:#fbf0da;
  --fail:#c22a2f; --failbg:#fbe6e6; --unv:#5a6270; --unvbg:#eaecef;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1013; --panel:#16191d; --ink:#e7e9ec; --mut:#8b929b; --hair:#262a30; --hair2:#1d2126;
  --acc:#2ec5d3;
  --ok:#46c26a; --okbg:#122a1a; --warn:#d9a648; --warnbg:#2c2411;
  --fail:#ef6a6f; --failbg:#331719; --unv:#9aa2ad; --unvbg:#20242b;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding:2.75rem 1.25rem 4rem}
.ey{font-family:var(--mono);font-size:.7rem;letter-spacing:.22em;text-transform:uppercase;
  color:var(--acc);margin:0 0 .55rem;display:flex;align-items:center;gap:.6rem}
.ey::before{content:"";width:26px;height:2px;background:var(--acc)}
h1{font-family:var(--mono);font-weight:600;font-size:2rem;letter-spacing:-.01em;margin:0 0 .5rem;
  text-wrap:balance}
.lede{color:var(--mut);max-width:64ch;margin:0 0 2rem}
.lede b{color:var(--ink);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem;margin:0 0 1.4rem}
.tile{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:.95rem 1rem}
.tile .k{font-family:var(--mono);font-size:2rem;font-weight:600;line-height:1;
  font-variant-numeric:tabular-nums}
.tile .l{font-family:var(--mono);font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--mut);margin-top:.5rem}
.tile.ok .k{color:var(--ok)} .tile.warn .k{color:var(--warn)}
.tile.fail .k{color:var(--fail)} .tile.unv .k{color:var(--unv)}
.meta{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem;color:var(--mut);font-size:.82rem;
  font-family:var(--mono);margin:0 0 2.2rem;padding-bottom:1.6rem;border-bottom:1px solid var(--hair)}
.meta b{color:var(--ink);font-weight:600}
.method{background:var(--panel);border:1px solid var(--hair);border-left:2px solid var(--acc);
  border-radius:10px;padding:1rem 1.15rem;margin:0 0 2.4rem;font-size:.88rem}
.method h3{font-family:var(--mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--mut);margin:0 0 .6rem;font-weight:600}
.method ul{margin:0;padding-left:1.1rem} .method li{margin:.2rem 0}
.method .rule b{color:var(--unv)}
.sec{font-family:var(--mono);font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--mut);margin:2.4rem 0 1rem;display:flex;align-items:center;gap:.8rem}
.sec::after{content:"";flex:1;height:1px;background:var(--hair)}
.grid{display:grid;grid-template-columns:1fr;gap:.9rem}
.card{background:var(--panel);border:1px solid var(--hair);border-radius:12px;overflow:hidden}
.card.s-fail{border-color:color-mix(in srgb,var(--fail) 45%,var(--hair))}
.card.s-unv{background:color-mix(in srgb,var(--unvbg) 25%,var(--panel))}
.card>header{display:flex;align-items:center;gap:.6rem;padding:.7rem 1rem;
  border-bottom:1px solid var(--hair2)}
.dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--mut)}
.s-ok .dot{background:var(--ok)} .s-warn .dot{background:var(--warn)}
.s-fail .dot{background:var(--fail)} .s-unv .dot{background:var(--unv)}
.mpn{font-family:var(--mono);font-size:.9rem;color:var(--mut)}
.mpn b{color:var(--ink);font-weight:600;margin-left:.35em}
.bv{margin-left:auto;font-family:var(--mono);font-size:.72rem;color:var(--mut);
  border:1px solid var(--hair);border-radius:6px;padding:.12rem .45rem}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:.83rem}
thead th{color:var(--mut);font-weight:500;font-size:.66rem;letter-spacing:.09em;text-transform:uppercase;
  text-align:left;padding:.5rem 1rem;border-bottom:1px solid var(--hair2)}
tbody td{padding:.44rem 1rem;border-top:1px solid var(--hair2);vertical-align:middle}
tbody tr:first-child td{border-top:none}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.q{color:var(--ink)} td.c{color:var(--mut);font-size:.78rem;white-space:nowrap}
td.e{color:var(--mut)}
tr.v-ok td.e{color:var(--ok)} tr.v-warn td.e{color:var(--warn)} tr.v-fail td.e{color:var(--fail)}
.u{color:var(--mut);font-size:.82em;margin-left:.15em}
.vb{width:1%;white-space:nowrap}
.chip{display:inline-block;min-width:2.4rem;text-align:center;padding:.12rem .4rem;border-radius:5px;
  font-size:.66rem;font-weight:700;letter-spacing:.03em}
.chip.ok{background:var(--okbg);color:var(--ok)} .chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.fail{background:var(--failbg);color:var(--fail)} .chip.unv{background:var(--unvbg);color:var(--unv)}
td.db,th.db{width:96px}
.dev{position:relative;display:block;width:84px;height:14px}
.dev .zero{position:absolute;left:50%;top:1px;bottom:1px;width:1px;background:var(--hair)}
.dev .mk{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;
  transform:translate(-50%,-50%)}
.dev .mk.v-ok{background:var(--ok)} .dev .mk.v-warn{background:var(--warn)}
.dev .mk.v-fail{background:var(--fail)}
.dev.dev-x::after{content:"";position:absolute;left:0;right:0;top:50%;height:0;
  border-top:1px dashed var(--hair)}
.notes{padding:.5rem 1rem .7rem;border-top:1px solid var(--hair2);background:var(--hair2)}
.note{font-family:var(--mono);font-size:.74rem;color:var(--mut);padding:.08rem 0}
.note::before{content:"— "}
.foot{margin-top:2.6rem;padding-top:1.4rem;border-top:1px solid var(--hair);color:var(--mut);
  font-family:var(--mono);font-size:.74rem;line-height:1.7}
.foot b{color:var(--ink)}
@media (max-width:760px){.tiles{grid-template-columns:repeat(2,1fr)}
  td.db,th.db{display:none} h1{font-size:1.6rem}}
</style>
"""

_CLS = {PASS: "ok", WARN: "warn", FAIL: "fail", UNV: "unv"}
_LBL = {PASS: "ok", WARN: "warn", FAIL: "FAIL", UNV: "??"}


def _overall(card) -> str:
    vs = [r.verdict for r in card.rows]
    if FAIL in vs:
        return "fail"
    if all(v == UNV for v in vs):
        return "unv"
    if WARN in vs:
        return "warn"
    return "ok"


def _devbar(r) -> str:
    """Deviation marker: centre = 0 error, full scale = the FAIL threshold (30%)."""
    if r.err is None:
        return "<span class='dev dev-x'></span>"
    frac = max(-1.0, min(1.0, r.err / 0.30))
    return (f"<span class='dev'><i class='zero'></i>"
            f"<i class='mk v-{_CLS[r.verdict]}' style='left:{50 + frac * 48:.1f}%'></i></span>")


def _num_html(v, unit) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    u = f"<span class='u'>{_html.escape(unit)}</span>" if unit else ""
    return f"{v:.4g}{u}"


def _render_card_html(card) -> str:
    e = _html.escape
    bv = f"<span class='bv'>BV {card.bv:.0f} V</span>" if card.bv else ""
    rows, notes = [], []
    for r in card.rows:
        err = f"{r.err*100:+.1f}%" if r.err is not None else "—"
        rows.append(
            f"<tr class='v-{_CLS[r.verdict]}'>"
            f"<td class='vb'><span class='chip {_CLS[r.verdict]}'>{_LBL[r.verdict]}</span></td>"
            f"<td class='q'>{e(r.name)}</td>"
            f"<td class='n'>{_num_html(r.model, r.unit)}</td>"
            f"<td class='n'>{_num_html(r.ref, r.unit)}</td>"
            f"<td class='n e'>{err}</td>"
            f"<td class='db'>{_devbar(r)}</td>"
            f"<td class='c'>{e(r.cond)}</td></tr>")
        if r.note:
            notes.append(f"<div class='note'>{e(r.note)}</div>")
    note_html = f"<div class='notes'>{''.join(notes)}</div>" if notes else ""
    return (
        f"<article class='card s-{_overall(card)}'>"
        f"<header><span class='dot'></span><span class='mpn'>{e(card.mfr)}"
        f"<b>{e(card.mpn)}</b></span>{bv}</header>"
        f"<table><thead><tr><th></th><th>quantity</th><th class='n'>model</th>"
        f"<th class='n'>nameplate</th><th class='n'>err</th><th class='db'>deviation</th>"
        f"<th>condition</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"{note_html}</article>")


def render_html(cards) -> str:
    t = tally(cards)
    n_checks = sum(len(c.rows) for c in cards)
    graded = [c for c in cards if _overall(c) != "unv"]
    unverified = [c for c in cards if _overall(c) == "unv"]

    def tile(k, label, cls):
        return f"<div class='tile {cls}'><div class='k'>{k}</div><div class='l'>{label}</div></div>"

    out = ['<!doctype html><html><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>dslib fidelity cards</title>', _STYLE, '</head><body><div class="wrap">']
    out.append('<p class="ey">Model QA · datasheet fidelity</p>')
    out.append('<h1>dslib fidelity cards</h1>')
    out.append('<p class="lede">Every homemade model declares its own error against the '
               "datasheet's <b>own quoted spec point</b> — so \"not shown\" can never read as "
               '"fine". Graded: the digitized <b>Coss(V)/Crss(V)</b> curves and the '
               'Lauritzen–Ma <b>Qrr</b> model, evaluated back at the nameplate condition.</p>')
    out.append("<div class='tiles'>" + tile(t[PASS], "passed", "ok")
               + tile(t[WARN], "warn", "warn") + tile(t[FAIL], "failed", "fail")
               + tile(t[UNV], "unverified", "unv") + "</div>")
    out.append(f"<div class='meta'><span><b>{len(cards)}</b> parts</span>"
               f"<span><b>{n_checks}</b> checks</span>"
               f"<span>graded <b>{len(graded)}</b></span>"
               f"<span>unverified <b>{len(unverified)}</b></span>"
               f"<span>generated by <b>dslib.viz.fidelity_card</b></span></div>")
    out.append(
        "<div class='method'><h3>What each row checks</h3><ul>"
        "<li><b>Coss(V) / Crss(V) curve</b> — the digitized curve interpolated at the datasheet's "
        "own Vds, vs the nameplate typ. Catches a digitization drifting off its own spec point.</li>"
        "<li><b>Qoss = ∫Coss(V)dV</b> — an <em>independent</em> cross-check: the curve's integral "
        "(to the same Vds the datasheet quotes) vs the separately-listed Qoss scalar.</li>"
        "<li><b>Qrr_op</b> — the Lauritzen–Ma body-diode model at the nameplate IF / di·dt / Tj, "
        "vs the datasheet Qrr. Confirms the fit honours its own anchor.</li></ul>"
        "<p class='rule' style='margin:.7rem 0 0'><b>UNVERIFIED is not PASS.</b> "
        "A row with no digitized curve, no curated condition, or an unalignable integration "
        "limit reads <b>??</b>, never green — absence of evidence must never encode absence "
        "of the problem.</p></div>")
    if graded:
        out.append("<div class='sec'>Graded vs nameplate</div><div class='grid'>")
        out += [_render_card_html(c) for c in graded]
        out.append("</div>")
    if unverified:
        out.append("<div class='sec'>Unverified — no model artifacts yet</div><div class='grid'>")
        out += [_render_card_html(c) for c in unverified]
        out.append("</div>")
    out.append("<div class='foot'>Tolerances (|err| pass / warn, above = FAIL): "
               "cap points <b>5% / 15%</b> · Qoss integral <b>10% / 25%</b> · "
               "Qrr <b>10% / 30%</b>. Deviation dots are drawn on a ±30% full-scale track.</div>")
    out.append("</div></body></html>")
    return "".join(out)


# ---------------------------------------------------------------- CLI

def _resolve(arg):
    if ":" not in arg:
        raise SystemExit(f"need MFR:MPN, got {arg!r}")
    mfr_raw, mpn = arg.split(":", 1)
    return mfr_tag(mfr_raw), mpn


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dslib.viz.fidelity_card",
        description="Grade dslib model artifacts against datasheet nameplate spec points.")
    p.add_argument("parts", nargs="*", metavar="MFR:MPN",
                   help="parts to audit (default: every part with a digitised Coss curve)")
    p.add_argument("--with", dest="extra", action="append", default=[], metavar="MFR:MPN",
                   help="audit this part IN ADDITION to the default set (repeatable)")
    p.add_argument("--dedupe", action="store_true",
                   help="collapse orderable-suffix variants (…AKMA1) onto their base MPN")
    p.add_argument("--html", metavar="PATH", nargs="?", const="out/fidelity-card.html",
                   help="write an HTML report (default path out/fidelity-card.html)")
    p.add_argument("--quiet", action="store_true", help="suppress the terminal table")
    args = p.parse_args(argv)

    keys = [_resolve(a) for a in args.parts] if args.parts else keys_with_curves()
    if args.dedupe:
        keys = dedupe_base_variants(keys)
    keys += [_resolve(a) for a in args.extra]
    cards = audit(keys)

    if not args.quiet:
        print_cards(cards)
    if args.html:
        import os
        os.makedirs(os.path.dirname(args.html) or ".", exist_ok=True)
        with open(args.html, "w") as f:
            f.write(render_html(cards))
        print(f"\nwrote {args.html}")

    return 1 if tally(cards)[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
