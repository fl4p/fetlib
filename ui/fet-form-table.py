import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PYTHONPATH'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import pickle
from dslib.spec_models import DcDcSpecs, MosfetSpecs
from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from dslib.store import load_parts as _load_parts
from dslib.digikey.partsSearch import search_digikey_parts
from dslib.parts_discovery import digikey

@st.cache_resource
def load_parts():
    return _load_parts()


@st.cache_data
def fetch_digikey_parts(search_params):
    """
    Fetch MOSFET parts from DigiKey API based on search parameters.
    
    :param search_params: Dictionary containing search parameters
    :return: DataFrame of DigiKey part results
    """
    return search_digikey_parts(search_params)

@st.cache_data
def process_csv_data(csv_file):
    """
    Process uploaded CSV file containing MOSFET data.
    
    :param csv_file: Uploaded CSV file
    :return: Processed DataFrame
    """
    df = pd.read_csv(csv_file)
    # Add any necessary processing steps here
    return df

def combine_mosfet_data(api_data, csv_data):
    """
    Combine MOSFET data from DigiKey API and uploaded CSV.
    
    :param api_data: List of DigiKey part results
    :param csv_data: DataFrame of CSV data
    :return: Combined DataFrame of MOSFET data
    """
    # Convert api_data to DataFrame if it's not already
    if not isinstance(api_data, pd.DataFrame):
        api_df = pd.DataFrame(api_data)
    else:
        api_df = api_data
    
    # Combine the DataFrames
    combined_df = pd.concat([api_df, csv_data], ignore_index=True)
    
    # Remove duplicates if any
    combined_df.drop_duplicates(subset=['Mfr Part #'], keep='first', inplace=True)
    
    return combined_df

@st.cache_data
def analyze_mosfets(_dcdc_specs, mosfet_data):
    """
    Perform MOSFET analysis based on DC-DC converter specifications and MOSFET data.
    
    :param _dcdc_specs: DcDcSpecs object containing converter specifications
    :param mosfet_data: DataFrame containing MOSFET data
    :return: DataFrame with analysis results
    """
    results = []
    for _, row in mosfet_data.iterrows():
        part = digikey([row])  # Assuming digikey function can handle a single row
        if part:
            part = part[0]  # digikey function returns a list, we take the first item
            hs_loss = dcdc_buck_hs(_dcdc_specs, part.specs, rg_total=6)
            ls_loss = dcdc_buck_ls(_dcdc_specs, part.specs)
            results.append({
                "Part Number": part.mpn,
                "Manufacturer": part.mfr,
                "VDS (V)": part.specs.Vds_max,
                "ID (A)": part.specs.ID_25,
                "RDS(on) (mΩ)": part.specs.Rds_on * 1000,
                "Qg (nC)": part.specs.Qg * 1e9,
                "Qrr (nC)": part.specs.Qrr * 1e9,
                "tRise (ns)": part.specs.tRise * 1e9,
                "tFall (ns)": part.specs.tFall * 1e9,
                "FOM": part.specs.Rds_on * part.specs.Qg * 1e9,
                "FOMrr": part.specs.Rds_on * part.specs.Qrr * 1e9,
                "P_on (W)": hs_loss.P_on,
                "P_sw (W)": hs_loss.P_sw,
                "P_rr (W)": ls_loss.P_rr,
                "Total Loss (W)": hs_loss.buck_hs() + ls_loss.buck_ls()
            })
    return pd.DataFrame(results)

# Set page config to dark mode
st.set_page_config(page_title="MOSFET Component Selector", layout="wide", initial_sidebar_state="expanded")

# Function to save user inputs
def save_inputs(inputs):
    with open('user_inputs.pkl', 'wb') as f:
        pickle.dump(inputs, f)

# Function to load user inputs
def load_inputs():
    if os.path.exists('user_inputs.pkl'):
        with open('user_inputs.pkl', 'rb') as f:
            return pickle.load(f)
    return {}

# Load previous inputs
previous_inputs = load_inputs()

st.title('MOSFET Component Selector for a DC-DC Converter')

