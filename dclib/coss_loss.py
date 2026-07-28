"""Charge-conserving nonlinear MOSFET Coss/Eoss transition accounting.

This module deliberately separates three things that are often collapsed into a
single ``0.5*Coss*V**2*f`` estimate:

* the reversible state functions Qoss(V) and Eoss(V);
* the circuit mechanism that moves that energy (commutated, recovered, channel
  discharge, or resistive charging); and
* measured Coss hysteresis/dielectric loss.

The first comes from the datasheet Coss(V) curve (or an explicitly labelled scalar
fallback), the second comes from a voltage waveform split into mechanism-labelled
segments, and the third is an independent calibration with its own conditions and
provenance. Package/copper/Cin ring damping does not enter this ledger.
"""

from dataclasses import asdict, dataclass, replace
import json
import math
import re
import warnings
from typing import Dict, Iterable, Optional, Sequence, Tuple


PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"

OWNER_FETLIB = "fetlib-analytic"
OWNER_EXTERNAL = "external-waveform"

# The one curve-backed model state. Consumers that must distinguish "real Coss(V)
# evidence" from the scalar guess (e.g. the Qrr decontamination gate) compare against
# this constant instead of re-typing the string.
MODEL_STATE_CURVE = "datasheet-coss-curve"

# Scalar-fallback warning dedup, keyed by MPN (see CossEnergyModel.from_mosfet).
_warned_scalar_fallback = set()

MECH_COMMUTATED = "commutated"
MECH_CHANNEL_DISCHARGE = "channel-discharge"
MECH_RESISTIVE_CHARGE = "resistive-charge"
_MECHANISMS = {MECH_COMMUTATED, MECH_CHANNEL_DISCHARGE, MECH_RESISTIVE_CHARGE}

TOPOLOGY_SYNCHRONOUS_BUCK = "synchronous-buck"
ROLE_HS = "high-side"
ROLE_LS = "low-side"
CURRENT_SOURCE_TO_LOAD = "source-to-load"
CURRENT_LOAD_TO_SOURCE = "load-to-source"

ENERGY_DC_SOURCE = "dc-source"
ENERGY_LOAD_INDUCTOR = "load/inductor"
ENERGY_EXTERNAL = "external-waveform"
_FIXED_ENDPOINTS = {ENERGY_DC_SOURCE, ENERGY_LOAD_INDUCTOR, ENERGY_EXTERNAL}
_DEVICE_ENDPOINT_RE = re.compile(
    r"^device:([A-Za-z0-9_.-]+):(coss|channel|body-diode|coss-hysteresis)$")


def device_energy_endpoint(device_id: str, kind: str) -> str:
    endpoint = "device:%s:%s" % (device_id, kind)
    if not _DEVICE_ENDPOINT_RE.fullmatch(endpoint):
        raise ValueError("invalid device energy endpoint %r" % endpoint)
    return endpoint


def _valid_energy_endpoint(endpoint: Optional[str]) -> bool:
    return bool(endpoint in _FIXED_ENDPOINTS
                or (isinstance(endpoint, str) and _DEVICE_ENDPOINT_RE.fullmatch(endpoint)))


def _finite(value) -> bool:
    return value is not None and math.isfinite(value)


def _close(a: float, b: float, *, rel: float = 1e-6, abs_: float = 1e-12) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


@dataclass(frozen=True)
class CossState:
    """Reversible charge and stored energy at one drain voltage."""

    vds_v: float
    qoss_c: float
    eoss_j: float


@dataclass(frozen=True)
class CossWaveformSegment:
    """One labelled interval of a device's Vds waveform.

    ``t0_s``/``t1_s`` preserve the waveform and make partial-ZVS/deadtime inputs
    auditable. The energy integral is a state-function difference over every
    interval; no binary "hard switching fraction" exists.
    """

    t0_s: float
    t1_s: float
    v0_v: float
    v1_v: float
    mechanism: str
    destination: str
    source_voltage_v: Optional[float] = None
    source: Optional[str] = None

    def __post_init__(self):
        if self.mechanism not in _MECHANISMS:
            raise ValueError("unknown Coss transition mechanism %r" % self.mechanism)
        if not all(_finite(x) for x in (self.t0_s, self.t1_s, self.v0_v, self.v1_v)):
            raise ValueError("Coss waveform segment must be finite: %r" % (self,))
        if self.t1_s <= self.t0_s:
            raise ValueError("Coss waveform time must increase: %r" % (self,))
        if self.v0_v < 0 or self.v1_v < 0:
            raise ValueError("Coss Vds magnitude cannot be negative: %r" % (self,))
        if not _valid_energy_endpoint(self.destination):
            raise ValueError("invalid Coss energy destination %r" % self.destination)
        if self.source is not None and not _valid_energy_endpoint(self.source):
            raise ValueError("invalid Coss energy source %r" % self.source)
        if self.mechanism == MECH_RESISTIVE_CHARGE:
            if not _finite(self.source_voltage_v) or self.source_voltage_v <= 0:
                raise ValueError("resistive Coss charging needs a positive source voltage")


