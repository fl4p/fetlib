"""Datasheet reverse-recovery rows for parts quoting Qrr at MULTIPLE di/dt
points, keyed by (mfr, mpn) — GENERATED, do not edit by hand:

    python3 unit/validate_qrr_didt_datasheets.py --emit-points dslib/qrr_points.py

Extraction is the geometry parser validated in that script (typ values,
all rows Tj=25 C). Package/order-code variants are listed as their own
keys. Used for per-part two-point (tau, TM, q0) fits that replace the
global QRR_QOSS_FRACTION assumption — see dslib/qrr_model.fit_lm_2pt().
"""

QRR_POINTS = {
    ("infineon", "IPB014N08NM6"): [
        dict(IF=50, didt=100e6, VR=40, Tj=25.0, Qrr=107e-9, trr=66e-9),
        dict(IF=50, didt=1000e6, VR=40, Tj=25.0, Qrr=598e-9, trr=40e-9),
    ],
    ("infineon", "IPB022N12NM6"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=155.7e-9, trr=47.2e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=418.2e-9, trr=39.6e-9),
    ],
    ("infineon", "IPB022N12NM6ATMA1"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=155.7e-9, trr=47.2e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=418.2e-9, trr=39.6e-9),
    ],
    ("infineon", "IPB035N12NM6"): [
        dict(IF=43, didt=300e6, VR=60, Tj=25.0, Qrr=104e-9, trr=38e-9),
        dict(IF=43, didt=1000e6, VR=60, Tj=25.0, Qrr=263e-9, trr=29e-9),
    ],
    ("infineon", "IPB035N12NM6ATMA1"): [
        dict(IF=43, didt=300e6, VR=60, Tj=25.0, Qrr=104e-9, trr=38e-9),
        dict(IF=43, didt=1000e6, VR=60, Tj=25.0, Qrr=263e-9, trr=29e-9),
    ],
    ("infineon", "IPF011N08NM6"): [
        dict(IF=50, didt=100e6, VR=40, Tj=25.0, Qrr=107e-9, trr=66e-9),
        dict(IF=50, didt=1000e6, VR=40, Tj=25.0, Qrr=598e-9, trr=40e-9),
    ],
    ("infineon", "IPF019N12NM6"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=125e-9, trr=43e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=336e-9, trr=35e-9),
    ],
    ("infineon", "IPF019N12NM6ATMA1"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=125e-9, trr=43e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=336e-9, trr=35e-9),
    ],
    ("infineon", "IPP014N08NM6"): [
        dict(IF=50, didt=100e6, VR=40, Tj=25.0, Qrr=107e-9, trr=66e-9),
        dict(IF=50, didt=1000e6, VR=40, Tj=25.0, Qrr=598e-9, trr=40e-9),
    ],
    ("infineon", "IPP022N12NM6"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=155.2e-9, trr=46.3e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=412.1e-9, trr=39e-9),
    ],
    ("infineon", "IPP022N12NM6AKSA1"): [
        dict(IF=50, didt=300e6, VR=60, Tj=25.0, Qrr=155.2e-9, trr=46.3e-9),
        dict(IF=50, didt=1000e6, VR=60, Tj=25.0, Qrr=412.1e-9, trr=39e-9),
    ],
    ("infineon", "IPT009N08NM6"): [
        dict(IF=75, didt=100e6, VR=40, Tj=25.0, Qrr=110e-9, trr=71e-9),
        dict(IF=75, didt=1000e6, VR=40, Tj=25.0, Qrr=533e-9, trr=39e-9),
    ],
    ("infineon", "IPT017N12NM6"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=111e-9, trr=40e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=301e-9, trr=35e-9),
    ],
    ("infineon", "IPT017N12NM6ATMA1"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=111e-9, trr=40e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=301e-9, trr=35e-9),
    ],
    ("infineon", "IPTC017N12NM6"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=111e-9, trr=40e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=301e-9, trr=35e-9),
    ],
    ("infineon", "IPTC017N12NM6ATMA1"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=111e-9, trr=40e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=301e-9, trr=35e-9),
    ],
    ("infineon", "IPTC026N12NM6"): [
        dict(IF=58, didt=300e6, VR=60, Tj=25.0, Qrr=85e-9, trr=35e-9),
        dict(IF=58, didt=1000e6, VR=60, Tj=25.0, Qrr=245e-9, trr=30e-9),
    ],
    ("infineon", "IPTC026N12NM6ATMA1"): [
        dict(IF=58, didt=300e6, VR=60, Tj=25.0, Qrr=85e-9, trr=35e-9),
        dict(IF=58, didt=1000e6, VR=60, Tj=25.0, Qrr=245e-9, trr=30e-9),
    ],
    ("infineon", "IPTG017N12NM6"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=132.3e-9, trr=45.5e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=339.3e-9, trr=36.3e-9),
    ],
    ("infineon", "IPTG017N12NM6ATMA1"): [
        dict(IF=75, didt=300e6, VR=60, Tj=25.0, Qrr=132.3e-9, trr=45.5e-9),
        dict(IF=75, didt=1000e6, VR=60, Tj=25.0, Qrr=339.3e-9, trr=36.3e-9),
    ],
    ("infineon", "IQD005N04NM6"): [
        dict(IF=25, didt=100e6, VR=20, Tj=25.0, Qrr=79e-9, trr=58e-9),
        dict(IF=50, didt=1000e6, VR=20, Tj=25.0, Qrr=221e-9, trr=29e-9),
    ],
    ("infineon", "IQD009N06NM5"): [
        dict(IF=25, didt=100e6, VR=30, Tj=25.0, Qrr=51e-9, trr=45e-9),
        dict(IF=50, didt=1000e6, VR=30, Tj=25.0, Qrr=266e-9, trr=28e-9),
    ],
    ("infineon", "IQD016N08NM5"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=71e-9, trr=48e-9),
        dict(IF=50, didt=1000e6, VR=40, Tj=25.0, Qrr=331e-9, trr=29e-9),
    ],
    ("infineon", "IQD016N08NM5ATMA1"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=71e-9, trr=48e-9),
        dict(IF=50, didt=1000e6, VR=40, Tj=25.0, Qrr=331e-9, trr=29e-9),
    ],
    ("infineon", "IQD020N10NM5"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=71e-9, trr=48e-9),
        dict(IF=50, didt=1000e6, VR=50, Tj=25.0, Qrr=447e-9, trr=32e-9),
    ],
    ("infineon", "IQD020N10NM5ATMA1"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=71e-9, trr=48e-9),
        dict(IF=50, didt=1000e6, VR=50, Tj=25.0, Qrr=447e-9, trr=32e-9),
    ],
    ("infineon", "IQD063N15NM5"): [
        dict(IF=25, didt=100e6, VR=75, Tj=25.0, Qrr=55e-9, trr=49e-9),
        dict(IF=50, didt=1000e6, VR=75, Tj=25.0, Qrr=195e-9, trr=26e-9),
    ],
    ("infineon", "IQD063N15NM5ATMA1"): [
        dict(IF=25, didt=100e6, VR=75, Tj=25.0, Qrr=55e-9, trr=49e-9),
        dict(IF=50, didt=1000e6, VR=75, Tj=25.0, Qrr=195e-9, trr=26e-9),
    ],
    ("infineon", "IQDH29NE2LM5"): [
        dict(IF=25, didt=100e6, VR=12, Tj=25.0, Qrr=120e-9, trr=59e-9),
        dict(IF=50, didt=500e6, VR=12, Tj=25.0, Qrr=203e-9, trr=39e-9),
    ],
    ("infineon", "IQDH35N03LM5"): [
        dict(IF=25, didt=100e6, VR=15, Tj=25.0, Qrr=64e-9, trr=49e-9),
        dict(IF=50, didt=500e6, VR=15, Tj=25.0, Qrr=152e-9, trr=33e-9),
    ],
    ("infineon", "IQDH45N04LM6"): [
        dict(IF=25, didt=100e6, VR=20, Tj=25.0, Qrr=63e-9, trr=54e-9),
        dict(IF=50, didt=1000e6, VR=20, Tj=25.0, Qrr=277e-9, trr=31e-9),
    ],
    ("infineon", "IQDH88N06LM5"): [
        dict(IF=25, didt=100e6, VR=30, Tj=25.0, Qrr=49e-9, trr=44e-9),
        dict(IF=50, didt=1000e6, VR=30, Tj=25.0, Qrr=256e-9, trr=27e-9),
    ],
    ("infineon", "IQE004NE1LM7"): [
        dict(IF=30, didt=100e6, VR=7.5, Tj=25.0, Qrr=24e-9, trr=31e-9),
        dict(IF=30, didt=300e6, VR=7.5, Tj=25.0, Qrr=49e-9, trr=25e-9),
    ],
    ("infineon", "IQE004NE1LM7ATMA1"): [
        dict(IF=30, didt=100e6, VR=7.5, Tj=25.0, Qrr=24e-9, trr=31e-9),
        dict(IF=30, didt=300e6, VR=7.5, Tj=25.0, Qrr=49e-9, trr=25e-9),
    ],
    ("infineon", "IQE004NE1LM7CG"): [
        dict(IF=30, didt=100e6, VR=7.5, Tj=25.0, Qrr=24e-9, trr=31e-9),
        dict(IF=30, didt=300e6, VR=7.5, Tj=25.0, Qrr=49e-9, trr=25e-9),
    ],
    ("infineon", "IQE004NE1LM7CGSC"): [
        dict(IF=30, didt=100e6, VR=7.5, Tj=25.0, Qrr=24e-9, trr=31e-9),
        dict(IF=30, didt=300e6, VR=7.5, Tj=25.0, Qrr=49e-9, trr=25e-9),
    ],
    ("infineon", "IQE004NE1LM7SC"): [
        dict(IF=30, didt=100e6, VR=7.5, Tj=25.0, Qrr=24e-9, trr=31e-9),
        dict(IF=30, didt=300e6, VR=7.5, Tj=25.0, Qrr=49e-9, trr=25e-9),
    ],
    ("infineon", "IQE022N06LM5"): [
        dict(IF=20, didt=100e6, VR=30, Tj=25.0, Qrr=19e-9, trr=26e-9),
        dict(IF=20, didt=1000e6, VR=30, Tj=25.0, Qrr=98e-9, trr=17e-9),
    ],
    ("infineon", "IQE022N06LM5CG"): [
        dict(IF=20, didt=100e6, VR=30, Tj=25.0, Qrr=19e-9, trr=26e-9),
        dict(IF=20, didt=1000e6, VR=30, Tj=25.0, Qrr=98e-9, trr=17e-9),
    ],
    ("infineon", "IQE022N06LM5CGSC"): [
        dict(IF=20, didt=100e6, VR=30, Tj=25.0, Qrr=19e-9, trr=26e-9),
        dict(IF=20, didt=1000e6, VR=30, Tj=25.0, Qrr=98e-9, trr=17e-9),
    ],
    ("infineon", "IQE022N06LM5SC"): [
        dict(IF=20, didt=100e6, VR=30, Tj=25.0, Qrr=19e-9, trr=26e-9),
        dict(IF=20, didt=1000e6, VR=30, Tj=25.0, Qrr=98e-9, trr=17e-9),
    ],
    ("infineon", "IQE036N08NM6"): [
        dict(IF=15, didt=100e6, VR=40, Tj=25.0, Qrr=30e-9, trr=32e-9),
        dict(IF=15, didt=1000e6, VR=40, Tj=25.0, Qrr=173e-9, trr=21e-9),
    ],
    ("infineon", "IQE036N08NM6CG"): [
        dict(IF=15, didt=100e6, VR=40, Tj=25.0, Qrr=30e-9, trr=32e-9),
        dict(IF=15, didt=1000e6, VR=40, Tj=25.0, Qrr=173e-9, trr=21e-9),
    ],
    ("infineon", "IQE036N08NM6CGSC"): [
        dict(IF=15, didt=100e6, VR=40, Tj=25.0, Qrr=30e-9, trr=32e-9),
        dict(IF=15, didt=1000e6, VR=40, Tj=25.0, Qrr=173e-9, trr=21e-9),
    ],
    ("infineon", "IQE036N08NM6SC"): [
        dict(IF=15, didt=100e6, VR=40, Tj=25.0, Qrr=30e-9, trr=32e-9),
        dict(IF=15, didt=1000e6, VR=40, Tj=25.0, Qrr=173e-9, trr=21e-9),
    ],
    ("infineon", "IQE046N08LM5"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5ATMA1"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5CG"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5CGATMA1"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5CGSCATMA1"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5SC"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "IQE046N08LM5SCATMA1"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=26e-9, trr=32e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=18e-9),
    ],
    ("infineon", "ISC014N08NM6"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=65e-9, trr=25e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=327e-9, trr=29e-9),
    ],
    ("infineon", "ISC014N08NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=65e-9, trr=25e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=327e-9, trr=29e-9),
    ],
    ("infineon", "ISC018N08NM6"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=54e-9, trr=45e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=286e-9, trr=26e-9),
    ],
    ("infineon", "ISC018N08NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=54e-9, trr=45e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=286e-9, trr=26e-9),
    ],
    ("infineon", "ISC022N10NM6"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=70e-9, trr=52e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=325e-9, trr=28e-9),
    ],
    ("infineon", "ISC022N10NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=70e-9, trr=52e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=325e-9, trr=28e-9),
    ],
    ("infineon", "ISC027N10NM6"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=62e-9, trr=46e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=305e-9, trr=25e-9),
    ],
    ("infineon", "ISC027N10NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=62e-9, trr=46e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=305e-9, trr=25e-9),
    ],
    ("infineon", "ISC030N10NM6"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=56e-9, trr=46.5e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=266e-9, trr=25.5e-9),
    ],
    ("infineon", "ISC030N10NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=50, Tj=25.0, Qrr=56e-9, trr=46.5e-9),
        dict(IF=25, didt=1000e6, VR=50, Tj=25.0, Qrr=266e-9, trr=25.5e-9),
    ],
    ("infineon", "ISC030N12NM6"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=73e-9, trr=33e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=228e-9, trr=24e-9),
    ],
    ("infineon", "ISC030N12NM6ATMA1"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=73e-9, trr=33e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=228e-9, trr=24e-9),
    ],
    ("infineon", "ISC031N08NM6"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=34e-9, trr=36e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=202e-9, trr=22e-9),
    ],
    ("infineon", "ISC031N08NM6ATMA1"): [
        dict(IF=25, didt=100e6, VR=40, Tj=25.0, Qrr=34e-9, trr=36e-9),
        dict(IF=25, didt=1000e6, VR=40, Tj=25.0, Qrr=202e-9, trr=22e-9),
    ],
    ("infineon", "ISC032N12LM6"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=77.4e-9, trr=31.1e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=217.3e-9, trr=25.3e-9),
    ],
    ("infineon", "ISC032N12LM6ATMA1"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=77.4e-9, trr=31.1e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=217.3e-9, trr=25.3e-9),
    ],
    ("infineon", "ISC037N12NM6"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=64e-9, trr=30e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=256e-9, trr=27e-9),
    ],
    ("infineon", "ISC037N12NM6ATMA1"): [
        dict(IF=25, didt=300e6, VR=60, Tj=25.0, Qrr=64e-9, trr=30e-9),
        dict(IF=25, didt=1000e6, VR=60, Tj=25.0, Qrr=256e-9, trr=27e-9),
    ],
    ("infineon", "ISC056N08NM6"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=41e-9, trr=31e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=136e-9, trr=18e-9),
    ],
    ("infineon", "ISC056N08NM6ATMA1"): [
        dict(IF=20, didt=100e6, VR=40, Tj=25.0, Qrr=41e-9, trr=31e-9),
        dict(IF=20, didt=1000e6, VR=40, Tj=25.0, Qrr=136e-9, trr=18e-9),
    ],
    ("infineon", "ISC060N10NM6"): [
        dict(IF=12.5, didt=100e6, VR=50, Tj=25.0, Qrr=35e-9, trr=34.5e-9),
        dict(IF=12.5, didt=1000e6, VR=50, Tj=25.0, Qrr=155e-9, trr=19.5e-9),
    ],
    ("infineon", "ISC060N10NM6ATMA1"): [
        dict(IF=12.5, didt=100e6, VR=50, Tj=25.0, Qrr=35e-9, trr=34.5e-9),
        dict(IF=12.5, didt=1000e6, VR=50, Tj=25.0, Qrr=155e-9, trr=19.5e-9),
    ],
    ("infineon", "ISC073N12LM6"): [
        dict(IF=20, didt=300e6, VR=60, Tj=25.0, Qrr=35e-9, trr=22e-9),
        dict(IF=20, didt=1000e6, VR=60, Tj=25.0, Qrr=130e-9, trr=20e-9),
    ],
    ("infineon", "ISC073N12LM6ATMA1"): [
        dict(IF=20, didt=300e6, VR=60, Tj=25.0, Qrr=35e-9, trr=22e-9),
        dict(IF=20, didt=1000e6, VR=60, Tj=25.0, Qrr=130e-9, trr=20e-9),
    ],
    ("infineon", "ISC078N12NM6"): [
        dict(IF=18.5, didt=300e6, VR=60, Tj=25.0, Qrr=57.8e-9, trr=28.8e-9),
        dict(IF=18.5, didt=1000e6, VR=60, Tj=25.0, Qrr=179.9e-9, trr=17.9e-9),
    ],
    ("infineon", "ISC078N12NM6ATMA1"): [
        dict(IF=18.5, didt=300e6, VR=60, Tj=25.0, Qrr=57.8e-9, trr=28.8e-9),
        dict(IF=18.5, didt=1000e6, VR=60, Tj=25.0, Qrr=179.9e-9, trr=17.9e-9),
    ],
    ("infineon", "ISC080N10NM6ATMA1"): [
        dict(IF=10, didt=100e6, VR=50, Tj=25.0, Qrr=31e-9, trr=31.5e-9),
        dict(IF=10, didt=1000e6, VR=50, Tj=25.0, Qrr=140e-9, trr=18e-9),
    ],
    ("infineon", "ISC088N08NM6"): [
        dict(IF=14, didt=100e6, VR=40, Tj=25.0, Qrr=28e-9, trr=29e-9),
        dict(IF=14, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=17e-9),
    ],
    ("infineon", "ISC088N08NM6ATMA1"): [
        dict(IF=14, didt=100e6, VR=40, Tj=25.0, Qrr=28e-9, trr=29e-9),
        dict(IF=14, didt=1000e6, VR=40, Tj=25.0, Qrr=129e-9, trr=17e-9),
    ],
    ("infineon", "ISC104N12LM6"): [
        dict(IF=14, didt=300e6, VR=60, Tj=25.0, Qrr=38e-9, trr=23e-9),
        dict(IF=14, didt=1000e6, VR=60, Tj=25.0, Qrr=106e-9, trr=17e-9),
    ],
    ("infineon", "ISC104N12LM6ATMA1"): [
        dict(IF=14, didt=300e6, VR=60, Tj=25.0, Qrr=38e-9, trr=23e-9),
        dict(IF=14, didt=1000e6, VR=60, Tj=25.0, Qrr=106e-9, trr=17e-9),
    ],
    ("infineon", "ISC110N12NM6"): [
        dict(IF=13, didt=300e6, VR=60, Tj=25.0, Qrr=37.3e-9, trr=23.1e-9),
        dict(IF=13, didt=1000e6, VR=60, Tj=25.0, Qrr=112.5e-9, trr=14.7e-9),
    ],
    ("infineon", "ISC110N12NM6ATMA1"): [
        dict(IF=13, didt=300e6, VR=60, Tj=25.0, Qrr=37.3e-9, trr=23.1e-9),
        dict(IF=13, didt=1000e6, VR=60, Tj=25.0, Qrr=112.5e-9, trr=14.7e-9),
    ],
    ("infineon", "ISC151N08NM6"): [
        dict(IF=9, didt=100e6, VR=40, Tj=25.0, Qrr=16e-9, trr=22e-9),
        dict(IF=9, didt=1000e6, VR=40, Tj=25.0, Qrr=89e-9, trr=14e-9),
    ],
    ("infineon", "ISC230N10NM6"): [
        dict(IF=5, didt=100e6, VR=50, Tj=25.0, Qrr=23e-9, trr=30e-9),
        dict(IF=5, didt=1000e6, VR=50, Tj=25.0, Qrr=86.5e-9, trr=14e-9),
    ],
    ("infineon", "ISC230N10NM6ATMA1"): [
        dict(IF=5, didt=100e6, VR=50, Tj=25.0, Qrr=23e-9, trr=30e-9),
        dict(IF=5, didt=1000e6, VR=50, Tj=25.0, Qrr=86.5e-9, trr=14e-9),
    ],
    ("infineon", "ISC320N12LM6"): [
        dict(IF=4.5, didt=300e6, VR=60, Tj=25.0, Qrr=23.8e-9, trr=20.5e-9),
        dict(IF=4.5, didt=1000e6, VR=60, Tj=25.0, Qrr=20.3e-9, trr=10.3e-9),
    ],
    ("infineon", "ISC320N12LM6ATMA1"): [
        dict(IF=4.5, didt=300e6, VR=60, Tj=25.0, Qrr=23.8e-9, trr=20.5e-9),
        dict(IF=4.5, didt=1000e6, VR=60, Tj=25.0, Qrr=20.3e-9, trr=10.3e-9),
    ],
    ("infineon", "ISK018NE1LM7"): [
        dict(IF=20, didt=100e6, VR=7.5, Tj=25.0, Qrr=8e-9, trr=16e-9),
        dict(IF=20, didt=300e6, VR=7.5, Tj=25.0, Qrr=15e-9, trr=14e-9),
    ],
    ("infineon", "ISK057N04LM6"): [
        dict(IF=20, didt=100e6, VR=20, Tj=25.0, Qrr=29e-9, trr=48e-9),
        dict(IF=20, didt=500e6, VR=20, Tj=25.0, Qrr=32e-9, trr=16e-9),
    ],
    ("infineon", "ISZ053N08NM6"): [
        dict(IF=10, didt=100e6, VR=40, Tj=25.0, Qrr=28e-9, trr=31e-9),
        dict(IF=10, didt=1000e6, VR=40, Tj=25.0, Qrr=135e-9, trr=18e-9),
    ],
    ("infineon", "ISZ053N08NM6ATMA1"): [
        dict(IF=10, didt=100e6, VR=40, Tj=25.0, Qrr=28e-9, trr=31e-9),
        dict(IF=10, didt=1000e6, VR=40, Tj=25.0, Qrr=135e-9, trr=18e-9),
    ],
    ("infineon", "ISZ080N10NM6"): [
        dict(IF=10, didt=100e6, VR=50, Tj=25.0, Qrr=31e-9, trr=31.5e-9),
        dict(IF=10, didt=1000e6, VR=50, Tj=25.0, Qrr=140e-9, trr=18e-9),
    ],
    ("infineon", "ISZ080N10NM6ATMA1"): [
        dict(IF=10, didt=100e6, VR=50, Tj=25.0, Qrr=31e-9, trr=31.5e-9),
        dict(IF=10, didt=1000e6, VR=50, Tj=25.0, Qrr=140e-9, trr=18e-9),
    ],
    ("infineon", "ISZ106N12LM6"): [
        dict(IF=14, didt=300e6, VR=60, Tj=25.0, Qrr=38e-9, trr=23e-9),
        dict(IF=14, didt=1000e6, VR=60, Tj=25.0, Qrr=106e-9, trr=17e-9),
    ],
    ("infineon", "ISZ106N12LM6ATMA1"): [
        dict(IF=14, didt=300e6, VR=60, Tj=25.0, Qrr=38e-9, trr=23e-9),
        dict(IF=14, didt=1000e6, VR=60, Tj=25.0, Qrr=106e-9, trr=17e-9),
    ],
    ("infineon", "ISZ157N08NM6"): [
        dict(IF=9, didt=100e6, VR=40, Tj=25.0, Qrr=16e-9, trr=22e-9),
        dict(IF=9, didt=1000e6, VR=40, Tj=25.0, Qrr=89e-9, trr=14e-9),
    ],
    ("infineon", "ISZ230N10NM6"): [
        dict(IF=5, didt=100e6, VR=50, Tj=25.0, Qrr=23e-9, trr=30e-9),
        dict(IF=5, didt=1000e6, VR=50, Tj=25.0, Qrr=86.5e-9, trr=14e-9),
    ],
    ("infineon", "ISZ230N10NM6ATMA1"): [
        dict(IF=5, didt=100e6, VR=50, Tj=25.0, Qrr=23e-9, trr=30e-9),
        dict(IF=5, didt=1000e6, VR=50, Tj=25.0, Qrr=86.5e-9, trr=14e-9),
    ],
    ("infineon", "ISZ330N12LM6"): [
        dict(IF=4.5, didt=300e6, VR=60, Tj=25.0, Qrr=28e-9, trr=21e-9),
        dict(IF=4.5, didt=1000e6, VR=60, Tj=25.0, Qrr=45e-9, trr=11e-9),
    ],
    ("infineon", "ISZ330N12LM6ATMA1"): [
        dict(IF=4.5, didt=300e6, VR=60, Tj=25.0, Qrr=28e-9, trr=21e-9),
        dict(IF=4.5, didt=1000e6, VR=60, Tj=25.0, Qrr=45e-9, trr=11e-9),
    ],
    ("onsemi", "FDMS003N08C"): [
        dict(IF=28, didt=300e6, VR=None, Tj=25.0, Qrr=53e-9, trr=28e-9),
        dict(IF=28, didt=1000e6, VR=None, Tj=25.0, Qrr=121e-9, trr=23e-9),
    ],
    ("onsemi", "FDMS004N08C"): [
        dict(IF=22, didt=300e6, VR=None, Tj=25.0, Qrr=48e-9, trr=26e-9),
        dict(IF=22, didt=1000e6, VR=None, Tj=25.0, Qrr=108e-9, trr=19e-9),
    ],
    ("onsemi", "FDMS2D5N08C"): [
        dict(IF=34, didt=300e6, VR=None, Tj=25.0, Qrr=55e-9, trr=30e-9),
        dict(IF=34, didt=1000e6, VR=None, Tj=25.0, Qrr=139e-9, trr=24e-9),
    ],
    ("onsemi", "FDMS86180"): [
        dict(IF=33, didt=300e6, VR=None, Tj=25.0, Qrr=109e-9, trr=44e-9),
        dict(IF=33, didt=1000e6, VR=None, Tj=25.0, Qrr=235e-9, trr=33e-9),
    ],
    ("onsemi", "FDMS86182"): [
        dict(IF=14, didt=300e6, VR=None, Tj=25.0, Qrr=52e-9, trr=28e-9),
        dict(IF=14, didt=1000e6, VR=None, Tj=25.0, Qrr=116e-9, trr=22e-9),
    ],
    ("onsemi", "FDMS86183"): [
        dict(IF=8, didt=300e6, VR=None, Tj=25.0, Qrr=36e-9, trr=22e-9),
        dict(IF=8, didt=1000e6, VR=None, Tj=25.0, Qrr=79e-9, trr=18e-9),
    ],
    ("onsemi", "NTMFS08N003C"): [
        dict(IF=28, didt=300e6, VR=None, Tj=25.0, Qrr=53e-9, trr=28e-9),
        dict(IF=28, didt=1000e6, VR=None, Tj=25.0, Qrr=121e-9, trr=23e-9),
    ],
}


def qrr_points_for(mfr, mpn):
    """(mfr, mpn) -> list of row dicts or None. Same base-MPN prefix
    fallback as qrr_conditions (orderable suffixes resolve to the base)."""
    if not mfr or not mpn:
        return None
    hit = (QRR_POINTS.get((mfr, mpn))
           or QRR_POINTS.get((str(mfr).lower(), mpn)))
    if hit:
        return [dict(r) for r in hit]
    for (m, p), v in QRR_POINTS.items():
        if str(m).lower() == str(mfr).lower() and str(mpn).startswith(p):
            return [dict(r) for r in v]
    return None
