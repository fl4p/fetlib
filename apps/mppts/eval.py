import dslib.store
import maglib.cores
from dclib.powerloss import CoilSpecs
from dslib.field import MpnMfr
from dslib.mosfet import MosfetSlot
from dslib.spec_models import BuckConverter
from dslib.store import Part


def EPC90133():
    import dslib.store

    fet_mpn = MpnMfr('epc', 'EPC2302')
    fet: Part = dslib.store.parts_db.load_obj(fet_mpn)

    coil = CoilSpecs(
        Rdc=5e-3,
        # L0=55e-6,
        turns=20,
        wire_strands=2,
        wire_awg=27,
        core=maglib.cores.Micrometals_MS_130_060.stack(2),
        # core =dslib.magnetics.cores.MicrometalsToroid('MS', 60, 130).stack(2),
    )

    # https://epc-co.com/epc/portals/0/epc/documents/schematics/EPC90133_Schematic.pdf#page=2
    # driver: https://epc-co.com/epc/Portals/0/epc/documents/datasheets/uP1966E_datasheet.pdf

    fet_slot = MosfetSlot(fet.specs,
                          rg_total=0.7 + 1 + 0.5,  # driver + resistor + fet gate resistance
                          rg_total_dis=0.4 + 0 + 0.5,
                          )

    buck = BuckConverter(
        name='EPC90133_buck',
        Io_max=40,
        f_sw=100e3,
        coil=coil,
        hs=fet_slot,
        ls=fet_slot,
        output_parasitics=dict(
            # P_mcu=0.7,
            # R_csr=0.2e-3,  # current sense resistor (burden, shunt)
            # R_rpcb=1e-3,
            # R_fuse=2e-3,  # 20A fuse
        )
    )

    return buck
