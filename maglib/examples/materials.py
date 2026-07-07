
def _main():
    import maglib.plot as plot
    materials = [
        Micrometals_Sendust_60u,
        Micrometals_OE_60u,
        MagInc_KoolMu_60,
        KDM_SendustKS_60
    ]
    plot.core_loss_density_curves(materials, f_khz=40)
    plot.dc_bias_curves(materials)
    plot.dc_magnetization_curves(materials)


if __name__ == '__main__':
    _main()
