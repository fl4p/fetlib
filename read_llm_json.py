

import glob
import json
import os

from dslib.pdf2txt import normalize_dash
from dslib.pdf2txt.parse import get_field_detect_regex

file_paths = sorted(glob.glob("../fet-datasheets/data/**/*.json", recursive=True))

for file_path in file_paths:
    with open(file_path, "r") as f:
        data = json.load(f)

    mfr = file_path.split('/')[-4]
    mpn = os.path.basename(file_path).split('.')[0]
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
                m = next(filter(detect_field, [row_name, row.get('symbol','')]), None)

                if m:
                    print(mfr, mpn, field_sym, row)
                    break


    #print(file_path, data)