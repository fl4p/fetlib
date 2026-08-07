"""
A/B: FEM (femmt proxy) vs analytic (Micrometals app-note) AC resistance of a
toroid winding — the T184 sendust case from the 2026-08 strand-count study.

Run from repo root: python -m maglib.examples.femmt_toroid_acr
First run simulates 4 FEM configs (~minutes); repeats are cache hits.
"""
from maglib.cores import MicrometalsT184
from maglib.fem import femmt_toroid_acr
from maglib.wire import MaterialResistivity, acr_factor_micrometals

CORE_ID = MicrometalsT184.ID
WIRE_D = 1.8e-3
WIRE_OD = 1.9e-3   # grade-2 enamel
TURNS = 16
FREQS = [40e3, 80e3, 120e3, 200e3, 280e3]
RHO = MaterialResistivity.CopperAnnealed.value

print('T184 (ID %.2f mm), %d turns of %.1f mm wire' % (
    CORE_ID * 1e3, TURNS, WIRE_D * 1e3))
print('%2s %14s %10s %10s %10s' % (
    'S', 'layers', 'Fr_fem@40k', 'Fr_mm@40k', 'fem/mm'))
for strands in (1, 2, 3, 4):
    r = femmt_toroid_acr(CORE_ID, WIRE_D, TURNS, strands, FREQS,
                         wire_od=WIRE_OD)
    f_se, f_pe = acr_factor_micrometals(RHO, WIRE_D, FREQS[0], strands, TURNS,
                                        id=CORE_ID, od=MicrometalsT184.OD)
    fr_mm = 1 + f_se + f_pe
    fr_fem = r.fr_at(FREQS[0])
    print('%2d %14s %10.2f %10.2f %10.2f' % (
        strands, r.layers, fr_fem, fr_mm, fr_fem / fr_mm))
print('\nexpect (2026-08 study): FEM/analytic total-Fr ratio within ~10% at'
      '\nevery strand count (0.91 / 0.95 / 1.04 / 1.03 for S=1..4). An early'
      '\nrun showed FEM 35% higher at S=4 — that was the partial-column'
      '\nperiodicity artifact, fixed by the bracketing configs.')
