from pathlib import Path

from dslib.pdf.parse import _chart_source_pdf


def test_chart_source_pdf_prefers_existing_pristine_pdf(tmp_path: Path):
    original = tmp_path / "part.pdf"
    repaired = tmp_path / "part.pdf.r600_ocrmypdf.pdf"
    original.touch()
    repaired.touch()

    assert _chart_source_pdf(repaired) == str(original)


def test_chart_source_pdf_keeps_derivative_without_pristine_pdf(tmp_path: Path):
    repaired = tmp_path / "part.pdf.r600_ocrmypdf.pdf"
    repaired.touch()

    assert _chart_source_pdf(repaired) == str(repaired)
