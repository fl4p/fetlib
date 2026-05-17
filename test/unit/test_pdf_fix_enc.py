"""Tests for dslib.pdf.fix_encoding.has_custom_font_encoding"""

import os
import pathlib

import pytest

from dslib.pdf.fix_encoding import has_custom_font_encoding, fix_pdf_font_encoding

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent

# Sample PDFs with custom font encoding (from docs/vibes/font-replacer.md)
CUSTOM_ENCODING_SAMPLES = [
    "datasheets/huayi/HY3912W.pdf",
    "datasheets/infineon/IPP057N08N3GHKSA1.pdf",
    "datasheets/infineon/BSC190N15NS3_G.pdf",
    "datasheets/huayi/HY1920W.pdf",
    "datasheets/infineon/IPP028N08N3_G.pdf",
    "datasheets/infineon/IPW60R041C6.pdf",
]

# Sample PDFs WITHOUT custom font encoding (negative test cases)
NO_CUSTOM_ENCODING_SAMPLES = [
    "datasheets/huayi/HY0910D.pdf",
]


def _pdf_path(rel_path: str) -> str:
    """Return full path to a PDF relative to repo root."""
    return str(REPO_ROOT / rel_path)


class TestHasCustomFontEncoding:
    """Tests for has_custom_font_encoding function."""

    def test_nonexistent_file_raises(self):
        """has_custom_font_encoding should raise when file doesn't exist."""
        with pytest.raises(Exception):
            has_custom_font_encoding("/nonexistent/path/file.pdf")

    @pytest.mark.parametrize("sample", CUSTOM_ENCODING_SAMPLES)
    def test_custom_encoding_samples_detected(self, sample):
        """PDFs known to have custom encoding should return True."""
        pdf_path = _pdf_path(sample)
        if not os.path.exists(pdf_path):
            pytest.skip(f"Sample PDF not found: {pdf_path}")

        result = has_custom_font_encoding(pdf_path)
        assert result is True, f"Expected {sample} to be detected as having custom encoding"

    @pytest.mark.parametrize("sample", NO_CUSTOM_ENCODING_SAMPLES)
    def test_no_custom_encoding_samples(self, sample):
        """PDFs known to NOT have custom encoding should return False."""
        pdf_path = _pdf_path(sample)
        if not os.path.exists(pdf_path):
            pytest.skip(f"Sample PDF not found: {pdf_path}")

        result = has_custom_font_encoding(pdf_path)
        assert result is False, f"Expected {sample} to NOT be detected as having custom encoding"

    def test_returns_boolean(self):
        """Function should always return a boolean value."""
        # Test with any existing PDF
        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                result = has_custom_font_encoding(pdf_path)
                assert isinstance(result, bool)
                break
        else:
            pytest.skip("No sample PDFs available for testing")

    def test_multiple_calls_consistent(self):
        """Multiple calls on the same file should return consistent results."""
        for sample in CUSTOM_ENCODING_SAMPLES[:3]:  # Test first 3 samples
            pdf_path = _pdf_path(sample)
            if not os.path.exists(pdf_path):
                continue

            results = [has_custom_font_encoding(pdf_path) for _ in range(3)]
            assert all(r == results[0] for r in results), \
                f"Inconsistent results for {sample}"


class TestFixPdfFontEncoding:
    """Tests for fix_pdf_font_encoding function."""

    def test_fix_creates_output_file(self, tmp_path):
        """Fixing a PDF with custom encoding should create an output file."""
        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                out_path = str(tmp_path / "fixed.pdf")
                result = fix_pdf_font_encoding(pdf_path, out_path=out_path)
                assert os.path.exists(out_path), "Output file should be created"
                assert result == out_path
                return
        pytest.skip("No sample PDFs with custom encoding available")

    def test_fix_default_output_path_naming(self, tmp_path):
        """Default output path should be <input>.unicoded.pdf."""
        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                # Copy to tmp_path to control output location
                import shutil
                src = tmp_path / "test.pdf"
                shutil.copy(pdf_path, src)
                result = fix_pdf_font_encoding(str(src))
                expected = str(tmp_path / "test.unicoded.pdf")
                # If fix was applied, result should be the .unicoded path
                # If no fixable fonts, result is original path
                if result != str(src):
                    assert result == expected
                return
        pytest.skip("No sample PDFs with custom encoding available")

    def test_fix_no_custom_encoding_returns_original(self, tmp_path):
        """PDF without custom encoding should return original path unchanged."""
        for sample in NO_CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                result = fix_pdf_font_encoding(pdf_path)
                assert result == pdf_path, "Should return original path when no fix needed"
                return
        pytest.skip("No negative sample PDFs available")

    def test_fix_raise_if_no_bad_fonts(self, tmp_path):
        """raise_if_no_bad_fonts=True should raise ValueError when no bad fonts."""
        for sample in NO_CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                with pytest.raises(ValueError, match="no bad fonts"):
                    fix_pdf_font_encoding(pdf_path, raise_if_no_bad_fonts=True)
                return
        pytest.skip("No negative sample PDFs available")

    def test_fix_output_is_valid_pdf(self, tmp_path):
        """Fixed output should be a valid readable PDF."""
        import pymupdf

        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                out_path = str(tmp_path / "fixed.pdf")
                fix_pdf_font_encoding(pdf_path, out_path=out_path)

                # Should be able to open and read the fixed PDF
                doc = pymupdf.open(out_path)
                assert len(doc) > 0, "Fixed PDF should have at least one page"
                # Try to extract text from first page
                text = doc[0].get_text()
                assert isinstance(text, str)
                doc.close()
                return
        pytest.skip("No sample PDFs with custom encoding available")

    def test_fix_min_similarity_parameter(self, tmp_path):
        """min_similarity parameter should affect the fix process."""
        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                # Test with different similarity thresholds
                out_low = str(tmp_path / "fixed_low.pdf")
                out_high = str(tmp_path / "fixed_high.pdf")

                fix_pdf_font_encoding(pdf_path, out_path=out_low, min_similarity=0.1)
                fix_pdf_font_encoding(pdf_path, out_path=out_high, min_similarity=0.9)

                # Both should create output files
                assert os.path.exists(out_low)
                assert os.path.exists(out_high)
                return
        pytest.skip("No sample PDFs available")

    def test_fix_preserves_page_count(self, tmp_path):
        """Fixed PDF should have same number of pages as original."""
        import pymupdf

        for sample in CUSTOM_ENCODING_SAMPLES:
            pdf_path = _pdf_path(sample)
            if os.path.exists(pdf_path):
                orig_doc = pymupdf.open(pdf_path)
                orig_pages = len(orig_doc)
                orig_doc.close()

                out_path = str(tmp_path / "fixed.pdf")
                fix_pdf_font_encoding(pdf_path, out_path=out_path)

                fixed_doc = pymupdf.open(out_path)
                fixed_pages = len(fixed_doc)
                fixed_doc.close()

                assert fixed_pages == orig_pages, \
                    f"Page count mismatch: original={orig_pages}, fixed={fixed_pages}"
                return
        pytest.skip("No sample PDFs available")
