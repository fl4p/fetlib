from dslib.field import MpnMfr
from dclib.powerloss import CoilSpecs
from dslib.spec_models import BuckConverter
from dslib.mosfet import MosfetSpecs, MosfetSlot
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
        #core =dslib.magnetics.cores.MicrometalsToroid('MS', 60, 130).stack(2),
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


def FuguHeat2():
    import dslib.store

    """
    Picks
    SUM60020E vishay
    TK6R8A08QM toshiba (switch) Q_sw=13nC
    CSD19506KCS ti (sync)    
    IPP052N08N5AKSA1 infineon (switch) Q_sw=16nC
    CSD19503KCS (switch)
    """

    coil = CoilSpecs(Rdc=6.2e-3,
                     L0=47.3e-6,
                     turns=19.5,
                     core=dslib.magnetics.cores.KDM_KS130_060A.stack(2),
                     # core=dslib.magnetics.cores.Micrometals_OE_130_060.stack(2),
                     # core=dslib.magnetics.cores.Micrometals_MS_130_060.stack(2),
                     # core=dslib.magnetics.cores.Micrometals_OE_226_060,

                     )

    coil = CoilSpecs(Rdc=2.4e-3,
                     L0=65e-6,
                     turns=15.0,
                     wire_diameter=2.0e-3,
                     core=dslib.magnetics.cores.Micrometals_MS_184_125,
                     #core=dslib.magnetics.cores.Micrometals_MS_184_090,
                     )

    coil = CoilSpecs(Rdc=2.4e-3,
                     L0=65e-6,
                     turns=18.0,
                     wire_diameter=2.0e-3,
                     #core=dslib.magnetics.cores.Micrometals_MS_184_125,
                     core=dslib.magnetics.cores.Micrometals_MS_184_090,
                     )

    # coil = CoilSpecs(Rdc=2.4e-3,
    #                 L0=65e-6,
    #                 turns=18.0,
    #                 core=dslib.magnetics.cores.Micrometals_MS_184_090,
    #                 )

    # ds_ho = parse_datasheet('datasheets/ti/CSD19501KCS.pdf')
    # ds_ho.add(Field('Rds_on_10v', math.nan, 5.5e-3, 6.5e-3))

    # fet_mpn = MpnMfr('toshiba', 'TK6R8A08QM')
    # fet_ho: Part = dslib.store.parts_db.load_obj(fet_mpn)

    # from dslib.pdf2txt.parse import parse_datasheet
    # ds_lo = parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', mfr='onsemi')
    # ds_lo.add(Field('Rds_on_10v', math.nan, 2.21e-3, 2.7e-3))
    # fet_lo = ds_lo.get_mosfet_specs()

    # fet_lo: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs
    # fet_ho: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs

    # fet_ho: MosfetSpecs = parse_datasheet('datasheets/vishay/SiRA04DP.pdf').get_mosfet_specs()
    # fet_ho._Vpl = 2.6

    fet_ho = MosfetSpecs.from_mpn('TK6R8A08QM', mfr='toshiba')
    fet_ho._Vpl = 5.4
    fet_ho.Qg_th = 8e-9
    fet_lo = MosfetSpecs.from_mpn('FDP027N08B', mfr='onsemi')

    # fet_mpn = MpnMfr('infineon', 'IPA045N10N3GXKSA1')
    # fet: Part = dslib.store.parts_db.load_obj(fet_mpn)

    # winding = Winding(MaterialResistivity.CopperAnnealed, awg=27, turns=21, l=7.56e-2, strands=40)
    # https://www.micrometals.com/design-and-applications/design-tools/inductor-analyzer/
    # coil = CoilSpecs(
    #    Rdc=8.1e-3,  # from micrometals analyzer
    #    L0=55e-6,
    #    turns=21,
    #    core=dslib.magnetics.cores.Micrometals_MS_130_060.stack(2),
    # )

    buck = BuckConverter(
        name='FuguHeat184',
        Io_max=30,
        f_sw=80e3,
        coil=coil,
        hs=MosfetSlot(fet_ho, 22, parallel=2),
        ls=MosfetSlot(fet_lo, 3.3),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=1e-3,  # current sense resistor (burden, shunt)
            R_rpcb=1e-3,
            R_fuse=1.5e-3,  # 20A fuse
            R_bflow=.75e-3,
        )
    )

    return buck


