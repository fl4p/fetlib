"""
pip install digikey-api

cache_dir="path/to/cache/dir"
mkdir -p $cache_dir

export DIGIKEY_CLIENT_ID="client_id"
export DIGIKEY_CLIENT_SECRET="client_secret"
export DIGIKEY_STORAGE_PATH="${cache_dir}"

"""


# TODO this doesnt work
# use nexar
# https://portal.nexar.com/playground/4742444c-8330-48e3-9a72-3f8f0cb5db77


#"tbGNCaPtiWbd5WoL24vrEAUuW9SdJrLE"
#"nEDqljvrXf5hqV28"

import os
import pathlib
from pathlib import Path

import digikey
from digikey.v4.productinformation import KeywordRequest, ProductDetails, ProductVariation
from digikey.v4.batchproductdetails import BatchProductDetailsRequest


os.environ['DIGIKEY_CLIENT_ID'] = "tbGNCaPtiWbd5WoL24vrEAUuW9SdJrLE"
os.environ['DIGIKEY_CLIENT_SECRET'] = 'nEDqljvrXf5hqV28'
os.environ['DIGIKEY_CLIENT_SANDBOX'] = 'False'
os.environ['DIGIKEY_STORAGE_PATH'] = "dk-cache"


pathlib.Path(os.environ['DIGIKEY_STORAGE_PATH']).mkdir(exist_ok=True)

# Query product number
dkpn = 'SQM70060EL_GE3TR-ND'
part = digikey.product_details(dkpn)

digikey.digi_reel_pricing()

# Search for parts
search_request = KeywordRequest(keywords='SQM70060EL_GE3', limit=10)
result = digikey.keyword_search(body=search_request)

def get_cheapeast_pricing(part:ProductDetails):
    pv:ProductVariation
    for pv in part.product.product_variations:
        pv.standard_pricing[0]

#digikey.

print(result)

# Only if BatchProductDetails endpoint is explicitly enabled
# Search for Batch of Parts/Product
#mpn_list = ["0ZCK0050FF2E", "LR1F1K0"] #Length upto 50
#batch_request = BatchProductDetailsRequest(products=mpn_list)
#part_results = digikey.batch_product_details(body=batch_request)