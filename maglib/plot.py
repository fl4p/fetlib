import warnings
from typing import List, Union

import pandas as pd
from matplotlib import pyplot as plt

from maglib import oe2Apm, µ0
from maglib.materials import MagneticCoreMaterialSpecs


# TODO
"""
- this file needs some cleanup
- remove redundant functions
- normalise names
"""


def plot_dc_bias_curve(mat: Union[List[MagneticCoreMaterialSpecs], MagneticCoreMaterialSpecs],
                       interactive=False):
    if isinstance(mat, MagneticCoreMaterialSpecs):
        mat = [mat]

    for m in mat:
        H_oe = 1

        points = dict()

        while H_oe < 2000:
            ui_pct = m.dc_bias(H_oe=H_oe) * 100
            points[H_oe] = ui_pct
            H_oe *= 1.3

        s = pd.Series(points)

        if len(mat) == 1:
            s.plot()
            plt.title('DC Bias curve `%s %s` (%dµ)' % (m.mfr, m.mpn, m.mu_r))
        else:
            s.plot(label='%s %s (%dµ)' % (m.mfr, m.mpn, m.mu_r))

    plt.xlabel('H - DC Magnetizing Force (Oe)')  # r'$B_\odot$')
    plt.ylabel(r'% - Initial Permeability (%$µ_i$)')
    plt.semilogx()
    plt.grid()
    if len(mat) > 1:
        plt.legend(loc='best')

    if interactive:
        import mpld3
        from mpld3._server import serve
        serve(mpld3.fig_to_html(plt.gcf()))
    else:
        plt.show()


def dc_bias_curves(mats: List[MagneticCoreMaterialSpecs]):
    for mat in mats:
        H_oe = 1

        points = dict()

        while H_oe < 2000:
            ui_pct = mat.dc_bias(H_oe=H_oe) * 100
            points[H_oe] = ui_pct
            H_oe *= 1.3

        s = pd.Series(points)
        s.plot(label='%s %s %dµ' % (mat.mfr, mat.mpn, mat.mu_r))
    plt.title('DC Bias curve')
    plt.semilogx()
    plt.xlabel('H - DC Magnetizing Force (Oe)')  # r'$B_\odot$')
    plt.ylabel(r'% - Initial Permeability (%$µ_i$)')
    plt.grid()
    plt.legend(loc='best')
    plt.show()


def plot_dc_magnetization_curve_BH(mat: MagneticCoreMaterialSpecs):
    warnings.warn("this curve is non-standard plot")

    H_oe = 1

    points = dict()

    while H_oe < 1000:
        H = oe2Apm(H_oe)
        B_tesla = µ0 * mat.mu_r * mat.dc_bias(H_oe=H_oe) * H
        points[H_oe] = B_tesla
        H_oe *= 1.3

    s = pd.Series(points)
    s.plot()
    plt.title('DC Bias curve %s %s µi=%d' % (mat.mfr, mat.mpn, mat.mu_r))
    plt.semilogx()
    plt.xlabel('H - Magnetizing Force (Oe)')  # r'$B_\odot$')
    plt.ylabel('B - Flux Density (Tesla)')
    plt.grid()
    plt.show()
    return s


def plot_dc_magnetization_curve(mat: MagneticCoreMaterialSpecs):
    H_oe = 1

    points = dict()

    while H_oe < 1000:
        B_tesla = mat.dc_magnetization(H_oe=H_oe)
        points[H_oe] = B_tesla
        H_oe *= 1.3

    s = pd.Series(points)
    s.plot()
    plt.title('DC Magnetization curve %s %s %dµ' % (mat.mfr, mat.mpn, mat.mu_r))
    plt.semilogx()
    plt.xlabel('H - Magnetizing Force (Oe)')  # r'$B_\odot$')
    plt.ylabel('Bpk - Flux Density (Tesla)')
    plt.grid()
    plt.show()
    return s


def dc_magnetization_curves(mats: List[MagneticCoreMaterialSpecs]):
    for mat in mats:
        H_oe = 1

        points = dict()

        while H_oe < 1000:
            B_tesla = mat.dc_magnetization(H_oe=H_oe)
            points[H_oe] = B_tesla
            H_oe *= 1.3

        s = pd.Series(points)
        s.plot(label='%s %s %dµ' % (mat.mfr, mat.mpn, mat.mu_r))

    plt.title('DC Magnetization curve')
    plt.semilogx()
    plt.xlabel('H - Magnetizing Force (Oe)')  # r'$B_\odot$')
    plt.ylabel('Bpk - Flux Density (Tesla)')
    plt.grid()
    plt.legend(loc='best')
    plt.show()


def plot_core_loss_density_curve(mat: Union[MagneticCoreMaterialSpecs, List[MagneticCoreMaterialSpecs]], f_khz):
    Bpk_tesla = 10e-4

    if isinstance(mat, MagneticCoreMaterialSpecs):
        mat = [mat]

    for m in mat:
        points = dict()
        while Bpk_tesla < 1:
            points[Bpk_tesla * 1e4] = m.core_loss_density(Bpk_tesla=Bpk_tesla, f_khz=f_khz)
            Bpk_tesla *= 1.3

        s = pd.Series(points)
        s.plot(label='%d kHz' % f_khz)

    plt.title('Core Loss vs Bpk - %s %s %dµ' % (mat.mfr, mat.mpn, mat.mu_r))
    plt.semilogx()
    plt.semilogy()
    plt.xlabel('$B_{pk}$ - Peak AC Flux Density (gauss)')  # r'')\odot
    plt.ylabel('Core Loss (mW/cm3)')
    plt.ylim((10, 10e3))
    plt.grid()
    plt.legend(loc='best')
    plt.show()
    return s


def core_loss_density_curves(mat: List[MagneticCoreMaterialSpecs], f_khz):
    if isinstance(mat, MagneticCoreMaterialSpecs):
        mat = [mat]

    for m in mat:
        points = dict()
        Bpk_tesla = 10e-4
        while Bpk_tesla < 1:
            points[Bpk_tesla * 1e4] = m.core_loss_density(Bpk_tesla=Bpk_tesla, f_khz=f_khz)
            Bpk_tesla *= 1.3

        s = pd.Series(points)
        s.plot(label='%s %s %uµ' % (m.mfr, m.mpn, m.mu_r))

    plt.title('Core Loss vs Bpk @%d kHz' % (f_khz))
    plt.semilogx()
    plt.semilogy()
    plt.xlabel('$B_{pk}$ - Peak AC Flux Density (gauss)')  # r'')\odot
    plt.ylabel('Core Loss (mW/cm3)')
    plt.ylim((10, 10e3))
    plt.grid()
    plt.legend(loc='best')
    plt.show()