@dataclass(frozen=True)
class CossTransition:
    """A complete per-device Coss transition evaluated ``events_per_cycle`` times."""

    name: str
    segments: Tuple[CossWaveformSegment, ...]
    events_per_cycle: float = 1.0
    device_count: int = 1
    # Compatibility name: this owns transition/commutation loss only. Intrinsic
    # hysteresis has a separate owner so an external waveform cannot suppress it.
    accounting_owner: str = OWNER_FETLIB
    hysteresis_accounting_owner: str = OWNER_FETLIB
    model_state: str = "explicit-waveform"
    evidence_quality: str = UNVERIFIED
    topology: str = "generic"
    device_id: str = "device"
    device_role: str = "unspecified"
    peer_device_id: Optional[str] = None
    switch_node: str = "switch"
    current_direction: str = "unknown"
    cell_event_id: str = "standalone"
    turn_on_time_s: Optional[float] = None
    waveform_covered_until_s: Optional[float] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("Coss transition must be named")
        if not self.segments:
            raise ValueError("Coss transition needs at least one waveform segment")
        if not _finite(self.events_per_cycle) or self.events_per_cycle <= 0:
            raise ValueError("events_per_cycle must be positive")
        if not isinstance(self.device_count, int) or self.device_count <= 0:
            raise ValueError("device_count must be a positive integer")
        if self.accounting_owner not in (OWNER_FETLIB, OWNER_EXTERNAL):
            raise ValueError("unknown Coss accounting owner %r" % self.accounting_owner)
        if self.hysteresis_accounting_owner not in (OWNER_FETLIB, OWNER_EXTERNAL):
            raise ValueError("unknown Coss hysteresis accounting owner %r"
                             % self.hysteresis_accounting_owner)
        for name, value in (
                ("turn_on_time_s", self.turn_on_time_s),
                ("waveform_covered_until_s", self.waveform_covered_until_s)):
            if value is not None and (not _finite(value) or value < 0):
                raise ValueError("%s must be finite and non-negative" % name)
        if ((self.turn_on_time_s is None)
                != (self.waveform_covered_until_s is None)):
            raise ValueError(
                "timed Coss transitions require deadline and waveform coverage together")
        if (self.turn_on_time_s is not None
                and self.waveform_covered_until_s is not None
                and self.waveform_covered_until_s < self.turn_on_time_s):
            raise ValueError("deadtime waveform does not cover the turn-on deadline")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.device_id):
            raise ValueError("invalid Coss device_id %r" % self.device_id)
        if self.peer_device_id is not None and not re.fullmatch(
                r"[A-Za-z0-9_.-]+", self.peer_device_id):
            raise ValueError("invalid Coss peer_device_id %r" % self.peer_device_id)
        if self.topology == TOPOLOGY_SYNCHRONOUS_BUCK:
            if self.device_role not in (ROLE_HS, ROLE_LS):
                raise ValueError("synchronous-buck transition needs HS/LS device_role")
            if self.peer_device_id is None:
                raise ValueError("synchronous-buck transition needs peer and current direction")
            if self.peer_device_id == self.device_id:
                raise ValueError("synchronous-buck peer must be a distinct device")
            # Reverse-current buck commutation needs a different set of source and
            # destination rules. Until that ledger exists, reject the label rather
            # than letting forward-power-flow mechanisms pass under a false name.
            if self.current_direction != CURRENT_SOURCE_TO_LOAD:
                raise ValueError(
                    "load-to-source synchronous-buck Coss flow is not implemented")
        allowed_devices = {self.device_id, self.peer_device_id}
        for seg in self.segments:
            for endpoint in (seg.source, seg.destination):
                match = _DEVICE_ENDPOINT_RE.fullmatch(endpoint or "")
                if match and match.group(1) not in allowed_devices:
                    raise ValueError("energy endpoint %r is outside transition devices %r"
                                     % (endpoint, allowed_devices))
        for a, b in zip(self.segments, self.segments[1:]):
            if not _close(a.t1_s, b.t0_s) or not _close(a.v1_v, b.v0_v):
                raise ValueError("Coss waveform segments are not continuous: %r -> %r" % (a, b))

    @classmethod
    def from_points(cls, name: str, points: Sequence[Tuple[float, float]], *,
                    mechanism: str, destination: str,
                    source_voltage_v: Optional[float] = None,
                    events_per_cycle: float = 1.0, device_count: int = 1,
                    accounting_owner: str = OWNER_FETLIB,
                    hysteresis_accounting_owner: str = OWNER_FETLIB,
                    model_state: str = "explicit-waveform",
                    evidence_quality: str = UNVERIFIED,
                    topology: str = "generic", device_id: str = "device",
                    device_role: str = "unspecified",
                    peer_device_id: Optional[str] = None,
                    switch_node: str = "switch",
                    current_direction: str = "unknown",
                    cell_event_id: str = "standalone",
                    source: Optional[str] = None,
                    turn_on_time_s: Optional[float] = None,
                    waveform_covered_until_s: Optional[float] = None
                    ) -> "CossTransition":
        if len(points) < 2:
            raise ValueError("a Coss waveform needs at least two (time, Vds) points")
        segs = tuple(CossWaveformSegment(
            t0_s=a[0], t1_s=b[0], v0_v=a[1], v1_v=b[1],
            mechanism=mechanism, destination=destination,
            source_voltage_v=source_voltage_v, source=source,
        ) for a, b in zip(points, points[1:]))
        return cls(name=name, segments=segs, events_per_cycle=events_per_cycle,
                   device_count=device_count, accounting_owner=accounting_owner,
                   hysteresis_accounting_owner=hysteresis_accounting_owner,
                   model_state=model_state, evidence_quality=evidence_quality,
                   topology=topology, device_id=device_id, device_role=device_role,
                   peer_device_id=peer_device_id, switch_node=switch_node,
                   current_direction=current_direction, cell_event_id=cell_event_id,
                   turn_on_time_s=turn_on_time_s,
                   waveform_covered_until_s=waveform_covered_until_s)

    @classmethod
    def partial_zvs(cls, name: str, deadtime_waveform: Sequence[Tuple[float, float]], *,
                    turn_on_vds_v: float = 0.0, channel_destination: str,
                    recovery_destination: str = "source/load",
                    turn_on_time_s: Optional[float] = None,
                    events_per_cycle: float = 1.0, device_count: int = 1,
                    accounting_owner: str = OWNER_FETLIB,
                    hysteresis_accounting_owner: str = OWNER_FETLIB,
                    evidence_quality: str = UNVERIFIED,
                    topology: str = TOPOLOGY_SYNCHRONOUS_BUCK,
                    device_id: str = "hs", device_role: str = ROLE_HS,
                    peer_device_id: Optional[str] = "ls",
                    switch_node: str = "switch",
                    current_direction: str = CURRENT_SOURCE_TO_LOAD,
                    cell_event_id: str = "buck-hs-turn-on") -> "CossTransition":
        """Build a deadtime commutation followed by any residual channel discharge.

        Every supplied sample is retained as a separate commutated interval. If
        deadtime reaches zero, no channel-discharge interval is added; if it only
        reaches a residual voltage, the residual Eoss is dissipated in the named
        channel. That is the partial-ZVS calculation.
        """
        if len(deadtime_waveform) < 2:
            raise ValueError("partial ZVS needs a sampled deadtime waveform")
        points = tuple((float(t), float(v)) for t, v in deadtime_waveform)
        if not all(_finite(t) and _finite(v) for t, v in points):
            raise ValueError("partial ZVS waveform must be finite")
        if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
            raise ValueError("partial ZVS waveform times must increase")
        covered_until = points[-1][0]
        deadline = covered_until if turn_on_time_s is None else float(turn_on_time_s)
        if (not _finite(deadline) or deadline <= points[0][0]
                or deadline > covered_until):
            raise ValueError(
                "partial ZVS turn-on deadline must be covered by the sampled waveform")

        # Samples after turn-on prove coverage but are not integrated. Interpolate Vds
        # when the configured deadline falls between two acquired samples.
        clipped = [points[0]]
        for a, b in zip(points, points[1:]):
            if b[0] < deadline and not _close(b[0], deadline):
                clipped.append(b)
                continue
            if _close(b[0], deadline):
                clipped.append((deadline, b[1]))
            else:
                fraction = (deadline - a[0]) / (b[0] - a[0])
                clipped.append((deadline, a[1] + fraction * (b[1] - a[1])))
            break

        if recovery_destination == "source/load":
            recovery_destination = ENERGY_LOAD_INDUCTOR
        coss_source = device_energy_endpoint(device_id, "coss")
        segs = []
        for a, b in zip(clipped, clipped[1:]):
            if b[1] > a[1]:
                # A rebound/ringing interval returns energy from the commutating
                # circuit into this device's output capacitance.
                source, destination = recovery_destination, coss_source
            else:
                source, destination = coss_source, recovery_destination
            segs.append(CossWaveformSegment(
                a[0], b[0], a[1], b[1], MECH_COMMUTATED,
                destination, source=source))
        t, residual = clipped[-1]
        if turn_on_vds_v > residual and not _close(turn_on_vds_v, residual):
            raise ValueError("channel turn-on target cannot increase Coss voltage")
        if not _close(residual, turn_on_vds_v):
            dt = max(1e-15, abs(t - clipped[0][0]) * 1e-9)
            segs.append(CossWaveformSegment(
                t, t + dt, residual, turn_on_vds_v, MECH_CHANNEL_DISCHARGE,
                channel_destination, source=coss_source,
            ))
        return cls(name=name, segments=tuple(segs), events_per_cycle=events_per_cycle,
                   device_count=device_count, accounting_owner=accounting_owner,
                   hysteresis_accounting_owner=hysteresis_accounting_owner,
                   model_state="partial-zvs-waveform",
                   evidence_quality=evidence_quality, topology=topology,
                   device_id=device_id, device_role=device_role,
                   peer_device_id=peer_device_id, switch_node=switch_node,
                   current_direction=current_direction, cell_event_id=cell_event_id,
                   turn_on_time_s=deadline,
                   waveform_covered_until_s=covered_until)


