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


def find_vpl_package_results(pdf_path: str):
    """Every digitized gate-charge panel, including the ones that were REFUSED.

    `find_vpl_package_result` serves only `status == 'ok'` and returns None otherwise,
    which collapses two states a caller must tell apart: "no gate-charge chart here" and
    "a chart was read and the digitizer rejected what it got". They deserve opposite
    treatment -- the first may reasonably try another estimator, the second must not,
    because retrying after a refusal launders a rejected reading into an unvetted one.
    """

    from datasheet_chart_digitizer.gate_charge import digitize_gate_charge

    return list(digitize_gate_charge(pdf_path))


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


def _compute_chart_digitizer_sig():
    """Content hash of the EXTERNAL code that derives Vpl from a chart.

    Vpl is not parsed out of the text layer -- `read_charts` hands the PDF to
    datasheet-chart-digitizer, which finds the gate-charge panel, traces the curve and
    calibrates it against an axis it detects itself. That package is therefore part of
    the parse derivation, and until this existed NO key on dslib covered it:
    `legacy_parse_code_salt` hashes files under the dslib package directory only, so a
    digitizer fix could not invalidate a single cached parse. The cached Vpl simply
    stayed wrong, indefinitely, looking exactly like a fix that did not work.

    Demonstrated: the 2026-07-27 neighbour-column fix (a gate chart calibrated against
    the y-axis of the chart NEXT to it, EPC2934C reading 4.97 V for a 2.15 V plateau)
    changed nothing for any part until this salt moved.

    CONTENT hash, not the version. The package is an editable install pinned at 0.1.0,
    so a version-based salt records the same constant on every run forever -- an inert
    component that looks present, which is the failure mode `field_repr_salt` documents
    for unidecode.

    An absent package returns the explicit 'absent' generation, NOT a placeholder that
    reads like a hash. The two states produce genuinely different parses -- without the
    digitizer no Vpl is read at all -- so they belong under different keys, and this
    module must stay importable without it (see the guarded import at the top: the
    parts-DB-only tools run in a venv with no pymupdf). Absence is recorded, never
    silently equated with any digitizer generation.

    Scope is the whole package plus this wrapper (which chooses the package path over
    the legacy one, i.e. which digitizer runs at all). Deliberately over-broad: a
    capacitance-only edit will invalidate Vpl parses that could not have changed. That
    costs ~8.6 s/part with warm sub-caches -- measured, ~2 h across the corpus in
    parallel -- and the alternative is choosing per-module what "can change the numbers",
    which is the judgement call that leaves the silent-staleness hole open again.
    """
    import hashlib
    import os

    from dslib.cache import _file_content_sig

    try:
        import datasheet_chart_digitizer as _pkg
    except ImportError:
        return 'chart-digitizer:absent'
    pkg_dir = os.path.dirname(os.path.abspath(_pkg.__file__))

    h = hashlib.sha256()
    for rel in sorted(os.listdir(pkg_dir)):
        if rel.endswith('.py'):
            h.update(_file_content_sig(os.path.join(pkg_dir, rel)).encode())
    h.update(_file_content_sig(os.path.abspath(__file__)).encode())
    return 'chart-digitizer:' + h.hexdigest()[:16]


# Snapshotted at import, like legacy_parse_code_salt and for the same reason: a
# long-lived process still running the OLD digitizer must not observe a concurrent
# on-disk edit and write its old results under the new generation's key.
_CHART_DIGITIZER_SIG = _compute_chart_digitizer_sig()


def chart_digitizer_salt():
    """The digitizer generation this process imported. See _compute_chart_digitizer_sig."""
    return _CHART_DIGITIZER_SIG


__all__ = [
    'find_vpl',
    'find_vpl_package_result',
    'chart_digitizer_salt',
    'find_in_pdf',
    'find_plateau',
    'find_gate_charge_charts',
    'ChartLocation',
    'build_card',
    'audit',
    'render_html',
]
