from dslib import rel_err
from dslib.spec_models import DcDcLoadParams
from maglib import cores
from maglib.materials import KDM_SendustKS_60, MagInc_KoolMu_60, Micrometals_Sendust_60u


def test_mat():
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=10), 98 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=60), 70 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=100), 46 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=200), 21 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=1000), 1.5 / 100)) < 0.05

    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=10) - 0.05) < 0.012
    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=50) - 0.3) < 0.01
    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=100) - 0.53) < 0.01

    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=10) - .98) < 0.01
    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=100) - .5) < 0.01
    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=1000) - .01) < 0.01

    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=400e-4, f_khz=50) - 50) < 1
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=1000e-4, f_khz=50) - 323) < 10  # from table
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=5000e-4, f_khz=50) - 7125) < 100
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=100e-4, f_khz=500) - 90) < 5
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=1000e-4, f_khz=500) - 9500) < 500

    assert abs(Micrometals_Sendust_60u.dc_magnetization(H_oe=50) - 2800e-4) < 100e-4
    assert abs(Micrometals_Sendust_60u.dc_magnetization(H_oe=100) - 4900e-4) < 100e-4

    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.06, f_khz=50) - 70) < 5
    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.1, f_khz=50) - 190) < 5  # pg 124
    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.06, f_khz=100) - 200) < 1

    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=10) - 0.05) < 0.01
    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=50) - 0.28) < 0.01  # pg 124
    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=100) - 0.45) < 0.01  # pg 124


def test_power_loss():
    import maglib.cores as cores

    from dclib.powerloss import CoilSpecs
    coil = CoilSpecs(Rdc=0, turns=20, core=cores.MagInc_106_KoolMu60)

    # https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
    # method 1
    from maglib.powerloss import core_loss_from_dc_magnetization
    from maglib.powerloss import core_loss_from_dc_bias  # method 2

    # example 1: 20A DC, 2A ripple, 100 khz
    dcdc = DcDcLoadParams(85, 6.5, 100e3, io=20, iripple=2)
    assert abs(rel_err(dcdc.L, coil.L0)) < 0.1
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 44e-3)) < 0.05  # method 1
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 44e-3)) < 0.05  # method 2

    # example 2: 20A DC, 8A ripple, 100 khz
    dcdc = DcDcLoadParams(100, 60, 100e3, io=20, iripple=8)
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 692e-3)) < 0.05
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 708e-3)) < 0.05

    # example 3: 0A DC, 8A ripple, 100 khz
    dcdc = DcDcLoadParams(100, 60, 100e3, io=0, iripple=8)
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 1920e-3)) < 0.05
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 2062e-3)) < 0.05


def test_coil():
    from dclib.powerloss import CoilSpecs
    coil = CoilSpecs(Rdc=0, turns=20, core=cores.MagInc_106_KoolMu60, wire_awg=15, wire_strands=10)
    assert abs(rel_err(coil.wire_diameter, 1.45e-3)) < 0.01
    assert abs(rel_err(coil.bundle_diameter, 4.59e-3)) < 0.01


def test_wire():
    from dslib import rel_err


    from maglib.wire import d2awg, awg2d
    for i in range(1000):
        import random
        x = random.random() * 10

        assert abs(rel_err(awg2d(d2awg(x)), x)) < 1e-9
        assert abs(rel_err(d2awg(awg2d(x)), x)) < 1e-9


    from maglib.wire import skin_depth, dc_resistance, ac_resistance, ac_resistance_factor

    assert abs(rel_err(skin_depth(1.72e-8, f=50), 9.335e-3)) < 1e-4
    assert abs(rel_err(skin_depth(1.72e-8, f=50, mu_r=2), 6.601e-3)) < 1e-4

    from maglib.wire import MaterialResistivity
    res = MaterialResistivity.Copper.value
    from maglib.wire import awg2d
    d = awg2d(14)

    rdc = dc_resistance(res, 1, d)
    assert abs(rel_err(rdc, 8.1e-3)) < 0.01

    rac = ac_resistance(res, 1, d, 50e3)[0]
    assert abs(rel_err(rac, 13.7e-3)) < 0.01

    acf, sd = ac_resistance_factor(res, d, 50e3)
    assert abs(rel_err(rac, acf * rdc)) < 0.01

    # example from https://s3.amazonaws.com/micrometals-production/filer_public/7c/72/7c728863-9c0e-40b3-ba86-a3f94d5ad1c1/acresistance_rev0_110123.pdf
    from maglib.wire import acr_factor_micrometals
    assert abs(rel_err(2.5060, sum(acr_factor_micrometals(23e-9, 1e-3, 100e3, 1, 32, 14.1e-3, 27.69e-3)))) < 1e-4

    acr_factor_micrometals()

    ac_resistance_factor(23e-9, 1e-3, 100e3)

    for d in [0.7e-3, 1.0e-3, 1.2e-3, 1.5e-3, 2e-3]:
        for f in [20e3, 40e3, 100e3, 200e3]:
            a = ac_resistance_factor(23e-9, d, f)[0]
            b = acr_factor_micrometals(23e-9, d, f, 1, 32, 14.1e-3, 27.69e-3)[0]
            assert abs(rel_err(a, b)) < 0.07
