from dclib.powerloss import CoilSpecs
from dslib.field import MpnMfr
from dslib.mosfet import MosfetSlot
from dslib.spec_models import BuckConverter
from dslib.store import Part


def LibreSolar_MPPT_2420_HC():
    import dslib.store

    fet_mpn = MpnMfr('infineon', 'IPA045N10N3GXKSA1')

    fet: Part = dslib.store.parts_db.load_obj(fet_mpn)

    # winding = Winding(MaterialResistivity.CopperAnnealed, awg=27, turns=21, l=7.56e-2, strands=40)
    # https://www.micrometals.com/design-and-applications/design-tools/inductor-analyzer/
    coil = CoilSpecs(
        Rdc=8.1e-3,  # from micrometals analyzer (40xAWG27), mean turn len 7.56cm
        L0=55e-6,
        turns=21,
        wire_awg=27,
        core=dslib.magnetics.cores.Micrometals_MS_130_060.stack(2),
        # core =dslib.magnetics.cores.MicrometalsToroid('MS', 60, 130).stack(2),
    )

    # coil.micrometals_analyzer()

    buck = BuckConverter(
        name='LibreSolar_MPPT_2420_HC',
        Io_max=22,
        f_sw=70e3,
        coil=coil,
        hs=MosfetSlot(fet.specs, 3.3),
        ls=MosfetSlot(fet.specs, 3.3),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=2e-3,  # current sense resistor (burden, shunt)
            R_rpcb=1e-3,
            R_fuse=2e-3,  # 20A fuse
        )
    )

    return buck