@dataclass(frozen=True)
class CossHysteresisCalibration:
    """Measured per-event Coss hysteresis/dielectric loss at exact conditions.

    This calibration is intentionally not an ESR or ring-damping parameter. It is
    accepted only at its stated voltage/frequency/temperature/gate-bias point; callers
    must supply another measured calibration rather than silently extrapolate it.
    """

    energy_loss_j_per_event: float
    v_low_v: float
    v_high_v: float
    frequency_hz: float
    temperature_c: float
    gate_bias_v: float
    provenance: str
    evidence_quality: str = PASS
    energy_source: str = ENERGY_DC_SOURCE

    def __post_init__(self):
        nums = (self.energy_loss_j_per_event, self.v_low_v, self.v_high_v,
                self.frequency_hz, self.temperature_c, self.gate_bias_v)
        if not all(_finite(x) for x in nums):
            raise ValueError("Coss hysteresis calibration conditions must be finite")
        if self.energy_loss_j_per_event < 0 or self.v_low_v < 0:
            raise ValueError("Coss hysteresis calibration cannot be negative")
        if self.v_high_v <= self.v_low_v or self.frequency_hz <= 0:
            raise ValueError("invalid Coss hysteresis calibration range/frequency")
        if not self.provenance:
            raise ValueError("Coss hysteresis calibration needs provenance")
        if not _valid_energy_endpoint(self.energy_source):
            raise ValueError("invalid hysteresis energy source %r" % self.energy_source)


class CossEnergyModel:
    """Qoss/Eoss state functions from Coss(V), with explicit fallback provenance."""

    def __init__(self, *, curve=None, scalar_coss_f=None, scalar_anchor_v=None,
                 metadata=None, operating_frequency_hz=None,
                 operating_temperature_c=None, gate_bias_v=0.0):
        self.metadata = dict(metadata or {})
        self.operating_frequency_hz = operating_frequency_hz
        self.operating_temperature_c = operating_temperature_c
        self.gate_bias_v = gate_bias_v
        self.extrapolation_flags = []

        if curve:
            rows = []
            for row in curve:
                if len(row) < 2:
                    raise ValueError("Coss curve row needs Vds and Coss: %r" % (row,))
                v, c_pf = float(row[0]), float(row[1])
                if not _finite(v) or not _finite(c_pf) or v < 0 or c_pf <= 0:
                    raise ValueError("invalid Coss curve row %r" % (row,))
                # Curve rows are picofarads. Real power-MOSFET Coss curves live in
                # ~1..1e5 pF; a curve mistakenly supplied in farads lands 12 orders
                # below and previously under-reported energy by 1e12, silently. The
                # populations are separated by a genuine void, so the floor is safe.
                if not 0.1 <= c_pf <= 1e6:
                    raise ValueError(
                        "implausible Coss curve value %g pF in row %r — rows are pF, "
                        "not farads" % (c_pf, row))
                rows.append((v, c_pf * 1e-12))
            rows.sort()
            if len(rows) < 2 or rows[0][0] != 0:
                raise ValueError("Coss curve must contain at least two points and start at 0 V")
            if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
                raise ValueError("Coss curve voltages must increase strictly")
            self.curve = tuple(rows)
            self.scalar_coss_f = None
            self.scalar_anchor_v = None
            self.model_state = MODEL_STATE_CURVE
            self.provenance = self.metadata.get("provenance", "attached Coss(V) curve")
            self.base_evidence_quality = self.metadata.get("evidence_quality", UNVERIFIED)
        else:
            if not _finite(scalar_coss_f) or scalar_coss_f < 0:
                raise ValueError("no usable Coss(V) curve or scalar Coss")
            if scalar_coss_f == 0:
                # A parsed Coss of exactly 0 is indistinguishable from this repo's
                # corrupt-parse class, and it is the BEST possible loss number — the
                # anti-monotone false-PASS shape. Zero is only accepted when the caller
                # declares the intent; without that, refuse so the part becomes an
                # unavailable/NaN report instead of a silent 0 W with minted provenance.
                if not self.metadata.get("provenance"):
                    raise ValueError(
                        "Coss=0 without explicit provenance: a corrupt/zero-parsed Coss "
                        "is indistinguishable from an intentional zero-Coss fixture; "
                        "declare one in coss_curve_meta['provenance']")
                self.curve = None
                self.scalar_coss_f = 0.0
                self.scalar_anchor_v = scalar_anchor_v
                self.model_state = "explicit-zero-coss"
                self.provenance = self.metadata["provenance"]
                self.base_evidence_quality = self.metadata.get("evidence_quality", UNVERIFIED)
                self._flag_condition_extrapolation()
                return
            if not _finite(scalar_anchor_v) or scalar_anchor_v <= 0:
                raise ValueError("scalar Coss fallback needs its Vds anchor")
            self.curve = None
            self.scalar_coss_f = float(scalar_coss_f)
            self.scalar_anchor_v = float(scalar_anchor_v)
            self.model_state = "scalar-inverse-sqrt-fallback"
            self.provenance = self.metadata.get(
                "provenance", "single datasheet Coss anchor; assumed Coss(V) proportional to 1/sqrt(V)")
            self.base_evidence_quality = UNVERIFIED
            self.extrapolation_flags.append("nonlinear-curve-missing:scalar-parametric-fallback")

        self._flag_condition_extrapolation()

    @classmethod
    def from_mosfet(cls, mf, *, operating_frequency_hz=None,
                    operating_temperature_c=None, gate_bias_v=0.0) -> "CossEnergyModel":
        curve = getattr(mf, "coss_curve", None)
        meta = getattr(mf, "coss_curve_meta", None) or {}
        coss = getattr(mf, "Coss", math.nan)
        anchor = getattr(mf, "Coss_Vds", None)
        if not _finite(anchor) or anchor <= 0:
            anchor = getattr(mf, "Coss_V0", math.nan)
        # Warn only when the fallback will actually be USED: for Coss=NaN the
        # constructor raises right after, and a warning claiming a fallback that never
        # happens misattributes the refusal (the unavailable report carries the real
        # reason in its provenance).
        if not curve and _finite(coss) and coss > 0:
            part = getattr(getattr(mf, "part", None), "mpn", "<unknown>")
            # Once per part per process: the model is constructed several times per
            # part per run, and the per-MPN message defeats Python's own warn dedup —
            # a full ranking run drowned in thousands of identical lines.
            if part not in _warned_scalar_fallback:
                _warned_scalar_fallback.add(part)
                warnings.warn("%s: no Coss(V) curve; using explicitly UNVERIFIED "
                              "inverse-sqrt scalar fallback" % part)
        return cls(curve=curve, scalar_coss_f=coss, scalar_anchor_v=anchor,
                   metadata=meta, operating_frequency_hz=operating_frequency_hz,
                   operating_temperature_c=operating_temperature_c,
                   gate_bias_v=gate_bias_v)

    def _flag_condition_extrapolation(self):
        # frequency_hz is deliberately NOT an evidence-capping axis: the C(V) curve is
        # the quasi-static reversible state function, and its 1 MHz small-signal
        # measurement frequency is not extrapolated by running the converter at a
        # different switching frequency. Frequency-DEPENDENT Coss loss is the
        # hysteresis calibration's job, and _validate_hysteresis refuses a frequency
        # mismatch outright. Both frequencies remain side-by-side in `conditions`.
        checks = (
            ("temperature_c", self.operating_temperature_c),
            ("gate_bias_v", self.gate_bias_v),
        )
        for key, operating in checks:
            measured = self.metadata.get(key)
            if measured is None:
                self.extrapolation_flags.append("%s:measurement-unknown" % key)
                continue
            if operating is None:
                self.extrapolation_flags.append("%s:operating-unknown" % key)
                continue
            if not _close(float(measured), float(operating), rel=1e-3):
                self.extrapolation_flags.append("%s:%g->%g" % (key, measured, operating))
        binding_state = self.metadata.get("binding_state")
        if binding_state and str(binding_state).startswith("unverified-"):
            self.extrapolation_flags.append(
                "curve-metadata-binding:%s" % binding_state)

    def _integrate_curve(self, voltage_v: float) -> Tuple[float, float]:
        """Analytically integrate the piecewise-linear C(V) representation."""
        q, e = 0.0, 0.0
        remaining = voltage_v
        rows = self.curve
        for (v0, c0), (v1, c1) in zip(rows, rows[1:]):
            if remaining <= v0:
                break
            stop = min(remaining, v1)
            dx = stop - v0
            if dx <= 0:
                continue
            slope = (c1 - c0) / (v1 - v0)
            q += c0 * dx + 0.5 * slope * dx ** 2
            e += (v0 * c0 * dx
                  + 0.5 * (v0 * slope + c0) * dx ** 2
                  + slope * dx ** 3 / 3.0)
            if remaining <= v1:
                return q, e

        vmax, cmax = rows[-1]
        if remaining > vmax:
            # Constant-C extension is deliberately simple and loudly flagged. It avoids
            # inventing a new knee outside the digitized graph while preserving positive
            # charge and energy.
            dx = remaining - vmax
            q += cmax * dx
            e += cmax * (remaining ** 2 - vmax ** 2) / 2.0
            # One flag per model, keyed on the curve limit only: a per-voltage flag
            # grew without bound across calls at varying voltages. Flags are cumulative
            # model state — production builds a fresh model per evaluation; a reused
            # model keeps flags from earlier queries (conservative direction).
            flag = "voltage_v:curve-max-%g-exceeded:constant-C-extension" % vmax
            if flag not in self.extrapolation_flags:
                self.extrapolation_flags.append(flag)
        return q, e

    def at(self, voltage_v: float) -> CossState:
        if not _finite(voltage_v) or voltage_v < 0:
            raise ValueError("Coss state voltage must be finite and non-negative")
        voltage_v = float(voltage_v)
        if voltage_v == 0:
            return CossState(0.0, 0.0, 0.0)
        if self.curve:
            q, e = self._integrate_curve(voltage_v)
        elif self.scalar_coss_f == 0:
            q, e = 0.0, 0.0
        else:
            # Integral of the explicitly stated nonlinear fallback
            # C(V)=C_anchor*sqrt(V_anchor/V). This is never 1/2*C_table*V^2.
            scale = self.scalar_coss_f * math.sqrt(self.scalar_anchor_v)
            q = 2.0 * scale * math.sqrt(voltage_v)
            e = (2.0 / 3.0) * scale * voltage_v ** 1.5
        return CossState(voltage_v, q, e)

    @property
    def evidence_quality(self) -> str:
        return (self.base_evidence_quality
                if not self.extrapolation_flags else UNVERIFIED)

    @property
    def conditions(self) -> Dict[str, object]:
        return dict(
            measurement_frequency_hz=self.metadata.get("frequency_hz"),
            operating_frequency_hz=self.operating_frequency_hz,
            measurement_temperature_c=self.metadata.get("temperature_c"),
            operating_temperature_c=self.operating_temperature_c,
            measurement_gate_bias_v=self.metadata.get("gate_bias_v"),
            operating_gate_bias_v=self.gate_bias_v,
            curve_registry_id=self.metadata.get("curve_registry_id"),
            curve_metadata_binding=self.metadata.get("binding_state"),
            source_document=self.metadata.get("source_document"),
            datasheet_revision=self.metadata.get("datasheet_revision"),
            source_figure=self.metadata.get("source_figure"),
            source_page=self.metadata.get("source_page"),
            digitization_method=self.metadata.get("digitization_method"),
            validation_method=self.metadata.get("validation_method"),
        )