# Sidebar for user input
st.sidebar.header('Input Parameters')
st.sidebar.write('Please enter the DC-DC operating point parameters below:')

vi = st.sidebar.number_input('Input Voltage (V)', min_value=0.0, step=0.1, value=previous_inputs.get('vi', 12.0), help="DC-DC converter input voltage")
vo = st.sidebar.number_input('Output Voltage (V)', min_value=0.0, step=0.1, value=previous_inputs.get('vo', 5.0), help="DC-DC converter output voltage")
pin = st.sidebar.number_input('Input Power (W)', min_value=0.0, step=0.1, value=previous_inputs.get('pin', 50.0), help="Input power of the DC-DC converter")
f = st.sidebar.number_input('Switching Frequency (Hz)', min_value=0.0, step=1000.0, value=previous_inputs.get('f', 100000.0), help="Switching frequency of the DC-DC converter")
vgs = st.sidebar.number_input('Gate Drive Voltage (V)', min_value=0.0, step=0.1, value=previous_inputs.get('vgs', 10.0), help="Gate drive voltage for both (HS) high-side and (LS) low-side MOSFETs")
ripple_factor = st.sidebar.number_input('Ripple Factor', min_value=0.0, max_value=1.0, step=0.01, value=previous_inputs.get('ripple_factor', 0.2), help="Peak-to-peak coil current divided by mean coil current (assuming Continuous Conduction Mode)")
tDead = st.sidebar.number_input('Dead Time (s)', min_value=0.0, step=1e-9, format="%.9f", value=previous_inputs.get('tDead', 1e-9), help="Gate driver dead-time (occurs twice per switching period)")

# Save inputs button
if st.sidebar.button('Save Inputs'):
    inputs = {'vi': vi, 'vo': vo, 'pin': pin, 'f': f, 'vgs': vgs, 'ripple_factor': ripple_factor, 'tDead': tDead}
    save_inputs(inputs)
    st.sidebar.success('Inputs saved successfully!')

# Clear inputs button
if st.sidebar.button('Clear Saved Inputs'):
    if os.path.exists('user_inputs.pkl'):
        os.remove('user_inputs.pkl')
        st.sidebar.success('Saved inputs cleared!')
    else:
        st.sidebar.info('No saved inputs to clear.')

# Function to perform MOSFET analysis
@st.cache_data
def analyze_mosfets(_dcdc_specs):
    parts = load_parts()
    results = []
    for part in parts:
        hs_loss = dcdc_buck_hs(_dcdc_specs, part.specs, rg_total=6)
        ls_loss = dcdc_buck_ls(_dcdc_specs, part.specs)
        results.append({
            "Part Number": part.mpn,
            "Manufacturer": part.mfr,
            "VDS (V)": part.specs.Vds_max,
            "ID (A)": part.specs.ID_25,
            "RDS(on) (mΩ)": part.specs.Rds_on * 1000,
            "Qg (nC)": part.specs.Qg * 1e9,
            "Qrr (nC)": part.specs.Qrr * 1e9,
            "tRise (ns)": part.specs.tRise * 1e9,
            "tFall (ns)": part.specs.tFall * 1e9,
            "FOM": part.specs.Rds_on * part.specs.Qg * 1e9,
            "FOMrr": part.specs.Rds_on * part.specs.Qrr * 1e9,
            "P_on (W)": hs_loss.P_on,
            "P_sw (W)": hs_loss.P_sw,
            "P_rr (W)": ls_loss.P_rr,
            "Total Loss (W)": hs_loss.buck_hs() + ls_loss.buck_ls()
        })
    return pd.DataFrame(results)

# Add file uploader for CSV
uploaded_file = st.sidebar.file_uploader("Upload CSV file with MOSFET data", type="csv")

