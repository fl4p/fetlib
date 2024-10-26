from dslib.pdf2txt.parse import parse_datasheet


def test_mosfet_specs():

    ds = parse_datasheet('../.././datasheets/infineon/BSB056N10NN3GXUMA2.pdf')
    ds.get_mosfet_specs()