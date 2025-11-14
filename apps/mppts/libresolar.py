import maglib.cores
from dclib.powerloss import CoilSpecs
from dslib.field import MpnMfr
from dslib.mosfet import MosfetSpecs, MosfetSlot
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
                     # core=dslib.magnetics.cores.Micrometals_MS_184_090,
                     )

    coil = CoilSpecs(Rdc=2.4e-3,
                     L0=65e-6,
                     turns=18.0,
                     wire_diameter=2.0e-3,
                     # core=dslib.magnetics.cores.Micrometals_MS_184_125,
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
                     # core=dslib.magnetics.cores.Micrometals_MS_184_125,
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
    # fet_ho._Vpl = 5.4
    # fet_ho.Qg_th = 8e-9
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
    sync_fet: Part = dslib.store.parts_db.load_obj(MpnMfr('infineon', 'IPP022N12NM6AKSA1'))

    # KS184-125A-d1.18-s10-n12
    coil = CoilSpecs(
        Rdc=2.43e-3,  # measured
        L0=281e-9 * 2 * 12 ** 2,  # from datasheet
        turns=12,
        wire_awg=16.8, wire_strands=10,
        # core=dslib.magnetics.cores.KDM_KS184_125A.stack(2),
        core=maglib.cores.Micrometals_MS_184_125.stack(2),
    )

    class Capacitor(Part):
        def __init__(self, mfn, mpn, C, V, Z):
            super().__init__(mpn, mfn)
            self.mfn = mfn
            self.mpn = mpn
            self.C = C
            self.V = V
            self.Z = Z

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
        cin_imp=33e-3 / 4,  # rubycon 470u 100v ZLH
        cout_imp=32e-3,
        # TODO Cin,Cout!
    )

    return buck


def Fugu2_lab_ipp_rtime_rr():
    import dslib.store

    ctrl_mpn = MpnMfr('infineon', 'IPP055N08NF2SAKMA1')

    ctrl_fet: Part = dslib.store.parts_db.load_obj(ctrl_mpn)
    sync_fet: Part = dslib.store.parts_db.load_obj(MpnMfr('infineon', 'IPP024N08NF2S'))

    # KS184-125A-d1.18-s10-n12
    coil = CoilSpecs(
        Rdc=3e-3,  # TODO measure
        L0=47e-6,  # measured with LCR meter (@150khz, Q=150)
        #turns=22, # TODO
        wire_awg=16.8, # TODO
        wire_strands=2, # TODO
        core=maglib.cores.Micrometals_MS_130_060.stack(2),
    )

    buck = BuckConverter(
        name='Fugu2_lab_ipp_rtime_rr',
        Io_max=40,
        f_sw=39e3,
        coil=coil,
        hs=MosfetSlot(ctrl_fet.specs, 15, parallel=2),
        ls=MosfetSlot(sync_fet.specs, 15),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=1e-3,  # current sense resistor
            R_rpcb=1.5e-3,
            R_fuse=1.6e-3,  # 40A fuse
        ),
        cin_imp=33e-3 / 4,  # rubycon 470u 100v ZLH TODO
        cout_imp=32e-3, # TODO
    )

    return buck


def Fugu2_banana():
    import dslib.store

    #ctrl_mpn = MpnMfr('infineon', 'IRF100B201')
    # MpnMfr('ti', 'CSD19505KCS')

    ctrl_mpn = MpnMfr('infineon', 'IPP055N08NF2S')
    sync_mpn = MpnMfr('infineon', 'IPP019N08NF2S')

    ctrl_fet: Part = dslib.store.parts_db.load_obj(ctrl_mpn)
    sync_fet: Part = dslib.store.parts_db.load_obj(sync_mpn)

    coil = CoilSpecs(
        # Ruishen RSEQ32-470M
        # https://www.lcsc.com/datasheet/C37634010.pdf
        Rdc=3.5e-3,  # ds says 3.0mΩ(typ) 4.5(max), hp3458a 4w: 3.55mΩ, 5A test: 3.46mΩ
        L0=48e-6, # 47
        turns=19,
        wire_awg=16.8, # n/a
        wire_strands=1, # n/a
        core=maglib.cores.MicrometalsToroid('MS', 60, maglib.cores.MicrometalsT184),#, Micrometals_MS_184_060# .stack(2), # TODO n/a
    )

    buck = BuckConverter(
        name='Fugu2_banana',
        Io_max=40,
        f_sw=39e3,
        coil=coil,
        hs=MosfetSlot(ctrl_fet.specs,
                      rg_total=4.7+2.2, # IRF100B201 rg=2.2
                      rg_total_dis=2.2,
                      parallel=2),
        ls=MosfetSlot(sync_fet.specs,
                      rg_total=4.7),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=1.5e-3,  # current sense resistor
            R_rpcb=1.5e-3,
            R_fuse=0.0e-3,  # bridged
        ),
        cin_imp=33e-3 / 2,  # rubycon 470u 100v ZLH
        cout_imp=33e-3, # TODO
    )

    return buck


def Fugu2_tall():
    import dslib.store

    # inf 2p IPP055N08NF2S?  # IPP019N08NF2S ?
    ctrl_mpn = MpnMfr('infineon', 'IPA050N10NM5S')
    sync_mpn = MpnMfr('infineon', 'IPP039N10N5') # TODO verify

    ctrl_fet: Part = dslib.store.parts_db.load_obj(ctrl_mpn)
    sync_fet: Part = dslib.store.parts_db.load_obj(sync_mpn)

    coil = CoilSpecs(
        Rdc=3.05e-3,
        L0=69e-6, # 47
        turns=14,
        wire_awg=16.8,
        wire_strands=9, # n/a
        core=maglib.cores.MicrometalsToroid('MS', 75, maglib.cores.MicrometalsT184).stack(2),
    )

    buck = BuckConverter(
        name='Fugu2_tall',
        Io_max=40,
        f_sw=80e3, # todo?
        coil=coil,
        hs=MosfetSlot(ctrl_fet.specs,
                      rg_total=4.7+1.2,
                      #rg_total_dis=1.5+1.2,
                      parallel=2),
        ls=MosfetSlot(sync_fet.specs,
                      rg_total=4.7+2.1, #
                      parallel=2),
        output_parasitics=dict(
            # P_mcu=0.7,
            R_csr=0.5e-3,  # current sense resistor
            R_rpcb=1.5e-3,
            R_fuse=1.5e-3,
        ),
        cin_imp=33e-3 / 2,  # rubycon 470u 100v ZLH, ZLJ:32mΩ
        cout_imp=33e-3, # TODO
    )

    return buck
