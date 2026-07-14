"""
viz — vector-PDF chart extraction.

Currently focused on locating the *gate-charge characteristic* chart in a
MOSFET datasheet and reading the Miller plateau voltage (V_pl) off the
plateau of the V_GS(Q_G) curve.

Quick start::

    from viz import find_vpl
    v = find_vpl('datasheets/onsemi/FDD86367.pdf')
    print(v)  # ≈ 5.0
"""
from dslib.viz.curve_extract import find_in_pdf, find_plateau, find_vpl
from dslib.viz.chart_finder import ChartLocation, find_gate_charge_charts


def find_vpl_package_result(pdf_path: str):
    """Return the package-owned experimental Vpl result with diagnostics.

    ``dslib.viz.find_vpl`` remains the compatibility default until the
    package-native numeric corpus reaches parity with it.
    """

    from datasheet_chart_digitizer.gate_charge import find_vpl_result

    return find_vpl_result(pdf_path)


__all__ = [
    'find_vpl',
    'find_vpl_package_result',
    'find_in_pdf',
    'find_plateau',
    'find_gate_charge_charts',
    'ChartLocation',
]
