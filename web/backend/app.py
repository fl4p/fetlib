import logging
import math
import os
import sys
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dslib.store import parts_db  # noqa: E402

from .schema import Bucket, Meta, Part, Range  # noqa: E402

log = logging.getLogger("mosfet-web")

NUMERIC_COLUMNS = (
    "Vds_max",
    "Rds_on_max",
    "Id",
    "Qsw",
    "Qg",
    "Qrr",
    "Vsd",
    "V_pl",
    "Vgs_th",
    "QgdQgs_ratio",
)

SLIDER_COLUMNS = (
    "Vds_max",
    "Rds_on_max",
    "Id",
    "Qsw",
    "Qg",
    "Qrr",
    "Vsd",
    "QgdQgs_ratio",
)


def _clean(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _substrate(substrate: Optional[str]) -> str:
    if substrate == "GaN":
        return "GaN"
    if substrate == "SiC":
        return "SiC"
    return "Si"


def _serialize(part) -> dict:
    specs = part.specs
    disc = part.discovered
    basic = getattr(disc, "specs", None) if disc is not None else None

    substrate = getattr(basic, "substrate", None) if basic is not None else None
    package = getattr(disc, "package", None) if disc is not None else None
    release = getattr(disc, "release_data", None) if disc is not None else None
    vgs_th = getattr(basic, "Vgs_th_max", None) if basic is not None else None
    id_fallback = getattr(basic, "ID_25", None) if basic is not None else None

    id_val = _clean(getattr(specs, "Id", None))
    if id_val is None:
        id_val = _clean(id_fallback)

    date_str = None
    if release is not None:
        try:
            date_str = release.date().isoformat() if hasattr(release, "date") else release.isoformat()
        except Exception:
            date_str = str(release)

    return {
        "mfr": part.mfr,
        "mpn": part.mpn,
        "substrate": _substrate(substrate),
        "housing": package if isinstance(package, str) and package else None,
        "Vds_max": _clean(_safe_attr(specs, "Vds")),
        "Rds_on_max": _clean(_safe_attr(specs, "Rds_on")),
        "Id": id_val,
        "Qsw": _clean(_safe_attr(specs, "Qsw")),
        "Qg": _clean(_safe_attr(specs, "Qg")),
        "Qrr": _clean(_safe_attr(specs, "Qrr")),
        "Vsd": _clean(_safe_attr(specs, "Vsd")),
        "V_pl": _clean(_safe_attr(specs, "V_pl")),
        "Vgs_th": _clean(vgs_th),
        "QgdQgs_ratio": _clean(_safe_attr(specs, "QgdQgsRatio")),
        "date": date_str,
    }


def _load_parts() -> List[dict]:
    try:
        raw = parts_db.load()
    except Exception as e:
        log.exception("Failed to load parts_db: %s", e)
        return []

    rows: List[dict] = []
    for part in raw.values():
        if part is None or part.specs is None:
            continue
        try:
            rows.append(_serialize(part))
        except Exception as e:
            log.warning("Skipping part %s/%s: %s", getattr(part, "mfr", "?"), getattr(part, "mpn", "?"), e)
    return rows


def _build_meta(rows: List[dict]) -> Meta:
    mfr_counts = Counter(r["mfr"] for r in rows)
    housing_counts = Counter(r["housing"] for r in rows)
    substrate_counts = Counter(r["substrate"] for r in rows)

    def buckets(counter: Counter) -> list:
        items = sorted(counter.items(), key=lambda x: (-x[1], (x[0] or "")))
        return [Bucket(value=k, count=c) for k, c in items]

    ranges = {}
    for col in NUMERIC_COLUMNS:
        vals = [r[col] for r in rows if r.get(col) is not None]
        if vals:
            ranges[col] = Range(min=min(vals), max=max(vals))
        else:
            ranges[col] = Range(min=0.0, max=0.0)

    return Meta(
        total=len(rows),
        manufacturers=buckets(mfr_counts),
        housings=buckets(housing_counts),
        substrates=buckets(substrate_counts),
        ranges=ranges,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.parts = _load_parts()
    app.state.meta = _build_meta(app.state.parts)
    log.info("Loaded %d parts", len(app.state.parts))
    yield


app = FastAPI(title="MOSFET parametric search", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/parts", response_model=List[Part])
def list_parts():
    return app.state.parts


@app.get("/api/parts/meta", response_model=Meta)
def parts_meta():
    return app.state.meta