if st.sidebar.button('Find Components'):
    with st.spinner('Fetching and Analyzing MOSFETs...'):
        try:
            # Fetch DigiKey parts
            search_params = {
                "keywords": "mosfet",
                "voltage_min": vi,
                "voltage_max": vi * 1.5,  # Adjust as needed
                "current_min": pin / vo,
                "current_max": (pin / vo) * 1.5  # Adjust as needed
            }
            digikey_parts = fetch_digikey_parts(search_params)
            
            # Process uploaded CSV if available
            csv_data = pd.DataFrame()
            if uploaded_file is not None:
                csv_data = process_csv_data(uploaded_file)
            
            # Combine data
            combined_data = combine_mosfet_data(digikey_parts, csv_data)
            
            # Perform analysis
            _dcdc_specs = DcDcSpecs(vi=vi, vo=vo, pin=pin, f=f, Vgs=vgs, ripple_factor=ripple_factor, tDead=tDead)
            df = analyze_mosfets(_dcdc_specs, combined_data)
            
            # Sort the dataframe by Total Loss
            df = df.sort_values('Total Loss (W)')
            
            # Function to color code cells
            def color_cells(val, column):
                if column in ['FOM', 'FOMrr', 'P_on (W)', 'P_sw (W)', 'P_rr (W)', 'Total Loss (W)']:
                    if val <= df[column].quantile(0.25):
                        return 'background-color: #92D050; color: black;'
                    elif val <= df[column].quantile(0.75):
                        return 'background-color: #FFFF00; color: black;'
                    else:
                        return 'background-color: #FF0000; color: black;'
                return ''

            # Apply color coding
            styled_df = df.style.apply(lambda x: [color_cells(x[col], col) for col in df.columns], axis=1)

            # Display the table with full width
            st.subheader('MOSFET Analysis Results')
            st.dataframe(styled_df, use_container_width=True)

            # Add download button for CSV
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download results as CSV",
                data=csv,
                file_name="mosfet_analysis_results.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.error(f"An error occurred during analysis: {str(e)}")

st.write("""
Finding the right switches for your DC-DC converter can be more complex than it initially appears. 
The two switches in a converter operate under different conditions, and factors like reverse recovery loss 
are often overlooked.
""")
st.write("""
This tool aims to assist you in making an informed selection by considering these 
crucial aspects and providing a comprehensive comparison of MOSFET options.
""")

# Add a brief tutorial or guide for first-time users
with st.expander("How to use this tool"):
    st.write("""
    Welcome to the MOSFET Component Selector for DC-DC Converters! Here's a quick guide to get you started:

    1. Enter Parameters: Use the sidebar on the left to input your DC-DC converter parameters.
       - Input Voltage (V): The input voltage of your DC-DC converter.
       - Output Voltage (V): The desired output voltage.
       - Input Power (W): The input power of your converter.
       - Switching Frequency (Hz): The switching frequency of your converter.
       - Gate Drive Voltage (V): The gate drive voltage for both high-side and low-side MOSFETs.
       - Ripple Factor: The peak-to-peak coil current divided by mean coil current.
       - Dead Time (s): The gate driver dead-time.

    2. Find Components: Click the 'Find Components' button to analyze suitable MOSFETs based on your inputs.

    3. View Results: The results table will show various MOSFET options with their specifications and estimated power losses.
       - You can sort the table by clicking on column headers.
       - Color coding helps identify better performing MOSFETs (green is better, red is worse).

    4. Download Results: Use the 'Download results as CSV' button to save the analysis for further review.

    5. Save Inputs: You can save your inputs for future sessions using the 'Save Inputs' button in the sidebar.

    6. Clear Inputs: To start fresh, use the 'Clear Saved Inputs' button in the sidebar.

    Remember, finding the right switches for your DC-DC converter involves considering various factors. This tool aims to assist you in making an informed selection by providing a comprehensive comparison of MOSFET options.
    """)

# Add tooltips for headers
st.markdown("""
<style>
    [data-testid="stMetricLabel"] {
        overflow: visible;
    }
    [data-testid="stMetricLabel"]::after {
        content: attr(title);
        visibility: hidden;
        position: absolute;
        padding: 5px;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        background-color: rgba(0,0,0,0.8);
        color: white;
        border-radius: 5px;
        white-space: nowrap;
        z-index: 1;
    }
    [data-testid="stMetricLabel"]:hover::after {
        visibility: visible;
    }
</style>
""", unsafe_allow_html=True)
