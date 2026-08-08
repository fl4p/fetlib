"""Spec-table anchors for the C(V) digitizer, served FROM fetlib's parsed datasheets.

The digitizer validates a digitized Coss/Crss/Ciss trace against the datasheet's own
spec table (value at a stated Vds) and its Qoss/Coss(ER)/Coss(TR) row. It used to
re-extract those numbers itself from a `<part>.pdf.nop.csv` render -- a second, weaker
parser over the same PDFs fetlib already parses with the text/v2/tabular stack, the
manual-override registry and the unit-repair history behind it.

That second parser is where EPC silently lost: its symbol match is case-sensitive
(`Coss` vs EPC's printed `COSS`), so `parse_capacitance_anchors` returned {} for every
EPC part while fetlib held Coss=557 pF @ 50 V, Crss=3.6 pF, Ciss=1864 pF and
Qoss=47 nC @ 50 V for the same device. The export gate then reported
`missing_coss_anchor` -- which reads as "the datasheet has no Coss" and is not what
happened. Nineteen human-GREEN EPC curves were unlandable for that reason alone.

So fetlib owns the anchors and the digitizer consumes them. This module renders them in
the shape the digitizer already carries in each digitization row:

    {"<PART>": {"anchors": {"Coss": {"value_pf": .., "vds_v": ..}, ...},
                "output_charge": {"qoss_pc": .., "vint_v": .., "coer_pf": .., "cotr_pf": ..},
                "provenance": {...}}}

Fail-closed rules, all inherited from the pipeline rather than reinvented here:
- a stat that is NaN, or a symbol with no Vds condition, yields NO anchor. A missing
  anchor is a rejected export downstream; a guessed one is a silently wrong curve.
- the Vds condition passes the same |Vds| >= 5 V plausibility floor `field.py` applies
  to Coss/Qoss conditions (below that the corpus is dominated by a mis-bucketed
  `f=1 MHz` artifact), and p-channel negatives are kept by magnitude.
- units follow `field_mul`: capacitance stats are pF, charge stats nC. Those are the
  scalings the whole loss model already runs on, so an anchor can never disagree with
  the `scalar:` Coss it is meant to replace.
"""

import json
import math
from typing import Dict, Iterable, Optional, Tuple

CAP_SYMBOLS = ('Ciss', 'Coss', 'Crss')
VDS_FLOOR = 5.0  # see dslib/field.py's Coss/Qoss condition floor


def _stat(field, prefer=('typ', 'max', 'min')):
    """The value the pipeline would read, with its stat name, or (None, None)."""
    for st in prefer:
        v = getattr(field, st, None)
        if v is not None and isinstance(v, (int, float)) and not math.isnan(v):
            return float(v), st
    return None, None


def _vds_of(ds, symbol) -> Optional[float]:
    """The Vds condition attached to any field of `symbol`, largest magnitude wins
    (matching field.py's `max(coss_cond)`), or None when the datasheet states none."""
    from dslib.conditions import normalize_conditions
    vals = []
    for f in ds.fields_lists.get(symbol, []):
        v = normalize_conditions(f.cond).get('Vds')
        if v and abs(v) >= VDS_FLOOR:
            vals.append(v)
    return max(vals, key=abs) if vals else None


