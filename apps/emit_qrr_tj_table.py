"""Generate dslib/qrr_tj_table.py — Qrr(Tj) exponents fitted from datasheet TABLE pairs.

    python3 apps/emit_qrr_tj_table.py            # report only
    python3 apps/emit_qrr_tj_table.py --emit     # rewrite the generated module

The IR/AUIR recovery sections print (Qrr, trr) at 25 C AND 125 C for one (IF, di/dt)
(fetlib#41) — direct evidence for the tau temperature exponent, from the table, with no
chart digitisation. This generator finds those paired sections with the SAME extractor
that feeds the layout-conditions registry (apps/emit_qrr_layout_conditions.py, _ir_rows:
one candidate per self-tagged Tj row), fits each pair with
dslib.qrr_tj_fit.fit_n_tau_2rows, and emits per-part results.

NOT CONSUMED by dslib.qrr_model.resolve_n_tau. Wiring measured evidence into the
three-state resolution is a human-gated step (the AO chart fits went through a dual-agent
+ human review before QRR_TJ_MEASURED was written); this module is the evidence packet
for that review, nothing more.

Guards, in the order they refuse:

* Corroboration: the DB's independently-parsed (Qrr, trr) must match ONE of the two
  printed rows (either temperature — which one is recorded). Extraction junk that
  matches neither never reaches the fit.
* q0 (the capacitive share inside BOTH integrals) is subtracted only when the part's
  Qoss(VR) comes from a datasheet Coss CURVE (MODEL_STATE_CURVE) — the 1/sqrt(V) scalar
  guess is out-of-calibration for QRR_QOSS_FRACTION and its known corruption mode is
  anti-monotone (see dcdc_buck_ls). Raw fits are labelled q0_basis='none'; fitting raw
  biases n_tau LOW (non-conservative), which the reviewer sees, not a silent default.
* fit_n_tau_2rows refuses non-growing hot charge (displacement-dominated), q0 consuming
  a charge, and cold rows that are not LM-representable.
* The printed hot trr is a fit-free holdout; its residual rides along per entry.
"""
import importlib.util
import json
import math
import os
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

_spec = importlib.util.spec_from_file_location(
    "emit_qrr_layout_conditions",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "emit_qrr_layout_conditions.py"))
lay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lay)

OUT = os.path.join(REPO, 'dslib', 'qrr_tj_table.py')
COLD_BAND = (20.0, 30.0)
HOT_BAND = (100.0, 175.0)


def paired_sections(blocks):
    """[(cold_cand, hot_cand)] from _ir_rows candidates sharing one section.

    Candidates of one section share the identical block-lines list object; a section
    qualifies when it has exactly one row in the cold band and one in the hot band,
    both with a printed charge AND time (the time is the fit's anchor / holdout)."""
    by_block = {}
    for c, blk in blocks:
        by_block.setdefault(id(blk), []).append(c)
    out = []
    for cands in by_block.values():
        cold = [c for c in cands if COLD_BAND[0] <= c['Tj'] <= COLD_BAND[1]]
        hot = [c for c in cands if HOT_BAND[0] <= c['Tj'] <= HOT_BAND[1]]
        if (len(cold) == 1 and len(hot) == 1
                and all(c['qrr_seen'] and c['trr_seen'] for c in (cold[0], hot[0]))):
            out.append((cold[0], hot[0]))
    return out


def harvest():
    import warnings
    warnings.filterwarnings('ignore')
    from dclib.powerloss import qoss_at
    from dclib.coss_loss import MODEL_STATE_CURVE
    from dslib.qrr_model import LMFitError, QRR_QOSS_FRACTION
    from dslib.qrr_tj_fit import fit_n_tau_2rows
    from dslib.store import datasheets_db, load_parts

    parts = load_parts()
    stats, out = Counter(), []
    for key, ds in datasheets_db.load().items():
        fq, ft = ds.fields_filled.get('Qrr'), ds.fields_filled.get('trr')
        try:
            qrr = fq.typ_or_max_or_min if fq else None
            trr = ft.typ_or_max_or_min if ft else None
        except ValueError:
            qrr = trr = None
        if not qrr or not trr or math.isnan(qrr) or math.isnan(trr):
            continue                          # no independent values to corroborate with
        unit = str(getattr(fq, 'unit', '') or '').strip().lower()
        if unit and unit not in ('nc',):
            continue                          # untrustworthy scale, same gate as layout
        pdf = os.path.join(REPO, 'datasheets', key[0], key[1] + '.pdf')
        if not os.path.exists(pdf):
            continue
        pairs = paired_sections(lay.extract_all_blocks(lay.layout_text(pdf)))
        if not pairs:
            continue                          # not the paired-row layout: not our part
        if len(pairs) > 1:
            stats['ambiguous: multiple paired sections'] += 1
            continue
        cold, hot = pairs[0]
        q_c, t_c = cold['qrr_seen'][0] * 1e-9, cold['trr_seen'][0] * 1e-9
        q_h, t_h = hot['qrr_seen'][0] * 1e-9, hot['trr_seen'][0] * 1e-9
        # corroboration: the DB's parse must agree with ONE of the printed rows
        if lay._near(qrr, cold['qrr_seen']) and lay._near(trr, cold['trr_seen']):
            corr = 'cold'
        elif lay._near(qrr, hot['qrr_seen']) and lay._near(trr, hot['trr_seen']):
            corr = 'hot'
        else:
            stats['DB corroborates neither printed row'] += 1
            continue
        q0, q0_basis = 0.0, 'none'
        mf = getattr(parts.get(key), 'specs', None)
        if mf is not None and cold['VR'] is not None:
            qd = qoss_at(mf, cold['VR'], detail=True)
            if qd['model_state'] == MODEL_STATE_CURVE and math.isfinite(qd['qoss_c']):
                q0, q0_basis = QRR_QOSS_FRACTION * qd['qoss_c'], 'coss-curve'
        try:
            r = fit_n_tau_2rows(q_c, t_c, q_h, t_h, IF=cold['IF'], didt=cold['didt'],
                                tj_cold=cold['Tj'], tj_hot=hot['Tj'], q0=q0)
        except LMFitError as e:
            stats['fit refused: %s' % str(e).split('(')[0].strip()[:60]] += 1
            continue
        stats['ACCEPTED'] += 1
        out.append(dict(
            mfr=key[0], mpn=key[1], n_tau=round(r['n_tau'], 4),
            q0_basis=q0_basis, q0_nc=round(q0 * 1e9, 2),
            qrr_ratio=round(r['qrr_ratio'], 4),
            trr_hot_resid=round(r['trr_hot_resid'], 4),
            corroborated_row=corr,
            tj_cold=cold['Tj'], tj_hot=hot['Tj'],
            IF=cold['IF'], didt=cold['didt'], VR=cold['VR'],
            qrr_cold_nc=q_c * 1e9, trr_cold_ns=t_c * 1e9,
            qrr_hot_nc=q_h * 1e9, trr_hot_ns=t_h * 1e9,
        ))
    out.sort(key=lambda r: (r['mfr'], r['mpn']))
    return out, stats


