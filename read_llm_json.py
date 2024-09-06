import glob
import json

from dslib.field import Field
from dslib.pdf2txt import normalize_dash
from dslib.pdf2txt.parse import get_field_detect_regex

file_paths = sorted(glob.glob("../fet-datasheets/intermediate/infineon/**/llm_*.json", recursive=True))

for file_path in file_paths:
    with open(file_path, "r") as f:
        data = json.load(f)

    mfr = file_path.split('/')[-3]
    mpn = file_path.split('/')[-2]
    fields_detect = get_field_detect_regex(mfr)

    print(mfr, mpn)

    for sec_name, section in data.items():
        if not isinstance(section, dict):
            continue
        for row_name, row in section.items():
            if not isinstance(row, dict):
                continue
            for field_sym, field_re in fields_detect.items():
                detect_field = lambda s: (len(str(s)) < 80) and field_re.search(normalize_dash(str(s)).strip(' -'))
                name_candidates = [row_name, row.get('symbol', ''), row.get('parameter', '')]
                m = next(filter(detect_field, name_candidates), None)

                if m:
                    # TODO symbol-aware min/typ/max shift to solve mapping errors
                    try:
                        Field(field_sym, min=row.get('min'), typ=row.get('typ'), max=row.get('max'))
                    except Exception as e:
                        print(mfr, mpn, 'error parsing field', e, row)
                    print(mfr, mpn, field_sym, row)
                    break

    # print(file_path, data)