def FuguWhite184():
    import dslib.store

    """
    Picks
    SUM60020E vishay
    TK6R8A08QM toshiba (switch) Q_sw=13nC
    CSD19506KCS ti (sync)    
    IPP052N08N5AKSA1 infineon (switch) Q_sw=16nC
    CSD19503KCS (switch)
    """

    coil = CoilSpecs(Rdc=2.4e-3,
                     L0=65e-6,
                     turns=18.0,
                     wire_diameter=2.0e-3,
                     #core=dslib.magnetics.cores.Micrometals_MS_184_125,
                     core=dslib.magnetics.cores.Micrometals_MS_184_090,
                     )

    # coil = CoilSpecs(Rdc=2.4e-3,
    #                 L0=65e-6,
    #                 turns=18.0,
    #                 core=dslib.magnetics.cores.Micrometals_MS_184_090,
    #                 )

    # ds_ho = parse_datasheet('datasheets/ti/CSD19501KCS.pdf')
    # ds_ho.add(Field('Rds_on_10v', math.nan, 5.5e-3, 6.5e-3))

    # fet_mpn = MpnMfr('toshiba', 'TK6R8A08QM')
    # fet_ho: Part = dslib.store.parts_db.load_obj(fet_mpn)

    # from dslib.pdf2txt.parse import parse_datasheet
    # ds_lo = parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', mfr='onsemi')
    # ds_lo.add(Field('Rds_on_10v', math.nan, 2.21e-3, 2.7e-3))
    # fet_lo = ds_lo.get_mosfet_specs()

    # fet_lo: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs
    # fet_ho: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs

    # fet_ho: MosfetSpecs = parse_datasheet('datasheets/vishay/SiRA04DP.pdf').get_mosfet_specs()
    # fet_ho._Vpl = 2.6

    fet_ho = MosfetSpecs.from_mpn('IPP040N08NF2SAKMA1', mfr='infineon')
    #fet_ho._Vpl = 5.4
    #fet_ho.Qg_th = 8e-9
    fet_lo = MosfetSpecs.from_mpn('FDP027N08B', mfr='onsemi')

    # fet_mpn = MpnMfr('infineon', 'IPA045N10N3GXKSA1')
    # fet: Part = dslib.store.parts_db.load_obj(fet_mpn)

    # winding = Winding(MaterialResistivity.CopperAnnealed, awg=27, turns=21, l=7.56e-2, strands=40)
    # https://www.micrometals.com/design-and-applications/design-tools/inductor-analyzer/
    # coil = CoilSpecs(
    #    Rdc=8.1e-3,  # from micrometals analyzer
    #    L0=55e-6,
    #    turns=21,
    #    core=dslib.magnetics.cores.Micrometals_MS_130_060.stack(2),
    # )

    buck = BuckConverter(
        name='FuguHeat184',
        Io_max=30,
        f_sw=80e3,
        coil=coil,
        hs=MosfetSlot(fet_ho, 22, parallel=2),
        ls=MosfetSlot(fet_lo, 3.3),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=1e-3,  # current sense resistor (burden, shunt)
            R_rpcb=1e-3,
            R_fuse=1.5e-3,  # 20A fuse
            R_bflow=.75e-3,
        )
    )

    return buck



def MPPT_Fheat2():
    import dslib.store

    ctrl_mpn = MpnMfr('infineon', 'IPP055N08NF2SAKMA1')

    ctrl_fet: Part = dslib.store.parts_db.load_obj(ctrl_mpn)
    sync_fet:Part = dslib.store.parts_db.load_obj(MpnMfr('infineon', 'IPP022N12NM6AKSA1'))

    # KS184-125A-d1.18-s10-n12
    coil = CoilSpecs(
        Rdc=2.43e-3, # measured
        L0=281e-9 * 2 * 12 ** 2, # from datasheet
        turns=12,
        wire_awg=16.8, wire_strands=10,
        # core=dslib.magnetics.cores.KDM_KS184_125A.stack(2),
        core=dslib.magnetics.cores.Micrometals_MS_184_125.stack(2),
    )

    buck = BuckConverter(
        name='Fugu2',
        Io_max=40,
        f_sw=39e3,
        coil=coil,
        hs=MosfetSlot(ctrl_fet.specs, 4.7, parallel=2),
        ls=MosfetSlot(sync_fet.specs, 4.7),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=.5e-3,  # current sense resistor (burden, shunt)
            R_rpcb=1.5e-3,
            R_fuse=1.6e-3,  # 40A fuse
        ),
        cin_imp=33e-3/4, # rubycon 470u 100v ZLH
        cout_imp=32e-3,
        # TODO Cin,Cout!
    )

    return buck