from dslib import round_to_n_dec
from dslib.spec_models import DcDcLoadParams

dc = DcDcLoadParams(
    vi=70,
    vo=30,
    f=40e3,
    io=30,
    ripple_factor=0.3,
)

print(dc)
print('L=', round_to_n_dec(dc.L,3))
