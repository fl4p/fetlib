import os
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()
import pandas as pd

import digikey
from digikey.v3.productinformation import KeywordSearchRequest

DIGIKEY_STORAGE_PATH = 'digikey_cache_dir'
os.environ['DIGIKEY_CLIENT_SANDBOX'] = 'False'
os.environ['DIGIKEY_STORAGE_PATH'] = DIGIKEY_STORAGE_PATH

def search_digikey_parts(search_params):

    # Prepare the search request
    search_request = KeywordSearchRequest(
        keywords=search_params['keywords'],
        record_count=50,  # Changed to 50 to comply with API limit
        # filters={
        #     'ParametricFilters': [
        #         {
        #             'ParameterId': 'Drain to Source Voltage (Vdss)',
        #             'ValueId': '',
        #             'MinValue': search_params['voltage_min'],
        #             'MaxValue': search_params['voltage_max']
        #         },
        #         {
        #             'ParameterId': 'Current - Continuous Drain (Id) @ 25°C',
        #             'ValueId': '',
        #             'MinValue': search_params['current_min'],
        #             'MaxValue': search_params['current_max']
        #         }
        #     ]
        # }
    )

    # Perform the search
    result = digikey.keyword_search(body=search_request)

    # Process the results
    if result.products:
        data = []
        for product in result.products:
            product_data = {
                'Datasheet': product.primary_datasheet,
                'Image': product.primary_photo,
                'DK Part #': product.digi_key_part_number,
                'Mfr Part #': product.manufacturer_part_number,
                'Mfr': product.manufacturer.value,
                'Description': product.product_description,
                'Stock': product.quantity_available,
                'Price': product.unit_price,
                '@ qty': product.standard_pricing[0].break_quantity if product.standard_pricing else None,
                'Min Qty': product.minimum_order_quantity,
                'Package': next((param.value for param in product.parameters if param.parameter == 'Package / Case'), None),
                'Series': product.series.value if hasattr(product, 'series') else None,
                'Product Status': product.product_status,
                'FET Type': next((param.value for param in product.parameters if param.parameter == 'FET Type'), None),
                'Technology': next((param.value for param in product.parameters if param.parameter == 'Technology'), None),
                'Drain to Source Voltage (Vdss)': next((param.value for param in product.parameters if param.parameter == 'Drain to Source Voltage (Vdss)'), None),
                'Current - Continuous Drain (Id) @ 25°C': next((param.value for param in product.parameters if param.parameter == 'Current - Continuous Drain (Id) @ 25°C'), None),
                'Drive Voltage (Max Rds On, Min Rds On)': next((param.value for param in product.parameters if param.parameter == 'Drive Voltage (Max Rds On, Min Rds On)'), None),
                'Rds On (Max) @ Id, Vgs': next((param.value for param in product.parameters if param.parameter == 'Rds On (Max) @ Id, Vgs'), None),
                'Vgs(th) (Max) @ Id': next((param.value for param in product.parameters if param.parameter == 'Vgs(th) (Max) @ Id'), None),
                'Gate Charge (Qg) (Max) @ Vgs': next((param.value for param in product.parameters if param.parameter == 'Gate Charge (Qg) (Max) @ Vgs'), None),
                'Vgs (Max)': next((param.value for param in product.parameters if param.parameter == 'Vgs (Max)'), None),
                'Input Capacitance (Ciss) (Max) @ Vds': next((param.value for param in product.parameters if param.parameter == 'Input Capacitance (Ciss) (Max) @ Vds'), None),
                'FET Feature': next((param.value for param in product.parameters if param.parameter == 'FET Feature'), None),
                'Power Dissipation (Max)': next((param.value for param in product.parameters if param.parameter == 'Power Dissipation (Max)'), None),
                'Operating Temperature': next((param.value for param in product.parameters if param.parameter == 'Operating Temperature'), None),
                'Mounting Type': next((param.value for param in product.parameters if param.parameter == 'Mounting Type'), None),
                'Supplier Device Package': next((param.value for param in product.parameters if param.parameter == 'Supplier Device Package'), None),
            }
            data.append(product_data)

        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Save to CSV (optional)
        csv_file_path = os.path.join(DIGIKEY_STORAGE_PATH, 'search_results.csv')
        df.to_csv(csv_file_path, index=False)
        print(f'Results written to {csv_file_path}')

        return df
    else:
        print('No products found.')
        return pd.DataFrame()

# Example usage:
# search_params = {
#     'keywords': 'mosfet',
#     'voltage_min': 30,
#     'voltage_max': 100,
#     'current_min': 10,
#     'current_max': 50
# }
# results = search_digikey_parts(search_params)
# print(results)