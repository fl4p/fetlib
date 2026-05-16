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
from viz.curve_extract import find_in_pdf, find_plateau, find_vpl
from viz.chart_finder import ChartLocation, find_gate_charge_charts


__all__ = [
    'find_vpl',
    'find_in_pdf',
    'find_plateau',
    'find_gate_charge_charts',
    'ChartLocation',
]
