import glob
import json
import os.path
from collections import defaultdict
from typing import Dict, Tuple

from dslib.field import Field, DatasheetFields
from dslib.pdf2txt.parse import parse_datasheet, detect_fields
from dslib.store import Mpn, Mfr


def main():
    file_paths = sorted(glob.glob("../fet-data-extractor/benchmark/**/llm_*.json", recursive=True))

    num_fields_by_pl = defaultdict(int)
    num_fields_by_pl_sym = defaultdict(lambda: defaultdict(int))

    num_equal_by_pl = defaultdict(int)
    num_equal_by_pl_sym = defaultdict(lambda: defaultdict(int))

    def count_fields(pl_name, fields: DatasheetFields):
        num_fields_by_pl[pl_name] += len(fields)
        for sym in fields.keys():
            num_fields_by_pl_sym[pl_name][sym] += 1

    refs: Dict[Tuple[Mfr, Mpn], DatasheetFields] = dict()

    relevant_symbols = 'Coss Qg Qg_th Qgd Qgs Qgs2 Qrr Qsw Vpl Vsd tFall tRise'.split(' ')

    def count_equal_to_ref(pl_name, fields: DatasheetFields, ref: DatasheetFields):
        num_equal_by_pl[pl_name] += ref.count_equal(fields, err_threshold=0.05)
        for sym in ref.keys():
            num_equal_by_pl_sym[pl_name][sym] += ref.count_equal(fields, symbols=[sym], err_threshold=0.05)

    for file_path in file_paths:
        with open(file_path, "r") as f:
            data = json.load(f)

        pl_name = os.path.basename(file_path)[len('llm_extract_'):].split(".")[0]
        mfr = file_path.split('/')[-3]
        mpn = file_path.split('/')[-2]

        fields = find_fields_from_json(data, mfr, mpn)

        if (mfr, mpn) not in refs:
            ds_path = os.path.join('datasheets', mfr, mpn + '.pdf')
            ref = parse_datasheet(ds_path, mfr=mfr, mpn=mpn)
            count_fields('tabular_parse', ref)
            count_equal_to_ref('tabular_parse', ref, ref)
            refs[(mfr, mpn)] = ref

        count_fields(pl_name, fields)
        count_equal_to_ref(pl_name, fields, refs[(mfr, mpn)])

        refs[(mfr, mpn)].show_diff(fields, relevant_symbols, err_threshold=0.05, title=pl_name) or print(mfr, mpn)

    all_syms = sorted(set(sum(map(list, num_fields_by_pl_sym.values()), [])))

    num_total_fields = len(all_syms) * len(file_paths)

    print('')
    s = ' '.join(map(lambda t: '%4s' % t, all_syms))
    print('num fields by pipeline from %s datasheets:' % len(refs))
    print(' ' * 40, '  total     ', s)
    for k, v in sorted(num_fields_by_pl.items(), key=lambda t: -t[1]):
        s = ' '.join(['%4.0f' % num_fields_by_pl_sym[k][s] for s in all_syms])
        print('%40s: %4d (%3.0f%%)' % (k, v, 100 * v / max(num_fields_by_pl.values())), s)

    print('')
    print('num *EQUAL* *VALUES*:')
    print(' ' * 40, '  total     ')
    for k, v in sorted(num_equal_by_pl.items(), key=lambda t: -t[1]):
        s = ' '.join(['%4.0f' % num_equal_by_pl_sym[k][s] for s in all_syms])
        print('%40s: %4d (%3.0f%%)' % (k, v, 100 * v / max(num_equal_by_pl.values())), s)


def find_fields_from_json(data, mfr, mpn):
    ds = DatasheetFields()

    def _iterate_node(o, name='root'):
        nonlocal mfr, mpn

        if not isinstance(o, dict):
            return

        name_candidates = [name, o.get('symbol', ''), o.get('parameter', '')]

        m, field_sym = detect_fields(mfr, name_candidates)

        if m is not None:
            try:
                f = Field(field_sym, min=o.get('min'), typ=o.get('typ') or o.get('value'), max=o.get('max'),
                          unit=o.get('unit'), cond=o)
                ds.add(f)
            except Exception as e:
                print(mfr, mpn, 'error parsing field', e, o)

        for row_name, row in o.items():
            _iterate_node(row, row_name)

    _iterate_node(data)
    return ds


if __name__ == '__main__':
    main()
