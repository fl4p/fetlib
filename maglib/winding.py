"""Toroid winding fit: parallel strands of round enamelled wire through the bore.

Every strand of every turn passes through the toroid's inner window, so the
bore is what limits the strand count. Two views of the same constraint:

* ``max_strands`` -- area fill: passes = fill_target * (ID/d_o)**2, the classic
  hand-winding rule of thumb (fill_target ~ 0.4 max for stiff wire).
* ``layer_fit`` -- concentric layers against the bore, with a practical packing
  factor, showing where the passes land and what hole remains.

All lengths are SI metres, like the rest of maglib. CLI (mm in, human out):

    python -m maglib.winding --turns 16 --wire-mm 1.8 --grade 2 \
        --id-mm 24.11 --od-mm 46.7 --ht-mm 18
    python -m maglib.winding --turns 16 --wire-mm 1.8 --core KDM_KS184_125A --ht-mm 18
"""
import math

# Maximum overall diameter of enamelled round copper wire, IEC/DIN EN 60317-0-1.
# {nominal bare diameter [mm]: (grade1, grade2, grade3) max OD [mm]}.
# Rows <= 1.320 from the HEERMANN GmbH DIN EN 60317-0-1 sheet (Ausgabe 09/2014);
# rows >= 1.400 from SH-wire's IEC 60317-0-1 size table (grade 1 cross-checked
# against an independent source; the standard defines no grade 3 there -> None).
_IEC60317_MAX_OD_MM = {
    0.200: (0.226, 0.239, 0.252),
    0.250: (0.281, 0.297, 0.312),
    0.315: (0.349, 0.367, 0.384),
    0.400: (0.439, 0.459, 0.478),
    0.500: (0.544, 0.566, 0.587),
    0.630: (0.679, 0.704, 0.728),
    0.710: (0.762, 0.789, 0.814),
    0.800: (0.855, 0.884, 0.911),
    0.900: (0.959, 0.989, 1.018),
    1.000: (1.062, 1.094, 1.124),
    1.120: (1.184, 1.217, 1.248),
    1.250: (1.316, 1.349, 1.381),
    1.320: (1.388, 1.422, 1.455),
    1.400: (1.468, 1.502, None),
    1.500: (1.570, 1.606, None),
    1.600: (1.670, 1.706, None),
    1.700: (1.772, 1.809, None),
    1.800: (1.872, 1.909, None),
    1.900: (1.974, 2.012, None),
    2.000: (2.074, 2.112, None),
    2.120: (2.196, 2.235, None),
    2.240: (2.316, 2.355, None),
    2.500: (2.578, 2.618, None),
    2.800: (2.880, 2.922, None),
}


def enameled_od(d_bare: float, grade: int = 2) -> float:
    """Max overall diameter [m] of enamelled wire with bare diameter ``d_bare`` [m].

    Linear interpolation between the IEC 60317-0-1 nominal sizes. Refuses
    outside the table (0.2..2.8 mm) and where the standard defines no build
    for the grade -- an unverified guess must not become a fit calculation.
    """
    if grade not in (1, 2, 3):
        raise ValueError('grade must be 1, 2 or 3, got %r' % (grade,))
    d_mm = d_bare * 1e3
    sizes = sorted(_IEC60317_MAX_OD_MM)
    if not sizes[0] <= d_mm <= sizes[-1]:
        raise ValueError(
            'bare diameter %.3f mm outside IEC 60317-0-1 table (%.3f..%.3f mm)'
            % (d_mm, sizes[0], sizes[-1]))
    hi = next(s for s in sizes if s >= d_mm - 1e-9)
    lo = max(s for s in sizes if s <= d_mm + 1e-9)
    od_lo = _IEC60317_MAX_OD_MM[lo][grade - 1]
    od_hi = _IEC60317_MAX_OD_MM[hi][grade - 1]
    if od_lo is None or od_hi is None:
        raise ValueError(
            'no grade %d build in IEC 60317-0-1 for %.3f mm wire' % (grade, d_mm))
    if hi == lo:
        return od_lo * 1e-3
    return (od_lo + (od_hi - od_lo) * (d_mm - lo) / (hi - lo)) * 1e-3


