import glob
import json
import os.path
from collections import defaultdict

from dslib.field import Field
from dslib.pdf2txt import normalize_dash
from dslib.pdf2txt.parse import get_field_detect_regex, parse_datasheet


def main():
    file_paths = sorted(glob.glob("benchmark/**/llm_*.json", recursive=True))

    num_fields_by_pl = defaultdict(int)
    num_fields_by_pl_sym = defaultdict(lambda: defaultdict(int))

    def count_fields(pl_name, fields):
        if not isinstance(fields, dict):
            fields = dict(zip((f.symbol for f in fields), fields))
        num_fields_by_pl[pl_name] += len(fields)
        for field in fields.values():
            num_fields_by_pl_sym[pl_name][field.symbol] += 1

    uniq = set()

    for file_path in file_paths:
        with open(file_path, "r") as f:
            data = json.load(f)

        pl_name = os.path.basename(file_path)[len('llm_extract_'):].split(".")[0]
        mfr = file_path.split('/')[-3]
        mpn = file_path.split('/')[-2]
        uniq.add((mfr, mpn))
        print(mfr, mpn)

        fields = find_fields_from_json(data, mfr, mpn)
        count_fields(pl_name, fields)

    for mfr, mpn in uniq:
        ds_path = os.path.join('datasheets', mfr, mpn + '.pdf')
        dsp = parse_datasheet(ds_path, mfr=mfr, mpn=mpn)
        count_fields('tabular_parse', dsp)

    all_syms = sorted(set(sum(map(list, num_fields_by_pl_sym.values()), [])))

    num_total_fields = len(all_syms) * len(file_paths)

    print('')
    s = ' '.join(map(lambda t: '%4s' % t, all_syms))
    print('num fields by pipeline from %s datasheets:' % len(uniq))
    print('                           total     ', s)
    for k, v in sorted(num_fields_by_pl.items(), key=lambda t: -t[1]):
        s = ' '.join(['%4.0f' % num_fields_by_pl_sym[k][s] for s in all_syms])
        print('%24s: %4d (%3.0f%%)' % (k, v, 100 * v / max(num_fields_by_pl.values())), s)


def find_fields_from_json(data, mfr, mpn):
    fields_detect = get_field_detect_regex(mfr)

    fields = []

    def _iterate_node(o, name='root'):
        if not isinstance(o, dict):
            return

        name_candidates = [name, o.get('symbol', ''), o.get('parameter', '')]
        for field_sym, field_re in fields_detect.items():
            detect_field = lambda s: (len(str(s)) < 80) and field_re.search(normalize_dash(str(s)).strip(' -'))
            m = next(filter(detect_field, name_candidates), None)
            if m is None:
                continue
            # TODO symbol-aware min/typ/max shift to solve mapping errors
            try:
                f = Field(field_sym, min=o.get('min'), typ=o.get('typ') or o.get('value'), max=o.get('max'),
                          unit=o.get('unit'))
                fields.append(f)
            except Exception as e:
                print(mfr, mpn, 'error parsing field', e, o)
            # print(mfr, mpn, field_sym, o)
            break

        for row_name, row in o.items():
            _iterate_node(row, row_name)

    _iterate_node(data)
    return fields


if __name__ == '__main__':
    main()
