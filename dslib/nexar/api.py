"""Sample request for extracting GraphQL part data."""
import argparse
import json
import os.path

import requests
import pyperclip

from dslib import mfr_tag
from dslib.cache import disk_cache

NEXAR_URL = "https://api.nexar.com/graphql"
QUERY_MPN = """query ($mpn: String!) {
      supSearchMpn(q: $mpn) {
        results {
          part {
            category {
              parentId
              id
              name
              path
            }
            mpn
            manufacturer {
              name
            }
            shortDescription
            descriptions {
              text
              creditString
            }
            specs {
              attribute {
                name
                shortname
              }
              displayValue
            }
          }
        }
      }
    }
"""

def get_part_info_from_mpn(variables, token) -> dict:
    """Return Nexar response for the given mpn."""
    try:
        r = requests.post(
            NEXAR_URL,
            json={"query": QUERY_MPN, "variables": variables},
            headers={"token": token},
        )

        obj = json.loads(r.text)
        if obj.get('errors'):
            raise Exception(obj.get('errors'))

        data = obj["data"]["supSearchMpn"]
    except Exception:
        raise Exception("Error while getting Nexar response")
    return data


def read_token():
    with open(os.path.dirname(__file__) + "/.token", "r") as f:
        return f.read().strip()

@disk_cache(ttl='7d')
def get_part_specs(mpn, mfr):
    token = read_token()  # pyperclip.paste() or
    variables = {"mpn": mpn}
    response = get_part_info_from_mpn(variables, token)


    if not response['results']:
        print(mfr, mpn, 'no nexar results')
        return None

    for r in response['results']:
        p = r['part']
        if mfr_tag(p['manufacturer']['name']) == mfr_tag(mfr):
            if len(p['specs']) == 0:
                print(mfr, mpn, 'empty specs')
                continue
            return {s['attribute']['shortname']: s['displayValue'] for s in p['specs']}

def get_part_specs_cached(mpn, mfr):
    dn = os.path.join('data', 'nexar-specs', mfr)
    fn = os.path.join(dn, mpn + '.json')
    os.path.isdir(dn) or os.makedirs(dn)
    if os.path.exists(fn):
        with open(fn, 'r') as f:
            return json.load(f)

    specs = get_part_specs(mpn, mfr=mfr)

    if not specs:
        print(mfr, mpn, 'no specs found')
        # return

    with open(fn, 'w') as f:
        json.dump(specs, f)
    return specs

    # print(mfr, mpn, 'no mfr match!')

if __name__ == '__main__':
    specs = get_part_specs('TK46E08N1,S1X', 'toshiba')

    print(specs)

    parser = argparse.ArgumentParser()
    parser.add_argument("mpn", help="The mpn for the part request.", type=str)
    args = parser.parse_args()



    token = read_token() # pyperclip.paste() or
    variables = {"mpn": args.mpn}
    response = get_part_info_from_mpn(variables, token)
    print(json.dumps(response, indent = 1))