def _check_geometry(core_id, wire_od):
    # explicit raise, not assert: these guards must survive python -O, and a
    # negative wire_od turns layer_fit into an unbounded loop without them
    if not (0 < wire_od < core_id and math.isfinite(wire_od)
            and math.isfinite(core_id)):
        raise ValueError('need 0 < wire_od < core_id, got wire_od=%r core_id=%r'
                         % (wire_od, core_id))


def max_strands(core_id: float, wire_od: float, turns: int,
                fill_target: float = 0.4) -> int:
    """Max parallel strands so that turns*strands passes fill at most
    ``fill_target`` of the bore window area. Raises if not even one fits."""
    _check_geometry(core_id, wire_od)
    if not 0 < fill_target <= 1:
        raise ValueError('fill_target must be in (0, 1], got %r' % (fill_target,))
    if turns < 1:
        raise ValueError('turns must be >= 1, got %r' % (turns,))
    passes = math.floor(fill_target * (core_id / wire_od) ** 2)
    strands = passes // turns
    if strands < 1:
        raise ValueError(
            '%d turns of %.2f mm wire do not fit ID %.2f mm at fill %.2f '
            '(%d passes possible)'
            % (turns, wire_od * 1e3, core_id * 1e3, fill_target, passes))
    return strands


def window_fill(core_id: float, wire_od: float, n_passes: int) -> float:
    """Fraction of the bore window area occupied by ``n_passes`` wires."""
    return n_passes * (wire_od / core_id) ** 2


def layer_fit(core_id: float, wire_od: float, n_passes: int, packing: float = 0.8):
    """Distribute ``n_passes`` bore passes onto concentric layers.

    Layer k (1-based) centers sit at r = ID/2 - (k-0.5)*wire_od and hold
    floor(packing * 2*pi*r / wire_od) wires; ``packing`` < 1 models the gaps
    hand-winding stiff wire leaves against ideal close packing.

    Returns [(layer, capacity, placed, hole_d_after), ...] covering exactly
    ``n_passes``. Raises when the bore cannot hold them -- never a short list.
    """
    _check_geometry(core_id, wire_od)
    if not 0 < packing <= 1:
        raise ValueError('packing must be in (0, 1], got %r' % (packing,))
    if n_passes < 1:
        raise ValueError('n_passes must be >= 1, got %r' % (n_passes,))
    layers = []
    remaining = n_passes
    k = 0
    while remaining > 0:
        k += 1
        r = core_id / 2 - (k - 0.5) * wire_od
        if r < wire_od / 2:
            raise ValueError(
                '%d passes of %.2f mm wire do not fit ID %.2f mm '
                '(%d left after %d layers)'
                % (n_passes, wire_od * 1e3, core_id * 1e3, remaining, k - 1))
        capacity = math.floor(packing * 2 * math.pi * r / wire_od)
        placed = min(capacity, remaining)
        remaining -= placed
        layers.append((k, capacity, placed, core_id - 2 * k * wire_od))
    return layers


def mean_turn_length(core_od: float, core_id: float, core_ht: float,
                     wire_od: float, layers: int = 1) -> float:
    """Mean length [m] of one turn around the core cross-section.

    Rectangular cross-section (radial build x height) plus the rounded
    corners a wire centerline actually follows; averaged over ``layers``
    build-up layers (layer k centerline sits (k-0.5)*wire_od off the core).
    """
    if not (0 < core_id < core_od and core_ht > 0 and layers >= 1):
        raise ValueError('bad core geometry: od=%r id=%r ht=%r layers=%r'
                         % (core_od, core_id, core_ht, layers))
    build = (core_od - core_id) / 2
    return 2 * (build + core_ht) + 2 * math.pi * wire_od * layers / 2


def strand_cut_length(mlt: float, turns: int, lead: float = 0.15) -> float:
    """Cut length [m] per strand: wound turns plus a termination lead each end."""
    return mlt * turns + 2 * lead


