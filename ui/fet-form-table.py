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

@st.cache_resource
def load_parts():
    return _load_parts()

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

if st.sidebar.button('Find Components'):
    with st.spinner('Analyzing MOSFETs...'):
        try:
            _dcdc_specs = DcDcSpecs(vi=vi, vo=vo, pin=pin, f=f, Vgs=vgs, ripple_factor=ripple_factor, tDead=tDead)
            df = analyze_mosfets(_dcdc_specs)
            
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
    1. Enter the DC-DC converter parameters in the sidebar.
    2. Click 'Find Components' to analyze suitable MOSFETs.
    3. The results table shows various MOSFET options with their specifications and estimated power losses.
    4. You can sort the table by clicking on column headers.
    5. Color coding helps identify better performing MOSFETs (green is better, red is worse).
    6. Use the download button to save results as a CSV file for further analysis.
    7. You can save your inputs for future sessions using the 'Save Inputs' button.
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
