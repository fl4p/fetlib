import sys
import unittest
from types import ModuleType
from unittest import mock

from dslib.viz import find_vpl, find_vpl_package_result
from dslib.viz.curve_extract import find_vpl as legacy_find_vpl


class VizPackageBridgeTests(unittest.TestCase):
    def test_legacy_find_vpl_remains_the_default(self):
        self.assertIs(find_vpl, legacy_find_vpl)

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
