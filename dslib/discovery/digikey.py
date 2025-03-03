import glob
import math

import pandas as pd

from dslib import mfr_tag
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart
from dslib.field import parse_field_value


def digikey(csv_glob_path, no_obsolete=False):
    df = pd.concat([pd.read_csv(fn) for fn in sorted(glob.glob(csv_glob_path))], axis=0, ignore_index=True)

    parts = []

    for i, row in df.iterrows():
        if no_obsolete and row['Product Status'] == 'Obsolete':
            continue

        mfr = mfr_tag(row.Mfr)
        mpn = str(row['Mfr Part #'])
        ds_url = row.Datasheet
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=float(row['Drain to Source Voltage (Vdss)'].strip(' V')),
            Rds_on_10v_max=(row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip()),
            Qg_max=(row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip()),
            Qg_typ=math.nan,
            ID_25=float(
                row['Current - Continuous Drain (Id) @ 25°C'].strip(' ,').split(',')[-1].strip().split(' ')[0].strip(
                    ' A')),
            Vgs_th_min=math.nan,
            Vgs_th_typ=math.nan,
            Vgs_th_max=parse_field_value(row['Vgs(th) (Max) @ Id'].split('@')[0].strip(' V')),
            source=['digikey'],
        ), package=row['Package / Case']))

    return parts