@dataclass(frozen=True)
class CossLossReport:
    transition_name: str
    accounting_owner: str
    commutation_accounting_owner: str
    hysteresis_accounting_owner: str
    topology: str
    device_id: str
    device_role: str
    peer_device_id: Optional[str]
    switch_node: str
    current_direction: str
    cell_event_id: str
    waveform_start_time_s: float
    turn_on_time_s: Optional[float]
    waveform_covered_until_s: Optional[float]
    initial_vds_v: float
    final_vds_v: float
    qoss_initial_c: float
    qoss_final_c: float
    eoss_initial_j: float
    eoss_final_j: float
    eoss_stored_peak_j: float
    supplied_energy_j_per_event: float
    recovered_energy_j_per_event: float
    dissipated_commutation_j_per_event: float
    dissipated_hysteresis_j_per_event: float
    dissipated_total_j_per_event: float
    dissipated_total_j_per_cycle: float
    p_commutation_w: float
    p_hysteresis_w: float
    p_total_w: float
    p_accounted_w: float
    accounting_scope: str
    events_per_cycle: float
    device_count: int
    switching_frequency_hz: float
    destination_buckets_j_per_event: Dict[str, float]
    energy_flows_j_per_event: Tuple[Dict[str, object], ...]
    model_state: str
    curve_model_state: str
    hysteresis_model_state: str
    evidence_quality: str
    validation_status: str
    conservation_residual_j_per_event: float
    provenance: str
    conditions: Dict[str, object]
    extrapolation_flags: Tuple[str, ...]
    waveform: Tuple[Dict[str, object], ...]

    @property
    def p_bookable_w(self) -> float:
        """The power a ranking may book: ``p_accounted_w``, unless this report FAILed.

        A FAILed mechanism (impossible hysteresis calibration, broken ledger) must
        poison the ranking exactly like a missing model does — NaN — not contribute a
        physically-impossible number with a red flag in a side column. `unavailable`
        and FAIL previously behaved oppositely; this is the one accessor consumers
        book from.
        """
        if FAIL in (self.validation_status, self.evidence_quality):
            return math.nan
        return self.p_accounted_w

    def as_dict(self) -> Dict[str, object]:
        d = asdict(self)
        # Compatibility fields used by existing CSV/debug consumers. P_coss is the
        # BOOKABLE power (NaN on FAIL); the raw accounted figure stays in
        # p_accounted_w for audit.
        d["Qoss"] = self.qoss_final_c if self.qoss_final_c else self.qoss_initial_c
        d["Eoss"] = self.eoss_stored_peak_j
        d["P_coss"] = self.p_bookable_w
        return d


