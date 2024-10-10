


def test_bbox():
    from dslib.pdf.tree import Bbox

    b1 = Bbox(0, 0, 10, 10)
    b2 = Bbox(5, 5, 10, 10)

    assert b1.area == 100
    assert b2.area == 25
    assert b1.height == 10  == b1.width
    assert b2.height == 5 == b2.height

    assert b1.h_overlap(b2) == b2.h_overlap(b1) == 5
    assert b1.v_overlap(b2) == b2.v_overlap(b1) == 5

    assert b1.overlap_area(b2) == b2.overlap_area(b1) == 25

    b3 = Bbox(10, 10, 20, 20)
    assert b1.h_overlap(b3) == 0
    assert b1.v_overlap(b3) == 0