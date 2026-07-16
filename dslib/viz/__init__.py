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
try:
    # Optional heavy PDF-extraction stack (needs pymupdf). Guarded so the
    # lightweight, parts-DB-only tools below (fidelity_card) stay importable in
    # the canonical loss/parts venv where pymupdf isn't installed.
    from dslib.viz.curve_extract import (
        find_in_pdf,
        find_plateau,
        find_vpl as _find_vpl_legacy,
    )
    from dslib.viz.chart_finder import ChartLocation, find_gate_charge_charts
except ImportError as _pdf_err:  # pragma: no cover - env-dependent
    _PDF_IMPORT_ERROR = _pdf_err

    def _pdf_stack_missing(*_a, **_k):
        raise ImportError(
            "dslib.viz PDF-chart extraction requires optional deps "
            f"(pymupdf): {_PDF_IMPORT_ERROR}")

    find_in_pdf = find_plateau = _find_vpl_legacy = _pdf_stack_missing
    find_gate_charge_charts = _pdf_stack_missing
    ChartLocation = None


def __getattr__(name):  # PEP 562: lazy re-export of the parts-DB fidelity tools.
    # Deferred so `python -m dslib.viz.fidelity_card` doesn't eager-import the
    # __main__ target (RuntimeWarning) and so plain `import dslib.viz` stays cheap.
    if name in ("build_card", "audit", "render_html"):
        from dslib.viz import fidelity_card
        return getattr(fidelity_card, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def find_vpl_package_result(pdf_path: str):
    """Return the package-owned Vpl result with diagnostics."""

    from datasheet_chart_digitizer.gate_charge import find_vpl_result

    return find_vpl_result(pdf_path)


def find_vpl(
    pdf_path: str,
    enable_raster: bool = True,
    enable_ocr: bool = False,
):
    """Return package-native Vpl while preserving explicit legacy controls.

    The default argument combination uses the accepted package-native scalar.
    Non-default raster/OCR controls retain their historical legacy behavior.
    Use :func:`find_vpl_package_result` when status and diagnostics are needed.
    """

    if not enable_raster or enable_ocr:
        return _find_vpl_legacy(
            pdf_path,
            enable_raster=enable_raster,
            enable_ocr=enable_ocr,
        )
    result = find_vpl_package_result(pdf_path)
    return None if result is None else result.vpl


__all__ = [
    'find_vpl',
    'find_vpl_package_result',
    'find_in_pdf',
    'find_plateau',
    'find_gate_charge_charts',
    'ChartLocation',
    'build_card',
    'audit',
    'render_html',
]