def die_pool(cands):
    """Distinct dies (package/order-code variants collapse on identical printed rows)
    -> sorted n_tau list, per q0 basis."""
    dies = {}
    for r in cands:
        k = (r['IF'], r['didt'], r['qrr_cold_nc'], r['trr_cold_ns'],
             r['qrr_hot_nc'], r['trr_hot_ns'])
        dies.setdefault(k, r)
    by_basis = {}
    for r in dies.values():
        by_basis.setdefault(r['q0_basis'], []).append(r['n_tau'])
    return {b: sorted(v) for b, v in by_basis.items()}


HEADER = '''"""GENERATED -- do not edit. Rebuild with:

    python3 apps/emit_qrr_tj_table.py --emit

Qrr(Tj) tau exponents fitted from datasheet TABLE pairs -- sheets (IR/AUIR layout)
that print (Qrr, trr) at 25 C AND 125 C for one (IF, di/dt). Fit:
dslib.qrr_tj_fit.fit_n_tau_2rows (TM held, tau inverted per temperature, printed hot
trr as a fit-free holdout -- its residual is per entry below). See the generator for
the corroboration and q0 gates.

NOT consumed by dslib.qrr_model.resolve_n_tau: this is REVIEW EVIDENCE, like the AO
chart fits were before QRR_TJ_MEASURED was written by hand after a human gate.
Entries with q0_basis='none' were fitted raw (no Coss curve for Qoss(VR)); raw fits
of a contaminated integral bias n_tau LOW, the non-conservative direction.
"""

QRR_TJ_TABLE = {
'''

FOOTER = '''}


def qrr_tj_table_for(mfr, mpn):
    """(mfr, mpn) -> entry dict or None; base-MPN variant fallback as elsewhere."""
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(QRR_TJ_TABLE, mfr, mpn)
    return dict(hit) if hit else None
'''


def emit(cands):
    with open(OUT, 'w') as fh:
        fh.write(HEADER)
        for r in cands:
            fh.write(
                '    ("%s", "%s"): dict(n_tau=%g, q0_basis=%r, q0_nc=%g,\n'
                '        qrr_ratio=%g, trr_hot_resid=%g, corroborated_row=%r,\n'
                '        tj_cold=%g, tj_hot=%g, IF=%g, didt=%g, VR=%s,\n'
                '        qrr_cold_nc=%g, trr_cold_ns=%g, qrr_hot_nc=%g, trr_hot_ns=%g),\n'
                % (r['mfr'], r['mpn'], r['n_tau'], r['q0_basis'], r['q0_nc'],
                   r['qrr_ratio'], r['trr_hot_resid'], r['corroborated_row'],
                   r['tj_cold'], r['tj_hot'], r['IF'], r['didt'],
                   'None' if r['VR'] is None else '%g' % r['VR'],
                   r['qrr_cold_nc'], r['trr_cold_ns'],
                   r['qrr_hot_nc'], r['trr_hot_ns']))
        fh.write(FOOTER)
    print('wrote %s (%d entries)' % (OUT, len(cands)))


if __name__ == '__main__':
    cands, stats = harvest()
    for k, n in stats.most_common():
        print('  %5d  %s' % (n, k))
    pools = die_pool(cands)
    for basis, ns in pools.items():
        n = len(ns)
        print('  distinct dies (q0=%s): %d  n_tau median %.3f  IQR %.3f-%.3f  '
              'range %.3f-%.3f'
              % (basis, n, ns[n // 2], ns[n // 4], ns[3 * n // 4], ns[0], ns[-1]))
    if os.path.isdir(os.path.join(REPO, 'out')):
        json.dump(cands, open(os.path.join(REPO, 'out', 'qrr_tj_table.json'), 'w'),
                  indent=1)
    if '--emit' in sys.argv:
        emit(cands)
    else:
        print('\n(dry run -- pass --emit to rewrite %s)' % os.path.relpath(OUT, REPO))