def unavailable_coss_report(transition: CossTransition, switching_frequency_hz: float,
                            reason: str) -> CossLossReport:
    """Machine-readable unknown result; missing Coss must never become zero loss."""
    nan = math.nan
    return CossLossReport(
        transition_name=transition.name,
        accounting_owner=transition.accounting_owner,
        commutation_accounting_owner=transition.accounting_owner,
        hysteresis_accounting_owner=transition.hysteresis_accounting_owner,
        topology=transition.topology, device_id=transition.device_id,
        device_role=transition.device_role,
        peer_device_id=transition.peer_device_id,
        switch_node=transition.switch_node,
        current_direction=transition.current_direction,
        cell_event_id=transition.cell_event_id,
        waveform_start_time_s=transition.segments[0].t0_s,
        turn_on_time_s=transition.turn_on_time_s,
        waveform_covered_until_s=transition.waveform_covered_until_s,
        initial_vds_v=transition.segments[0].v0_v,
        final_vds_v=transition.segments[-1].v1_v,
        qoss_initial_c=nan, qoss_final_c=nan,
        eoss_initial_j=nan, eoss_final_j=nan, eoss_stored_peak_j=nan,
        supplied_energy_j_per_event=nan, recovered_energy_j_per_event=nan,
        dissipated_commutation_j_per_event=nan,
        dissipated_hysteresis_j_per_event=nan,
        dissipated_total_j_per_event=nan,
        dissipated_total_j_per_cycle=nan,
        p_commutation_w=nan, p_hysteresis_w=nan, p_total_w=nan,
        p_accounted_w=nan, accounting_scope="unavailable",
        events_per_cycle=transition.events_per_cycle,
        device_count=transition.device_count,
        switching_frequency_hz=switching_frequency_hz,
        destination_buckets_j_per_event={},
        energy_flows_j_per_event=(),
        model_state=transition.model_state,
        curve_model_state="unavailable",
        hysteresis_model_state="UNVERIFIED:no-independent-calibration",
        evidence_quality=UNVERIFIED, validation_status=UNVERIFIED,
        conservation_residual_j_per_event=nan,
        provenance=reason, conditions={},
        extrapolation_flags=("coss-model-unavailable",),
        waveform=tuple(asdict(seg) for seg in transition.segments),
    )


def _validate_hysteresis(cal: CossHysteresisCalibration, *, v_low: float, v_high: float,
                         frequency_hz: float, temperature_c: Optional[float],
                         gate_bias_v: float):
    actual = dict(v_low_v=v_low, v_high_v=v_high, frequency_hz=frequency_hz,
                  temperature_c=temperature_c, gate_bias_v=gate_bias_v)
    expected = dict(v_low_v=cal.v_low_v, v_high_v=cal.v_high_v,
                    frequency_hz=cal.frequency_hz, temperature_c=cal.temperature_c,
                    gate_bias_v=cal.gate_bias_v)
    mismatches = []
    for key, want in expected.items():
        got = actual[key]
        if got is None or not _close(float(got), float(want), rel=1e-3):
            mismatches.append("%s=%r (cal %r)" % (key, got, want))
    if mismatches:
        raise ValueError("Coss hysteresis calibration condition mismatch; refusing implicit "
                         "extrapolation: " + ", ".join(mismatches))


