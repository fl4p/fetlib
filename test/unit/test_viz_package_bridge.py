import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

from dslib.viz import find_vpl, find_vpl_package_result


class VizPackageBridgeTests(unittest.TestCase):
    def test_package_find_vpl_is_the_default_scalar(self):
        package_result = SimpleNamespace(vpl=4.25)
        with (
            mock.patch(
                "dslib.viz.find_vpl_package_result",
                return_value=package_result,
            ) as package,
            mock.patch("dslib.viz._find_vpl_legacy") as legacy,
        ):
            result = find_vpl("sample.pdf")

        self.assertEqual(result, 4.25)
        package.assert_called_once_with("sample.pdf")
        legacy.assert_not_called()

    def test_package_find_vpl_returns_none_without_a_result(self):
        with mock.patch("dslib.viz.find_vpl_package_result", return_value=None):
            self.assertIsNone(find_vpl("sample.pdf"))

    def test_nondefault_extraction_controls_delegate_to_legacy(self):
        cases = (
            {"enable_raster": False, "enable_ocr": False},
            {"enable_raster": True, "enable_ocr": True},
        )
        for kwargs in cases:
            with self.subTest(**kwargs), mock.patch(
                "dslib.viz._find_vpl_legacy",
                return_value=3.5,
            ) as legacy:
                self.assertEqual(find_vpl("sample.pdf", **kwargs), 3.5)
                legacy.assert_called_once_with("sample.pdf", **kwargs)

    def test_package_bridge_returns_the_full_result(self):
        sentinel = object()
        calls = []
        package = ModuleType("datasheet_chart_digitizer")
        package.__path__ = []
        gate_charge = ModuleType("datasheet_chart_digitizer.gate_charge")

        def fake_find_vpl_result(pdf_path):
            calls.append(pdf_path)
            return sentinel

        gate_charge.find_vpl_result = fake_find_vpl_result
        modules = {
            "datasheet_chart_digitizer": package,
            "datasheet_chart_digitizer.gate_charge": gate_charge,
        }
        with mock.patch.dict(sys.modules, modules):
            result = find_vpl_package_result("sample.pdf")

        self.assertIs(result, sentinel)
        self.assertEqual(calls, ["sample.pdf"])
