from dclib.powerloss import CoilSpecs
from dslib.spec_models import DcDcLoadParams
from maglib.cores import MicrometalsToroid, MicrometalsT184

#2_KS184_125A-d118-s10-n12
#KS184_125

KS184u125s1_Cu180s10t17 = CoilSpecs(
    Rdc=3.05e-3, # TODO measure
    L0=84e-6,
    turns=17,
    wire_diameter=1.8e-3,
    wire_strands=4,
    core=MicrometalsToroid('MS', 125, MicrometalsT184),
)

dcdc = DcDcLoadParams(72, 27, 39e3, 200e-9, 30, coil=KS184u125s1_Cu180s10t17)

print(KS184u125s1_Cu180s10t17.micrometals_analyzer(dcdc))