def evaluate_coss_transition(model: CossEnergyModel, transition: CossTransition, *,
                             switching_frequency_hz: float,
                             temperature_c: Optional[float] = None,
                             gate_bias_v: float = 0.0,
                             hysteresis: Optional[CossHysteresisCalibration] = None
                             ) -> CossLossReport:
    if not _finite(switching_frequency_hz) or switching_frequency_hz <= 0:
        raise ValueError("switching frequency must be positive")

    states = []
    supplied = recovered = dissipated = 0.0
    destinations: Dict[str, float] = {}
    flows = []
    waveform = []
    own_coss = device_energy_endpoint(transition.device_id, "coss")

    for seg in transition.segments:
        a, b = model.at(seg.v0_v), model.at(seg.v1_v)
        if not states:
            states.append(a)
        states.append(b)
        de, dq = b.eoss_j - a.eoss_j, b.qoss_c - a.qoss_c
        s = r = d = 0.0
        if seg.mechanism == MECH_COMMUTATED:
            s, r = max(de, 0.0), max(-de, 0.0)
            if de > 0:
                source = seg.source
                if source is None:
                    raise ValueError("commutated Coss charging must name its energy source")
                if seg.destination != own_coss:
                    raise ValueError("commutated Coss charging destination must be %r"
                                     % own_coss)
                flows.append(dict(source=source, destination=own_coss,
                                  energy_j=de, kind="stored-transfer"))
                destinations[own_coss] = destinations.get(own_coss, 0.0) + de
            elif de < 0:
                source = seg.source or own_coss
                if source != own_coss:
                    raise ValueError("commutated Coss discharge source must be %r" % own_coss)
                flows.append(dict(source=own_coss, destination=seg.destination,
                                  energy_j=-de, kind="recovered-transfer"))
                destinations[seg.destination] = destinations.get(seg.destination, 0.0) - de
        elif seg.mechanism == MECH_CHANNEL_DISCHARGE:
            if de > 1e-18:
                raise ValueError("channel-discharge segment increases Eoss: %r" % (seg,))
            source = seg.source or own_coss
            if source != own_coss:
                raise ValueError("channel Coss discharge source must be %r" % own_coss)
            allowed = {
                device_energy_endpoint(transition.device_id, "channel"),
                device_energy_endpoint(transition.device_id, "body-diode"),
            }
            if seg.destination not in allowed:
                raise ValueError("channel/body-diode discharge destination must belong to "
                                 "the discharging device: %r" % seg.destination)
            d = -de
            if d:
                flows.append(dict(source=own_coss, destination=seg.destination,
                                  energy_j=d, kind="dissipated"))
                destinations[seg.destination] = destinations.get(seg.destination, 0.0) + d
        elif seg.mechanism == MECH_RESISTIVE_CHARGE:
            if dq < -1e-18 or de < -1e-18:
                raise ValueError("resistive-charge segment decreases Qoss/Eoss: %r" % (seg,))
            source = seg.source or ENERGY_DC_SOURCE
            s = seg.source_voltage_v * dq
            d = s - de
            if d < -1e-15:
                raise ValueError("Coss charging source voltage is below the energy trajectory")
            if de:
                flows.append(dict(source=source, destination=own_coss,
                                  energy_j=de, kind="stored"))
                destinations[own_coss] = destinations.get(own_coss, 0.0) + de
            if d:
                flows.append(dict(source=source, destination=seg.destination,
                                  energy_j=max(d, 0.0), kind="dissipated"))
                destinations[seg.destination] = destinations.get(seg.destination, 0.0) + max(d, 0.0)

        supplied += s
        recovered += r
        dissipated += max(d, 0.0)
        waveform.append(dict(
            t0_s=seg.t0_s, t1_s=seg.t1_s, initial_vds_v=seg.v0_v,
            final_vds_v=seg.v1_v, mechanism=seg.mechanism,
            source_voltage_v=seg.source_voltage_v, destination=seg.destination,
            source=seg.source,
            delta_qoss_c=dq, delta_eoss_j=de, supplied_energy_j=s,
            recovered_energy_j=r, dissipated_energy_j=max(d, 0.0),
        ))

    initial, final = states[0], states[-1]
    residual = initial.eoss_j + supplied - final.eoss_j - recovered - dissipated
    conservation_status = PASS if abs(residual) <= max(1e-15, 1e-9 * max(
        initial.eoss_j, final.eoss_j, supplied, recovered, dissipated, 1e-30)) else FAIL

    v_low = min(s.vds_v for s in states)
    v_high = max(s.vds_v for s in states)
    if hysteresis is None and transition.hysteresis_accounting_owner == OWNER_EXTERNAL:
        hyst_e = math.nan
        hyst_state = "external-owner:not-evaluated-by-fetlib"
        # The explicit term owner is the evidence needed for the handoff. Whether
        # the external model is high-fidelity is carried by transition evidence.
        hyst_quality = PASS
        hyst_provenance = "external waveform/model handoff"
    elif hysteresis is None:
        hyst_e = math.nan
        hyst_state = "UNVERIFIED:no-independent-calibration"
        hyst_quality = UNVERIFIED
        hyst_provenance = "none"
    else:
        _validate_hysteresis(hysteresis, v_low=v_low, v_high=v_high,
                             frequency_hz=switching_frequency_hz,
                             temperature_c=temperature_c, gate_bias_v=gate_bias_v)
        hyst_e = hysteresis.energy_loss_j_per_event
        hyst_state = "measured-independent-calibration"
        hyst_quality = hysteresis.evidence_quality
        hyst_provenance = hysteresis.provenance
        hyst_destination = device_energy_endpoint(transition.device_id, "coss-hysteresis")
        flows.append(dict(source=hysteresis.energy_source, destination=hyst_destination,
                          energy_j=hyst_e, kind="hysteresis-dissipated"))
        destinations[hyst_destination] = destinations.get(hyst_destination, 0.0) + hyst_e
        # A calibration claiming more loss than the full reversible energy excursion is
        # outside this lumped model's physical domain; do not award PASS merely because
        # an arbitrary source can algebraically fund it.
        if hyst_e > max(s.eoss_j for s in states) + 1e-15:
            conservation_status = FAIL

    count = transition.events_per_cycle * transition.device_count
    p_comm_physical = dissipated * switching_frequency_hz * count
    p_hyst_physical = (hyst_e * switching_frequency_hz * count
                       if hysteresis is not None else math.nan)
    total_e = dissipated + hyst_e if hysteresis is not None else math.nan
    per_cycle_e = total_e * count if hysteresis is not None else math.nan

    if transition.accounting_owner == OWNER_EXTERNAL:
        p_comm = 0.0
        comm_scope = "commutation=external-waveform:no-analytic-add-on"
        state = transition.model_state + ":commutation-external-no-analytic-add-on"
    else:
        p_comm = p_comm_physical
        comm_scope = "commutation=fetlib-analytic"
        state = transition.model_state

    if transition.hysteresis_accounting_owner == OWNER_EXTERNAL:
        p_hyst = 0.0
        hyst_scope = "hysteresis=external-waveform:no-analytic-add-on"
        p_total = p_accounted = p_comm
    elif hysteresis is None:
        p_hyst = p_total = math.nan
        p_accounted = p_comm
        hyst_scope = "hysteresis=fetlib-analytic:UNVERIFIED"
    else:
        p_hyst = p_hyst_physical
        p_total = p_accounted = p_comm + p_hyst
        hyst_scope = "hysteresis=fetlib-analytic:calibrated"
    accounting_scope = "%s;%s" % (comm_scope, hyst_scope)
    if transition.hysteresis_accounting_owner == OWNER_FETLIB and hysteresis is None:
        accounting_scope += ";known-booked-lower-bound"

    flags = tuple(model.extrapolation_flags)
    topology_quality = (PASS if transition.topology == TOPOLOGY_SYNCHRONOUS_BUCK
                        and transition.device_role in (ROLE_HS, ROLE_LS)
                        and transition.peer_device_id else UNVERIFIED)
    qualities = (model.evidence_quality, transition.evidence_quality,
                 hyst_quality, topology_quality)
    if FAIL in qualities:
        evidence = FAIL
    elif all(q == PASS for q in qualities):
        evidence = PASS
    else:
        evidence = UNVERIFIED
    validation = FAIL if conservation_status == FAIL or evidence == FAIL else evidence
    conditions = model.conditions
    conditions.update(dict(
        transition_temperature_c=temperature_c,
        transition_gate_bias_v=gate_bias_v,
        waveform_start_time_s=transition.segments[0].t0_s,
        configured_deadtime_s=(
            transition.turn_on_time_s - transition.segments[0].t0_s
            if transition.turn_on_time_s is not None else None),
        waveform_covered_until_s=transition.waveform_covered_until_s,
        commutation_accounting_owner=transition.accounting_owner,
        hysteresis_accounting_owner=transition.hysteresis_accounting_owner,
        hysteresis_provenance=hyst_provenance,
    ))

    return CossLossReport(
        transition_name=transition.name,
        accounting_owner=transition.accounting_owner,
        commutation_accounting_owner=transition.accounting_owner,
        hysteresis_accounting_owner=transition.hysteresis_accounting_owner,
        topology=transition.topology, device_id=transition.device_id,
        device_role=transition.device_role, peer_device_id=transition.peer_device_id,
        switch_node=transition.switch_node,
        current_direction=transition.current_direction,
        cell_event_id=transition.cell_event_id,
        waveform_start_time_s=transition.segments[0].t0_s,
        turn_on_time_s=transition.turn_on_time_s,
        waveform_covered_until_s=transition.waveform_covered_until_s,
        initial_vds_v=initial.vds_v,
        final_vds_v=final.vds_v,
        qoss_initial_c=initial.qoss_c,
        qoss_final_c=final.qoss_c,
        eoss_initial_j=initial.eoss_j,
        eoss_final_j=final.eoss_j,
        eoss_stored_peak_j=max(s.eoss_j for s in states),
        supplied_energy_j_per_event=supplied,
        recovered_energy_j_per_event=recovered,
        dissipated_commutation_j_per_event=dissipated,
        dissipated_hysteresis_j_per_event=hyst_e,
        dissipated_total_j_per_event=total_e,
        dissipated_total_j_per_cycle=per_cycle_e,
        p_commutation_w=p_comm,
        p_hysteresis_w=p_hyst,
        p_total_w=p_total,
        p_accounted_w=p_accounted,
        accounting_scope=accounting_scope,
        events_per_cycle=transition.events_per_cycle,
        device_count=transition.device_count,
        switching_frequency_hz=switching_frequency_hz,
        destination_buckets_j_per_event=destinations,
        energy_flows_j_per_event=tuple(flows),
        model_state=state,
        curve_model_state=model.model_state,
        hysteresis_model_state=hyst_state,
        evidence_quality=evidence,
        validation_status=validation,
        conservation_residual_j_per_event=residual,
        provenance=model.provenance,
        conditions=conditions,
        extrapolation_flags=flags,
        waveform=tuple(waveform),
    )


