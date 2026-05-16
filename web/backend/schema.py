from typing import List, Optional, Dict
from pydantic import BaseModel


class Part(BaseModel):
    mfr: str
    mpn: str
    substrate: str
    housing: Optional[str] = None
    Vds_max: Optional[float] = None
    Rds_on_max: Optional[float] = None
    Id: Optional[float] = None
    Qsw: Optional[float] = None
    Qg: Optional[float] = None
    Qrr: Optional[float] = None
    Vsd: Optional[float] = None
    V_pl: Optional[float] = None
    Vgs_th: Optional[float] = None
    QgdQgs_ratio: Optional[float] = None
    FoM: Optional[float] = None
    FoMqsw: Optional[float] = None
    FoMqrr: Optional[float] = None
    FoMcoss: Optional[float] = None
    date: Optional[str] = None
    extras: Dict[str, float] = {}


class Range(BaseModel):
    min: float
    max: float
    slider_max: Optional[float] = None


class Bucket(BaseModel):
    value: Optional[str] = None
    count: int


class Meta(BaseModel):
    total: int
    manufacturers: List[Bucket]
    housings: List[Bucket]
    substrates: List[Bucket]
    ranges: Dict[str, Range]
