"""Run maglib's vendor-traceable reference values as part of the routine suite.

``maglib/tests.py`` holds roughly forty hand-checked numbers taken from
manufacturer documents -- Magnetics' powder-core catalogue (with page
references), Micrometals datasheets, and the Micrometals AC-resistance
application note. They are the same kind of asset as ``test_v2_pdf_parse.py``'s
65 reference values: the only thing in the project that can say a physical
model is RIGHT rather than merely unchanged.

They were not running. The documented suite is ``pytest test/unit`` and
``pytest test/tests.py``; ``maglib/tests.py`` sits outside both, so nothing
collected it, and it had rotted:

  * the Micrometals app-note assertion compared the note's TOTAL Rac/Rdc ratio
    against the model's EXCESS factors, failing by exactly the missing DC term
    of 1.0 -- while the model itself reproduces the note to 1.7e-5;
  * ``acr_factor_micrometals()`` was called with no arguments at all, which
    raises TypeError;
  * the two-model cross-check asked for 8 points outside
    ``ac_resistance_factor``'s stated domain (sd/diameter < 0.3), so it died on
    that assert before comparing anything.

A test file that cannot run cannot regress, which is why all three survived.
Importing the functions here collects them wherever ``test/unit`` runs; the
values stay in maglib next to the code they describe rather than being copied,
because a duplicated reference set is one that drifts.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

# Imported for collection by pytest -- each is a real test function.
from maglib.tests import (test_bpk_sinusoidal,  # noqa: F401,E402
                          test_ks184_125a_dc_bias_against_flu_bench,  # noqa: F401,E402
                          test_ks184_125a_reproduces_its_own_datasheet_dc_bias_point,  # noqa: F401,E402
                          test_coil,  # noqa: F401,E402
                          test_copper_resistivity_tempco,  # noqa: F401,E402
                          test_dc_bias_suppression_is_not_silent,  # noqa: F401,E402
                          test_femmt_acr_result_conventions,  # noqa: F401,E402
                          test_femmt_config_golden,  # noqa: F401,E402
                          test_femmt_tool_paths_missing,  # noqa: F401,E402
                          test_femmt_toroid_fem,  # noqa: F401,E402
                          test_mat,   # noqa: F401,E402
                          test_micrometals_per_part_coefficients,  # noqa: F401,E402
                          test_micrometals_size_dependent_coefficients,  # noqa: F401,E402
                          test_micrometals_toroid_shapes,  # noqa: F401,E402
                          test_power_loss,  # noqa: F401,E402
                          test_toroid_column_geometry,  # noqa: F401,E402
                          test_toroid_packing,  # noqa: F401,E402
                          test_unusable_material_raises,  # noqa: F401,E402
                          test_winding_bore,  # noqa: F401,E402
                          test_winding_fit,  # noqa: F401,E402
                          test_wound_pass_count_is_not_monotone_in_turns,  # noqa: F401,E402
                          test_wire)  # noqa: F401,E402