def validate_coss_report(report: CossLossReport, *,
                         expected_destination: Optional[str] = None) -> str:
    """Independently recompute the energy ledger and preserve three-state severity.

    Checks, beyond the five-term event identity: the power figures must reproduce the
    per-event ledger under the declared accounting owners (a zeroed or rescaled
    ``p_accounted_w`` with an intact energy quintet must not validate), and every
    destination bucket must equal the sum of the flows that claim to feed it.
    """
    if report.validation_status == FAIL or report.evidence_quality == FAIL:
        return FAIL
    terms = (
        report.eoss_initial_j, report.supplied_energy_j_per_event,
        report.eoss_final_j, report.recovered_energy_j_per_event,
        report.dissipated_commutation_j_per_event)
    if not all(_finite(value) for value in terms):
        return UNVERIFIED
    residual = (report.eoss_initial_j + report.supplied_energy_j_per_event
                - report.eoss_final_j - report.recovered_energy_j_per_event
                - report.dissipated_commutation_j_per_event)
    tolerance = max(1e-15, 1e-9 * max(*(abs(value) for value in terms), 1e-30))
    if abs(residual) > tolerance:
        return FAIL
    if not _finite(report.conservation_residual_j_per_event):
        return UNVERIFIED
    if abs(report.conservation_residual_j_per_event - residual) > tolerance:
        return FAIL

    # Power identities: energies are the source of truth, powers are derived.
    count = report.events_per_cycle * report.device_count
    f = report.switching_frequency_hz
    if not _finite(f) or f <= 0 or not _finite(count) or count <= 0:
        return UNVERIFIED
    comm_booked = (0.0 if report.commutation_accounting_owner == OWNER_EXTERNAL
                   else report.dissipated_commutation_j_per_event * f * count)
    hyst_e = report.dissipated_hysteresis_j_per_event
    hyst_booked = (0.0 if (report.hysteresis_accounting_owner == OWNER_EXTERNAL
                           or not _finite(hyst_e))
                   else hyst_e * f * count)
    if not _close(report.p_accounted_w, comm_booked + hyst_booked,
                  rel=1e-6, abs_=1e-15):
        return FAIL
    if (report.commutation_accounting_owner != OWNER_EXTERNAL
            and _finite(report.p_commutation_w)
            and not _close(report.p_commutation_w,
                           report.dissipated_commutation_j_per_event * f * count,
                           rel=1e-6, abs_=1e-15)):
        return FAIL

    # Destination buckets and flows must agree in BOTH directions — a bucket with no
    # feeding flows and a flow with no bucket entry are equally broken ledgers (the
    # one-directional check read stripped buckets as fine).
    by_dest: Dict[str, float] = {}
    for flow in report.energy_flows_j_per_event:
        dest = flow.get("destination")
        e = flow.get("energy_j")
        if dest is None or not _finite(e):
            return UNVERIFIED
        by_dest[str(dest)] = by_dest.get(str(dest), 0.0) + float(e)
    for dest in set(by_dest) | set(report.destination_buckets_j_per_event):
        if not _close(report.destination_buckets_j_per_event.get(dest, 0.0),
                      by_dest.get(dest, 0.0), rel=1e-6, abs_=1e-15):
            return FAIL

    if expected_destination is not None:
        if expected_destination not in report.destination_buckets_j_per_event:
            # A perfect event (zero dissipation, e.g. full ZVS) legitimately has no
            # bucket; absence is only a failure when there IS dissipated energy that
            # had to land somewhere. Better input must not read as a worse verdict.
            d = report.dissipated_commutation_j_per_event
            if not _finite(d) or d > 1e-15:
                return FAIL
    if (report.validation_status == UNVERIFIED
            or report.evidence_quality == UNVERIFIED):
        return UNVERIFIED
    return PASS


@dataclass(frozen=True)
class CossSwitchingCellTransition:
    """Paired HS/LS waveforms for one physical synchronous-buck cell event."""

    bus_voltage_v: float
    hs: CossTransition
    ls: CossTransition
    topology: str = TOPOLOGY_SYNCHRONOUS_BUCK

    def __post_init__(self):
        if self.topology != TOPOLOGY_SYNCHRONOUS_BUCK:
            raise ValueError("only the synchronous-buck cell contract is implemented")
        if not _finite(self.bus_voltage_v) or self.bus_voltage_v <= 0:
            raise ValueError("switching-cell bus voltage must be positive")
        if self.hs.topology != self.topology or self.ls.topology != self.topology:
            raise ValueError("cell/device topology mismatch")
        if self.hs.device_role != ROLE_HS or self.ls.device_role != ROLE_LS:
            raise ValueError("switching cell must pair one HS and one LS transition")
        if (self.hs.peer_device_id != self.ls.device_id
                or self.ls.peer_device_id != self.hs.device_id):
            raise ValueError("switching-cell device peer relationship is not reciprocal")
        if (self.hs.switch_node != self.ls.switch_node
                or self.hs.current_direction != self.ls.current_direction
                or self.hs.cell_event_id != self.ls.cell_event_id):
            raise ValueError("paired transitions disagree on node/direction/event")
        if len(self.hs.segments) != len(self.ls.segments):
            raise ValueError("paired Coss waveforms must use the same time grid")
        for h, l in zip(self.hs.segments, self.ls.segments):
            if not (_close(h.t0_s, l.t0_s) and _close(h.t1_s, l.t1_s)):
                raise ValueError("paired Coss waveform time grids differ")
            if not (_close(h.v0_v + l.v0_v, self.bus_voltage_v, rel=1e-6)
                    and _close(h.v1_v + l.v1_v, self.bus_voltage_v, rel=1e-6)):
                raise ValueError("HS/LS Vds waveforms are not complementary at the bus voltage")


@dataclass(frozen=True)
class CossSwitchingCellReport:
    topology: str
    bus_voltage_v: float
    cell_event_id: str
    current_direction: str
    hs: CossLossReport
    ls: CossLossReport
    energy_flows_j_per_event: Tuple[Dict[str, object], ...]
    cross_device_transfer_residual_j_per_event: float
    conservation_residual_j_per_event: float
    validation_status: str


def _is_cross_device_coss_flow(flow: Dict[str, object]) -> bool:
    source = _DEVICE_ENDPOINT_RE.fullmatch(str(flow.get("source", "")))
    destination = _DEVICE_ENDPOINT_RE.fullmatch(str(flow.get("destination", "")))
    return bool(source and destination
                and source.group(2) == destination.group(2) == "coss"
                and source.group(1) != destination.group(1))


def _reconcile_cell_flows(*reports: CossLossReport
                          ) -> Tuple[Tuple[Dict[str, object], ...], float]:
    """Collapse the two device-side views of each physical Coss transfer.

    A device-to-device transfer appears once as a recovered transfer in the
    discharging device ledger and once as a stored transfer in the charging
    device ledger. A cell report emits that physical transfer once, and returns
    a non-zero residual when the two independently integrated energies disagree.
    """
    ordinary = []
    cross: Dict[Tuple[str, str], list] = {}
    for report in reports:
        for flow in report.energy_flows_j_per_event:
            if _is_cross_device_coss_flow(flow):
                key = (str(flow["source"]), str(flow["destination"]))
                cross.setdefault(key, []).append(flow)
            else:
                ordinary.append(flow)

    # Match tolerance is tied to the CELL's energy scale, the same scale the caller's
    # FAIL threshold uses. A fixed absolute floor (the old 1e-12 J) silently merged ANY
    # disagreement — including 2x — once the cell's energies were small enough, so the
    # far tail could never FAIL.
    scale = max([1e-30] + [r.eoss_stored_peak_j for r in reports
                           if _finite(r.eoss_stored_peak_j)])
    mismatch = 0.0
    for (source, destination), flows in cross.items():
        discharged = [float(f["energy_j"]) for f in flows
                      if f.get("kind") == "recovered-transfer"]
        charged = [float(f["energy_j"]) for f in flows
                   if f.get("kind") == "stored-transfer"]
        discharged_total, charged_total = sum(discharged), sum(charged)
        # Sampled waveforms legitimately emit one mirrored pair per interval.
        # Reconcile the complete event transfer, not the arbitrary sample count.
        matched = (bool(discharged) and bool(charged)
                   and _close(discharged_total, charged_total,
                              rel=1e-6, abs_=1e-9 * scale))
        if matched:
            ordinary.append(dict(
                source=source, destination=destination,
                energy_j=0.5 * (discharged_total + charged_total),
                kind="cell-coss-transfer"))
        else:
            # Retain the two audit views on failure so the discrepancy remains
            # diagnosable; the non-zero residual prevents PASS.
            ordinary.extend(flows)
            mismatch += abs(discharged_total - charged_total)
            if not discharged or not charged:
                mismatch += max(discharged_total, charged_total, 1e-30)
    return tuple(ordinary), mismatch