def _resolve_core(name: str):
    from maglib import cores as _cores

    def has_bore(v):
        return (hasattr(v, 'winding_bore') and not isinstance(v, type)
                and getattr(v, 'shape', None) is not None
                and math.isfinite(v.shape.ID))

    core = getattr(_cores, name, None)
    if core is None or not hasattr(core, 'winding_bore'):
        known = sorted(n for n, v in vars(_cores).items() if has_bore(v))
        raise ValueError('unknown core %r, known: %s' % (name, ', '.join(known)))
    return core


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        description='Max parallel strands on a toroid for a given ID fill target.')
    p.add_argument('--turns', type=int, required=True)
    p.add_argument('--wire-mm', type=float, help='bare copper diameter [mm]')
    p.add_argument('--grade', type=int, default=2, choices=(1, 2, 3),
                   help='enamel grade per IEC 60317 (default 2)')
    p.add_argument('--wire-od-mm', type=float,
                   help='overall diameter incl. enamel [mm]; overrides --wire-mm/--grade')
    p.add_argument('--core', help='core instance name from maglib.cores, e.g. KDM_KS184_125A')
    p.add_argument('--id-mm', type=float, help='toroid inner diameter [mm]')
    p.add_argument('--od-mm', type=float, help='toroid outer diameter [mm]')
    p.add_argument('--ht-mm', type=float, help='toroid height [mm]')
    p.add_argument('--fill', type=float, default=0.4,
                   help='ID window area fill target (default 0.4)')
    p.add_argument('--packing', type=float, default=0.8,
                   help='practical layer packing vs ideal (default 0.8)')
    args = p.parse_args(argv)

    if args.wire_od_mm is not None:
        wire_od = args.wire_od_mm * 1e-3
        wire_desc = '%.3f mm OD' % args.wire_od_mm
    elif args.wire_mm is not None:
        wire_od = enameled_od(args.wire_mm * 1e-3, args.grade)
        wire_desc = '%.3f mm bare, grade %d -> %.3f mm OD' % (
            args.wire_mm, args.grade, wire_od * 1e3)
    else:
        p.error('need --wire-mm or --wire-od-mm')

    core_id = core_od = core_ht = None
    if args.core:
        core = _resolve_core(args.core)
        core_id, core_od = core.winding_bore()
        ht = getattr(core.shape, 'HT', float('nan'))
        if math.isfinite(ht):
            core_ht = ht
    if args.id_mm is not None:
        core_id = args.id_mm * 1e-3
    if args.od_mm is not None:
        core_od = args.od_mm * 1e-3
    if args.ht_mm is not None:
        core_ht = args.ht_mm * 1e-3
    if core_id is None:
        p.error('need --id-mm or --core')

    print('wire: %s' % wire_desc)
    print('bore: ID %.2f mm, %d turns, fill target %.2f' % (
        core_id * 1e3, args.turns, args.fill))

    strands = max_strands(core_id, wire_od, args.turns, args.fill)
    n_passes = strands * args.turns
    print('\nmax strands: %d  (%d passes, actual fill %.2f)' % (
        strands, n_passes, window_fill(core_id, wire_od, n_passes)))
    for f in (0.3, 0.4, 0.5):
        try:
            s = max_strands(core_id, wire_od, args.turns, f)
        except ValueError:
            s = 0
        print('  fill %.1f -> %d strands' % (f, s))

    print('\nlayers (packing %.2f):' % args.packing)
    layers = layer_fit(core_id, wire_od, n_passes, args.packing)
    for k, capacity, placed, hole in layers:
        print('  layer %d: %2d/%2d wires, hole after: %5.1f mm'
              % (k, placed, capacity, hole * 1e3))

    if core_od is not None and core_ht is not None:
        mlt = mean_turn_length(core_od, core_id, core_ht, wire_od, len(layers))
        cut = strand_cut_length(mlt, args.turns)
        print('\nmean turn length: %.1f mm  (core %.1f x %.1f x %.1f mm)' % (
            mlt * 1e3, core_od * 1e3, core_id * 1e3, core_ht * 1e3))
        print('cut length per strand: %.2f m (incl. 2x150 mm leads), '
              'total %.1f m for %d strands'
              % (cut, cut * strands, strands))
    else:
        print('\n(no --od-mm/--ht-mm: skipping turn-length estimate)')


if __name__ == '__main__':
    main()
