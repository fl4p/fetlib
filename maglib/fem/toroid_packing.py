"""
Ring-packing geometry of a toroid inner-diameter winding.

Every strand of every turn passes through the toroid ID, stacking in concentric
layers against the core wall. This module computes how many wires fit per
layer, assigns wires to layers, and derives the equal-full-height-column
geometry used by the FEMMT proxy simulation (see maglib/fem/femmt_toroid.py).

Pure stdlib, SI units (metres) throughout, importable under Python 3.9.
"""
import math
from typing import List, NamedTuple, Optional, Tuple

# hand-winding efficiency vs ideal ring packing (stiff round enameled wire)
DEFAULT_PACK_EFF = 0.8


def layer_radius(layer: int, core_id: float, wire_od: float) -> float:
    """Radius of the circle through the wire centers of packing layer `layer`
    (1-based, layer 1 lies against the core ID wall)."""
    return core_id / 2 - (layer - 0.5) * wire_od


def layer_capacity(layer: int, core_id: float, wire_od: float,
                   pack_eff: float = DEFAULT_PACK_EFF) -> int:
    """How many wires of outer diameter `wire_od` fit in packing layer `layer`
    of a toroid bore with inner diameter `core_id`. 0 when the layer's radius
    has shrunk too far to hold wires."""
    r = layer_radius(layer, core_id, wire_od)
    if r <= wire_od:
        return 0
    return int(pack_eff * 2 * math.pi * r / wire_od)


def assign_layers(n_wires: int, core_id: float, wire_od: float,
                  pack_eff: float = DEFAULT_PACK_EFF) -> List[int]:
    """Distribute `n_wires` ID passes into packing layers, innermost-capacity
    first. Returns wires per layer, e.g. [29, 19]. Raises ValueError when the
    bore cannot hold them."""
    out = []
    layer, left = 1, n_wires
    while left > 0:
        cap = layer_capacity(layer, core_id, wire_od, pack_eff)
        if cap <= 0:
            raise ValueError(
                '%d wires of %.2f mm OD do not fit through a %.2f mm toroid ID '
                '(%d placed in %d layers)' % (
                    n_wires, wire_od * 1e3, core_id * 1e3, n_wires - left, layer - 1))
        take = min(cap, left)
        out.append(take)
        left -= take
        layer += 1
    return out


class ColumnGeometry(NamedTuple):
    """Equal full-height-column layout for the FEMMT toroid proxy.

    The proxy models the ID bundle as `n_layers` vertical columns of
    `conductors_per_column` wires at uniform `pitch`; the FEM window height is
    exactly `window_h = conductors_per_column * pitch` so the high-mu yokes
    mirror each column into an infinite periodic array (== the closed wire
    ring around the toroid ID). Every column is FULL: `n_wires` is always
    `n_layers * conductors_per_column` here — a short column is not a local
    defect but breaks the mirror periodicity of the WHOLE model (measured:
    0.45 rel. asymmetry across all columns for 22/22/20), so indivisible
    wire counts are simulated as two bracketing divisible configs instead
    (see fem_sim_configs).
    """
    n_wires: int            # == n_layers * conductors_per_column
    n_layers: int
    conductors_per_column: int
    pitch: float            # m, wire center-to-center
    window_h: float         # m, == conductors_per_column * pitch
    layers: List[int]       # real toroid packing (from assign_layers)


def column_geometry(n_wires: int, core_id: float, wire_od: float,
                    pack_eff: float = DEFAULT_PACK_EFF,
                    n_layers: Optional[int] = None) -> ColumnGeometry:
    """FEM proxy column layout for `n_wires` ID passes; `n_wires` must divide
    evenly into the packing layer count (pass `n_layers` to override the
    derived count, used by fem_sim_configs for bracketing configs).

    pitch = (mean circumference of the occupied packing layers) divided by
    conductors_per_column — wires spread evenly, as a hand winding lands.
    """
    layers = assign_layers(n_wires, core_id, wire_od, pack_eff)
    if n_layers is None:
        n_layers = len(layers)
    if n_wires % n_layers:
        raise ValueError(
            '%d wires do not divide into %d equal full columns — use '
            'fem_sim_configs() for indivisible counts' % (n_wires, n_layers))
    cap = sum(layer_capacity(k, core_id, wire_od, pack_eff)
              for k in range(1, n_layers + 1))
    if n_wires > cap:
        # a forced n_layers must still be physically packable: 54 wires do
        # not fit 2 layers of a 24.13 mm bore (cap 29+24=53) — simulating
        # 2x27 anyway would produce a plausible Fr for a fictitious geometry
        raise ValueError(
            '%d wires exceed the %d-layer capacity %d of a %.2f mm bore'
            % (n_wires, n_layers, cap, core_id * 1e3))
    n_col = n_wires // n_layers
    circ_mean = sum(2 * math.pi * layer_radius(k, core_id, wire_od)
                    for k in range(1, n_layers + 1)) / n_layers
    pitch = circ_mean / n_col
    if pitch < wire_od:
        # more wires per column than the mean circumference holds at this OD;
        # refuse rather than simulate an unbuildable overlap
        raise ValueError(
            'column pitch %.3f mm < wire OD %.2f mm for %d wires in %d layers '
            '(ID %.2f mm)' % (pitch * 1e3, wire_od * 1e3, n_wires, n_layers,
                              core_id * 1e3))
    return ColumnGeometry(n_wires=n_wires, n_layers=n_layers,
                          conductors_per_column=n_col, pitch=pitch,
                          window_h=n_col * pitch, layers=layers)


def fem_sim_configs(n_wires: int, core_id: float, wire_od: float,
                    pack_eff: float = DEFAULT_PACK_EFF
                    ) -> List[Tuple[float, ColumnGeometry]]:
    """FEM configs (weight, geometry) whose weighted Fr represents `n_wires`.

    Divisible counts run as one exact config. Indivisible counts run as the
    two bracketing divisible counts (all columns full, clean periodicity)
    with linear-in-n_wires interpolation weights — e.g. 64 wires in 3 layers
    becomes 2/3 * Fr(63 = 3x21) + 1/3 * Fr(66 = 3x22). When the UPPER
    bracket would exceed the n_layers capacity of the bore (53 wires ->
    bracket 54 > cap 53 for 2 layers), only the lower bracket runs at full
    weight — a documented <=(n_layers-1)-wire bias, visible in the wrapper's
    provenance['configs'], never a fictitious over-capacity geometry.
    """
    n_layers = len(assign_layers(n_wires, core_id, wire_od, pack_eff))
    if n_wires % n_layers == 0:
        return [(1.0, column_geometry(n_wires, core_id, wire_od, pack_eff))]
    n_lo = n_layers * (n_wires // n_layers)
    n_hi = n_layers * (n_wires // n_layers + 1)
    cap = sum(layer_capacity(k, core_id, wire_od, pack_eff)
              for k in range(1, n_layers + 1))
    if n_hi > cap:
        return [(1.0, column_geometry(n_lo, core_id, wire_od, pack_eff,
                                      n_layers=n_layers))]
    w_hi = (n_wires - n_lo) / (n_hi - n_lo)
    return [
        (1.0 - w_hi, column_geometry(n_lo, core_id, wire_od, pack_eff,
                                     n_layers=n_layers)),
        (w_hi, column_geometry(n_hi, core_id, wire_od, pack_eff,
                               n_layers=n_layers)),
    ]