def evaluate_coss_switching_cell(
        hs_model: CossEnergyModel, ls_model: CossEnergyModel,
        cell: CossSwitchingCellTransition, *, switching_frequency_hz: float,
        temperature_c: Optional[float] = None, gate_bias_v: float = 0.0,
        hs_hysteresis: Optional[CossHysteresisCalibration] = None,
        ls_hysteresis: Optional[CossHysteresisCalibration] = None,
        ) -> CossSwitchingCellReport:
    """Evaluate a paired cell, including complementary-waveform/topology validation."""
    hs = evaluate_coss_transition(
        hs_model, cell.hs, switching_frequency_hz=switching_frequency_hz,
        temperature_c=temperature_c, gate_bias_v=gate_bias_v,
        hysteresis=hs_hysteresis)
    ls = evaluate_coss_transition(
        ls_model, cell.ls, switching_frequency_hz=switching_frequency_hz,
        temperature_c=temperature_c, gate_bias_v=gate_bias_v,
        hysteresis=ls_hysteresis)
    flows, cross_residual = _reconcile_cell_flows(hs, ls)
    residual = (hs.conservation_residual_j_per_event
                + ls.conservation_residual_j_per_event + cross_residual)
    if (hs.validation_status == FAIL or ls.validation_status == FAIL
            or cross_residual > max(1e-15, 1e-9 * max(
                hs.eoss_stored_peak_j, ls.eoss_stored_peak_j, 1e-30))):
        status = FAIL
    elif hs.validation_status == PASS and ls.validation_status == PASS:
        status = PASS
    else:
        status = UNVERIFIED
    return CossSwitchingCellReport(
        topology=cell.topology, bus_voltage_v=cell.bus_voltage_v,
        cell_event_id=cell.hs.cell_event_id,
        current_direction=cell.hs.current_direction,
        hs=hs, ls=ls,
        energy_flows_j_per_event=flows,
        cross_device_transfer_residual_j_per_event=cross_residual,
        conservation_residual_j_per_event=residual,
        validation_status=status,
    )


def buck_hard_switching_cell(bus_voltage_v: float, *,
                             evidence_quality: str = UNVERIFIED,
                             current_direction: str = CURRENT_SOURCE_TO_LOAD,
                             accounting_owner: str = OWNER_FETLIB,
                             hysteresis_accounting_owner: str = OWNER_FETLIB
                             ) -> CossSwitchingCellTransition:
    """The paired hard HS-turn-on event used by the per-slot compatibility helpers."""
    return CossSwitchingCellTransition(
        bus_voltage_v=bus_voltage_v,
        hs=buck_hs_hard_transition(
            bus_voltage_v, evidence_quality=evidence_quality,
            current_direction=current_direction,
            accounting_owner=accounting_owner,
            hysteresis_accounting_owner=hysteresis_accounting_owner),
        ls=buck_ls_hard_transition(
            bus_voltage_v, evidence_quality=evidence_quality,
            current_direction=current_direction,
            accounting_owner=accounting_owner,
            hysteresis_accounting_owner=hysteresis_accounting_owner),
    )


def scale_coss_report_dict(report: Dict[str, object], multiplier: int) -> Dict[str, object]:
    """Scale a serialized report for parallel devices while retaining per-device energy."""
    if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 0:
        raise ValueError("Coss report multiplier must be a positive integer")
    if multiplier == 1:
        return dict(report)
    d = dict(report)
    d["device_count"] = int(d.get("device_count", 1)) * multiplier
    for key in ("dissipated_total_j_per_cycle", "p_commutation_w",
                "p_hysteresis_w", "p_total_w", "p_accounted_w", "P_coss"):
        value = d.get(key)
        if isinstance(value, (int, float)):
            d[key] = value * multiplier
    return d


def coss_audit_json(report) -> str:
    """Serialize a report (or namespaced reports) as strict, round-trippable JSON.

    Unknown numeric results are represented as JSON ``null`` rather than the
    non-standard JavaScript tokens NaN/Infinity. This is the production CSV escape
    hatch for the full audit trail; the compact columns remain search conveniences.
    """
    def safe(value):
        if isinstance(value, dict):
            return {str(k): safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    return json.dumps(safe(report), sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def buck_hs_hard_transition(bus_voltage_v: float, *,
                            events_per_cycle: float = 1.0,
                            accounting_owner: str = OWNER_FETLIB,
                            hysteresis_accounting_owner: str = OWNER_FETLIB,
                            evidence_quality: str = UNVERIFIED,
                            device_id: str = "hs",
                            peer_device_id: str = "ls",
                            current_direction: str = CURRENT_SOURCE_TO_LOAD) -> CossTransition:
    """Default buck HS: its stored Eoss is discharged in its own channel at turn-on."""
    return CossTransition.from_points(
        "buck-hs-turn-on", ((0.0, bus_voltage_v), (1.0, 0.0)),
        mechanism=MECH_CHANNEL_DISCHARGE,
        destination=device_energy_endpoint(device_id, "channel"),
        source=device_energy_endpoint(device_id, "coss"),
        events_per_cycle=events_per_cycle, accounting_owner=accounting_owner,
        hysteresis_accounting_owner=hysteresis_accounting_owner,
        model_state="hard-switch-default", evidence_quality=evidence_quality,
        topology=TOPOLOGY_SYNCHRONOUS_BUCK, device_id=device_id,
        device_role=ROLE_HS, peer_device_id=peer_device_id,
        current_direction=current_direction,
        cell_event_id="buck-high-side-turn-on",
    )


def buck_ls_hard_transition(bus_voltage_v: float, *,
                            events_per_cycle: float = 1.0,
                            accounting_owner: str = OWNER_FETLIB,
                            hysteresis_accounting_owner: str = OWNER_FETLIB,
                            evidence_quality: str = UNVERIFIED,
                            device_id: str = "ls",
                            peer_device_id: str = "hs",
                            current_direction: str = CURRENT_SOURCE_TO_LOAD) -> CossTransition:
    """Default buck LS attribution: charge is supplied through the commutating HS."""
    return CossTransition.from_points(
        "buck-ls-charge", ((0.0, 0.0), (1.0, bus_voltage_v)),
        mechanism=MECH_RESISTIVE_CHARGE,
        destination=device_energy_endpoint(peer_device_id, "channel"),
        source=ENERGY_DC_SOURCE,
        source_voltage_v=bus_voltage_v, events_per_cycle=events_per_cycle,
        accounting_owner=accounting_owner,
        hysteresis_accounting_owner=hysteresis_accounting_owner,
        model_state="hard-switch-default",
        evidence_quality=evidence_quality,
        topology=TOPOLOGY_SYNCHRONOUS_BUCK, device_id=device_id,
        device_role=ROLE_LS, peer_device_id=peer_device_id,
        current_direction=current_direction,
        cell_event_id="buck-high-side-turn-on",
    )
