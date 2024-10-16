from typing import List, Dict, Literal

import pandas as pd

from dslib.pdf.ascii import Row
from dslib.pdf.tree import Block, GraphicBlock


def take(gen, n: int) -> list:
    """
    Take n not-None elements from gen and return them.

    :param gen:
    :param n:
    :return:
    """
    l = []
    while len(l) < n:
        try:
            v = next(gen)
            if v is not None:
                l.append(v)
        except StopIteration:
            break
    return l


class SpatialQuery():
    # see pdfminer.utils.Plane

    def __init__(self, blocks: List[Block], graphic_max_area=200):
        self.blocks = []

        for b in blocks:
            if isinstance(b, Row):
                self.blocks.extend(p for p in b.to_phrases() if p.bbox.height and p.bbox.width)
            elif isinstance(b, GraphicBlock):
                if b.bbox.area <= graphic_max_area:
                    self.blocks.append(b)
            else:
                raise ValueError(repr(b))
        del blocks

        self.by_bbox_edge: Dict[Literal, pd.Series] = dict()

        for dir in ('x1', 'x2', 'y1', 'y2'):
            b = []
            idx = []
            for block in self.blocks:
                idx.append(block.bbox[dir])
                b.append(block)
            s = pd.Series(b, index=idx)
            s.sort_index(inplace=True)
            self.by_bbox_edge[dir] = s

    def cast(self, dir, start, end):
        if start <= end:
            v = self.by_bbox_edge[dir][start:end]
        else:
            v = self.by_bbox_edge[dir][end:start].iloc[::-1]

        return list(v)

    def ray(self, dir, bbox, length, min_overlap, limit=10, start_from_bbox_center=False, ignore=None, types=None):
        assert length > 0
        d = int(dir[1])

        start_bound = dir[0] + str(1 + (d % 2))
        start = bbox[start_bound]
        if start_from_bbox_center:
            start = (start + bbox[dir]) * .5

        els = self.cast(dir, start, start + length * (3 - 2 * d))

        ol_fn = getattr(bbox, 'v_overlap_rel' if dir[0] == 'x' else 'h_overlap_rel')
        els_filt = filter(lambda el: ol_fn(el.bbox) > min_overlap, els)

        if ignore:
            els_filt = filter(lambda el: bbox not in ignore, els_filt)

        if types:
            # assert
            els_filt = filter(lambda el: isinstance(el, types), els_filt)

        took = take(els_filt, limit)

        return took