def anchors_for(ds) -> Dict[str, object]:
    """Render one part's anchors from its DatasheetFields record."""
    out_anchors, prov = {}, {}
    # Ciss/Crss commonly share ONE printed condition cell with Coss (EPC prints it on
    # the Ciss row only). Falling back to the group's Coss/Qoss Vds is what the printed
    # table means; it is not a guess -- but only within the same capacitance group.
    group_vds = _vds_of(ds, 'Coss') or _vds_of(ds, 'Qoss')
    for sym in CAP_SYMBOLS:
        f = ds.fields_filled.get(sym)
        if f is None:
            continue
        value_pf, stat = _stat(f)
        if value_pf is None:
            continue
        vds = _vds_of(ds, sym) or group_vds
        if vds is None:
            continue  # no stated condition -> no anchor, never a guessed one
        out_anchors[sym] = dict(value_pf=value_pf, vds_v=abs(float(vds)))
        prov[sym] = dict(stat=stat, source=getattr(f, 'source', None),
                         vds_from='own' if _vds_of(ds, sym) else 'capacitance-group')

    charge = {}
    qf = ds.fields_filled.get('Qoss')
    if qf is not None:
        q_nc, q_stat = _stat(qf)
        q_vds = _vds_of(ds, 'Qoss') or group_vds
        if q_nc is not None and q_vds is not None:
            charge['qoss_pc'] = q_nc * 1000.0   # field_mul: charge stats are nC
            charge['vint_v'] = abs(float(q_vds))
            prov['Qoss'] = dict(stat=q_stat, source=getattr(qf, 'source', None))
    for sym, key, vkey in (('Coss_ER', 'coer_pf', 'coer_vint_v'),
                           ('Coss_TR', 'cotr_pf', 'cotr_vint_v')):
        f = ds.fields_filled.get(sym)
        if f is None:
            continue
        v, st = _stat(f)
        if v is not None:
            charge[key] = v
            # Co(er)/Co(tr) carry their OWN integration voltage and it is routinely NOT
            # the Coss row's condition: Infineon states Coss @ 50 V but Co(er) over
            # 0->80 V (80% of BVdss), while onsemi states Co(er) @ 50 V. Energy goes as
            # V^2, so validating a curve integrated to 50 V against a figure defined to
            # 80 V is off by ~2.5x -- it would reject good curves and could pass bad
            # ones. So this reads the symbol's own condition ONLY: no fall back to
            # group_vds, and none to Qoss's vint_v. Absent condition -> no voltage
            # emitted, and the consumer's energy tier must refuse rather than guess.
            vint = _vds_of(ds, sym)
            if vint is not None:
                charge[vkey] = abs(float(vint))
            prov[sym] = dict(stat=st, source=getattr(f, 'source', None),
                             vint_from='own' if vint is not None else None)

    return dict(anchors=out_anchors, output_charge=charge, provenance=prov)


def build_anchor_table(parts: Iterable[Tuple[str, str]]) -> Tuple[Dict[str, dict], dict]:
    """{PART: entry} for the given (mfr, mpn) parts, keyed by the MPN the digitizer uses
    (the PDF basename). Parts with no stored record, or with no anchorable stat, are
    counted and OMITTED -- an absent key means 'fetlib has no anchor', which the
    digitizer must treat as missing, not as zero."""
    import dslib.store
    table, stats = {}, dict(parts=0, with_coss=0, with_all_three=0, with_qoss=0,
                            no_record=0, no_anchor=0)
    for mfr, mpn in parts:
        stats['parts'] += 1
        # iter_items, not load_obj: the store key is the RAW mpn and load_obj wants a
        # record-shaped object, while mpn_like resolves the spelling the ranking uses.
        ds = next((d for _, d in dslib.store.datasheets_db.iter_items(
            mfr=mfr, mpn_like=mpn)), None)
        if ds is None:
            stats['no_record'] += 1
            continue
        entry = anchors_for(ds)
        anchors, charge = entry['anchors'], entry['output_charge']
        if not anchors and not charge:
            stats['no_anchor'] += 1
            continue
        stats['with_coss'] += int('Coss' in anchors)
        stats['with_all_three'] += int(all(s in anchors for s in CAP_SYMBOLS))
        stats['with_qoss'] += int('qoss_pc' in charge)
        entry['mfr'], entry['mpn'] = mfr, mpn
        table[mpn] = entry
    return table, stats


def write_anchor_table(parts: Iterable[Tuple[str, str]], path: str) -> dict:
    table, stats = build_anchor_table(parts)
    with open(path, 'w') as fh:
        json.dump(table, fh, indent=1, sort_keys=True)
    return stats
