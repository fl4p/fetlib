import logging
import math
import os
import sys
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dslib import get_datasheets_path  # noqa: E402
from dslib.store import parts_db  # noqa: E402

from .housing import normalize as _normalize_housing  # noqa: E402
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
    "FoM",
    "FoMqsw",
    "FoMqrr",
    "FoMcoss",
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
    "FoM",
    "FoMqsw",
    "FoMqrr",
    "FoMcoss",
)

# (weight_under, weight_over) where "under" means candidate < query in log space.
# Asymmetric for ratings where a candidate underspec'd vs the query is a bad
# replacement; symmetric for everything else.
SIMILARITY_WEIGHTS = {
    "Vds_max":      (3.0, 0.5),   # candidate < query → underrated, bad
    "Id":           (2.0, 0.3),   # candidate < query → underrated, bad
    "Rds_on_max":   (0.3, 2.0),   # candidate > query → lossier, bad
    "Qg":           (1.0, 1.0),
    "Qsw":          (1.0, 1.0),
    "Qrr":          (1.0, 1.0),
    "Vgs_th":       (0.5, 0.5),
    "Vsd":          (0.3, 0.3),
    "V_pl":         (0.3, 0.3),
    "QgdQgs_ratio": (0.5, 0.5),
}
# Candidates lacking either of these are excluded — the score isn't meaningful.
SIMILARITY_REQUIRED = ("Vds_max", "Rds_on_max")


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

    vsd_val = _clean(_safe_attr(specs, "Vsd"))
    if vsd_val is not None:
        vsd_val = abs(vsd_val)

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
        "housing": _normalize_housing(package),
        "Vds_max": _clean(_safe_attr(specs, "Vds")),
        "Rds_on_max": _clean(_safe_attr(specs, "Rds_on")),
        "Id": id_val,
        "Qsw": _clean(_safe_attr(specs, "Qsw")),
        "Qg": _clean(_safe_attr(specs, "Qg")),
        "Qrr": _clean(_safe_attr(specs, "Qrr")),
        "Vsd": vsd_val,
        "V_pl": _clean(_safe_attr(specs, "V_pl")),
        "Vgs_th": _clean(vgs_th),
        "QgdQgs_ratio": _clean(_safe_attr(specs, "QgdQgsRatio")),
        "FoM": _clean(_safe_attr(specs, "FoM")),
        "FoMqsw": _clean(_safe_attr(specs, "FoMqsw")),
        "FoMqrr": _clean(_safe_attr(specs, "FoMqrr")),
        "FoMcoss": _clean(_safe_attr(specs, "FoMcoss")),
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
            raise
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
            svals = sorted(vals)
            lo, hi = svals[0], svals[-1]
            p99 = svals[min(len(svals) - 1, int(len(svals) * 0.99))]
            slider_max = p99 if col in SLIDER_COLUMNS and p99 < hi else None
            ranges[col] = Range(min=lo, max=hi, slider_max=slider_max)
        else:
            ranges[col] = Range(min=0.0, max=0.0)

    return Meta(
        total=len(rows),
        manufacturers=buckets(mfr_counts),
        housings=buckets(housing_counts),
        substrates=buckets(substrate_counts),
        ranges=ranges,
    )


def _similarity_stats(rows: List[dict]) -> dict:
    """Per-feature (log_mean, log_std) over positive non-null values."""
    stats = {}
    for feat in SIMILARITY_WEIGHTS:
        logs = [math.log(r[feat]) for r in rows if r.get(feat) is not None and r[feat] > 0]
        if len(logs) < 2:
            stats[feat] = (0.0, 1.0)
            continue
        mu = sum(logs) / len(logs)
        var = sum((x - mu) ** 2 for x in logs) / (len(logs) - 1)
        sigma = math.sqrt(var) if var > 0 else 1.0
        stats[feat] = (mu, sigma)
    return stats


def _similarity_score(query: dict, candidate: dict, stats: dict) -> Optional[float]:
    for feat in SIMILARITY_REQUIRED:
        qv = query.get(feat)
        cv = candidate.get(feat)
        if qv is None or cv is None or qv <= 0 or cv <= 0:
            return None
    total = 0.0
    for feat, (w_under, w_over) in SIMILARITY_WEIGHTS.items():
        qv = query.get(feat)
        cv = candidate.get(feat)
        if qv is None or cv is None or qv <= 0 or cv <= 0:
            continue
        _, sigma = stats[feat]
        if sigma <= 0:
            continue
        diff = (math.log(cv) - math.log(qv)) / sigma
        w = w_under if diff < 0 else w_over
        total += w * diff * diff
    return total


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.parts = _load_parts()
    app.state.meta = _build_meta(app.state.parts)
    app.state.similarity_stats = _similarity_stats(app.state.parts)
    app.state.part_index = {(p["mfr"], p["mpn"]): p for p in app.state.parts}
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


@app.get("/api/datasheet")
def datasheet(mfr: str, mpn: str):
    path = get_datasheets_path(mfr, mpn)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="datasheet not found")
    return FileResponse(path, media_type="application/pdf", filename=f"{mpn}.pdf", content_disposition_type='inline')


@app.get("/api/qg-curve")
def qg_curve(mfr: str, mpn: str):
    safe_mfr = os.path.basename(mfr)
    safe_mpn = os.path.basename(mpn)
    path = os.path.join(REPO_ROOT, "crops", safe_mfr, safe_mpn, "qg.webp")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="qg curve not found")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/similar")
def similar(mfr: str, mpn: str, limit: int = 20):
    query = app.state.part_index.get((mfr, mpn))
    if query is None:
        raise HTTPException(status_code=404, detail="part not found")

    stats = app.state.similarity_stats
    scored: List[tuple] = []
    for cand in app.state.parts:
        if cand["mfr"] == mfr and cand["mpn"] == mpn:
            continue
        s = _similarity_score(query, cand, stats)
        if s is None:
            continue
        scored.append((s, cand))

    scored.sort(key=lambda t: t[0])
    return [{"score": round(s, 4), "part": p} for s, p in scored[: max(1, limit)]]
