#!/usr/bin/env python3
"""Import human-GREEN Coss review cards into dslib/coss_curves.py.

Consumes the browser-exported ``*.review.json`` from build_html_review_packets.py,
keeps capacitance cards whose ``human_review.status`` is ``green``, re-runs the
machine export gate on each card's ``values.verify.json``, and appends passing curves to
``COSS_CURVES`` / ``CISS_CURVES`` / ``COSS_CURVE_SOURCE``.

Human GREEN is necessary but not sufficient: rejected export-gate rows are reported and
not landed. Existing exact ``(mfr, mpn)`` registry keys are skipped.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import importlib.util
import json
import fcntl
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CURVES_FILE = REPO / "dslib" / "coss_curves.py"
DEFAULT_BACKLOG_HOME = Path(os.environ.get(
    "FETLIB_DSDIG_BACKLOG_HOME", "/Users/fab/dev/pv/ee/dsdig-verify-backlog"))
DEFAULT_DSDIG_HOME = Path(os.environ.get(
    "FETLIB_DSDIG_HOME", "/Users/fab/dev/pv/ee/datasheet-chart-digitizer"))


def _arguments() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Land human-GREEN Coss review cards into dslib/coss_curves.py")
    ap.add_argument("review_json", nargs="+", type=Path,
                    help="browser-exported *.review.json packet file(s)")
    ap.add_argument("--backlog-root", type=Path, default=DEFAULT_BACKLOG_HOME,
                    help="dsdig-verify-backlog root containing values.verify.json files")
    ap.add_argument("--dsdig-home", type=Path, default=DEFAULT_DSDIG_HOME,
                    help="datasheet-chart-digitizer checkout")
    ap.add_argument("--curves-file", type=Path, default=DEFAULT_CURVES_FILE,
                    help="target dslib/coss_curves.py")
    ap.add_argument("--out", type=Path,
                    help="optional directory for the gated *.dslib_coss.json exports")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the import plan and write export JSON, but do not edit curves-file")
    return ap.parse_args()


def _load_dsdig_export(dsdig_home: Path):
    src = dsdig_home / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from datasheet_chart_digitizer.coss_dslib import export_row
    return export_row


def _load_existing(curves_file: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    spec = importlib.util.spec_from_file_location("_fetlib_coss_curves_for_import", curves_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {curves_file}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return (set(mod.COSS_CURVES), set(getattr(mod, "CISS_CURVES", {})),
            set(getattr(mod, "COSS_CURVE_SOURCE", {})))


def _green_items(review_jsons: Iterable[Path]) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for path in review_jsons:
        packet = json.loads(path.read_text())
        packet_name = str(packet.get("packet") or path.stem)
        exported_at = str(packet.get("exported_at") or "")
        for item in packet.get("items", []):
            if item.get("chart_type") != "capacitance" or not item.get("values"):
                continue
            key = str(item.get("id") or item["values"])
            copied = dict(item)
            copied["_packet"] = packet_name
            copied["_packet_file"] = str(path)
            copied["_exported_at"] = exported_at
            by_id.setdefault(key, []).append(copied)

    out = []
    for rows in by_id.values():
        statuses = {(r.get("human_review") or {}).get("status") for r in rows}
        if statuses != {"green"}:
            continue
        out.append(max(rows, key=lambda r: str(r.get("_exported_at") or "")))
    return out


def _value_path(backlog_root: Path, item: dict[str, Any]) -> tuple[Path, Path]:
    p = Path(str(item["values"]))
    if p.is_absolute():
        return p, p.parents[5] if len(p.parents) >= 6 else p.parent

    candidates: list[tuple[Path, Path]] = []
    packet_file = Path(str(item.get("_packet_file") or ""))
    if packet_file:
        for parent in (packet_file.parent, *packet_file.parents):
            candidates.append((parent / "review-backlog" / p, parent / "review-backlog"))
            candidates.append((parent / p, parent))
    for review_backlog in sorted((REPO / "out").glob("**/review-backlog")):
        candidates.append((review_backlog / p, review_backlog))
    candidates.append((backlog_root / p, backlog_root))

    seen = set()
    for path, root in candidates:
        key = (path, root)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path, root
    return backlog_root / p, backlog_root


def _line_for_assign_end(source: str, name: str) -> int:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if node.end_lineno is None:
                raise RuntimeError(f"no end line for {name}")
            return node.end_lineno - 1
    raise RuntimeError(f"assignment not found: {name}")


def _fmt_scalar(v: Any) -> str:
    if v is None:
        return "None"
    if isinstance(v, str):
        return repr(v)
    return repr(v)


def _fmt_points(points: list[list[float] | tuple[float, ...]], indent: str = "        ") -> str:
    return "\n".join(
        f"{indent}({', '.join(f'{float(x):.10g}' for x in p)})," for p in points)


def _anchor_summary(anchor_check: dict[str, dict[str, Any]]) -> str:
    parts = []
    for name in ("Coss", "Crss", "Ciss"):
        row = anchor_check.get(name)
        if not row:
            continue
        rel = float(row.get("rel_error", 0.0))
        v = float(row.get("vds_v", 0.0))
        parts.append(f"{name} {row.get('spec_pf'):g} pF@{v:g}V ({rel:+.1%})")
    return ", ".join(parts) or "table-anchor validation"


def _safe_comment(value: Any) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")


def _source_entry(key: tuple[str, str], result: Any, item: dict[str, Any]) -> str:
    row = asdict(result)
    packet = item.get("_packet") or Path(str(item.get("_packet_file", "review"))).stem
    packet = _safe_comment(packet)
    exported = _safe_comment(item.get("_exported_at") or _dt.date.today().isoformat())
    page = row.get("page")
    if page is None:
        value_path = Path(str(item["_values_path"]))
        try:
            page = json.loads(value_path.read_text()).get("page")
        except Exception:
            page = None
    anchors = ["Coss", "Crss"] + (["Ciss"] if row.get("ciss_status") == "pass" else [])
    validation = ("export gate on FETLIB-served anchors (dslib.coss_anchors): "
                  f"{'/'.join(anchors)} + Qoss; human overlay review GREEN "
                  f"(packet {packet}, exported {exported})")
    source_figure = "Diagram %s" % _safe_comment(row["diagram"])
    return (
        f"    {key!r}: dict(\n"
        f"        datasheet_revision=\"unknown\", source_figure={source_figure!r},\n"
        f"        source_page={_fmt_scalar(page)}, digitization_method=\"dsdig-auto-vector-adaptive-knots\",\n"
        f"        validation_method={validation!r}),\n"
    )


def _coss_entry(key: tuple[str, str], result: Any, item: dict[str, Any]) -> str:
    row = asdict(result)
    packet = _safe_comment(item.get("_packet") or Path(str(item.get("_packet_file", "review"))).stem)
    return (
        f"    # human overlay review GREEN ({packet}); export anchors: "
        f"{_anchor_summary(row.get('anchor_check') or {})}.\n"
        f"    {key!r}: [\n{_fmt_points(row['curve'])}\n    ],\n"
    )


def _ciss_entry(key: tuple[str, str], result: Any) -> str:
    row = asdict(result)
    return f"    {key!r}: [\n{_fmt_points(row['ciss_curve'])}\n    ],\n"


def _apply_insertions(curves_file: Path, coss_entries: list[str], ciss_entries: list[str],
                      source_entries: list[str], coss_keys: set[tuple[str, str]],
                      ciss_keys: set[tuple[str, str]]) -> None:
    lock_path = curves_file.with_suffix(curves_file.suffix + ".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing_coss, existing_ciss, existing_source = _load_existing(curves_file)
        dup_coss = coss_keys & (existing_coss | existing_source)
        dup_ciss = ciss_keys & existing_ciss
        if dup_coss or dup_ciss:
            raise RuntimeError("registry changed while importing; duplicate key(s): "
                               f"Coss={sorted(dup_coss)}, Ciss={sorted(dup_ciss)}")
        source = curves_file.read_text()
        inserts = []
        if coss_entries:
            inserts.append((_line_for_assign_end(source, "COSS_CURVES"), "\n" + "".join(coss_entries)))
        if ciss_entries:
            inserts.append((_line_for_assign_end(source, "CISS_CURVES"), "\n" + "".join(ciss_entries)))
        if source_entries:
            inserts.append((_line_for_assign_end(source, "COSS_CURVE_SOURCE"), "\n" + "".join(source_entries)))
        lines = source.splitlines(keepends=True)
        for line_no, text in sorted(inserts, reverse=True):
            lines.insert(line_no, text)
        generated = "".join(lines)
        compile(generated, str(curves_file), "exec")
        tmp = curves_file.with_suffix(curves_file.suffix + ".tmp")
        tmp.write_text(generated)
        os.replace(tmp, curves_file)


def main() -> None:
    args = _arguments()
    export_row = _load_dsdig_export(args.dsdig_home)
    existing_coss, existing_ciss, existing_source = _load_existing(args.curves_file)
    items = _green_items(args.review_json)
    out_dir = args.out
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    accepted, rejected, skipped = [], [], []
    coss_entries, ciss_entries, source_entries = [], [], []
    pending_coss: set[tuple[str, str]] = set()
    pending_ciss: set[tuple[str, str]] = set()
    for item in items:
        mfr = str(item.get("mfr") or str(item.get("id", "")).split("/", 1)[0])
        item_part = str(item.get("part") or str(item.get("id", "")).split("/")[1])
        key = (mfr, item_part)
        if key in existing_coss:
            skipped.append((item.get("id"), "already in COSS_CURVES", key))
            continue
        if key in existing_source:
            skipped.append((item.get("id"), "already in COSS_CURVE_SOURCE", key))
            continue
        if key in pending_coss:
            skipped.append((item.get("id"), "duplicate green key in input batch", key))
            continue
        value_path, export_root = _value_path(args.backlog_root, item)
        item["_values_path"] = str(value_path)
        if not value_path.exists():
            skipped.append((item.get("id"), "missing values file", str(value_path)))
            continue
        row = json.loads(value_path.read_text())
        row_part = str(row.get("part") or "")
        if row_part and row_part != item_part:
            skipped.append((item.get("id"), "values file part mismatch", row_part))
            continue
        result = export_row(row, export_root)
        payload = asdict(result)
        if out_dir:
            safe = "".join(ch if ch.isalnum() else "_" for ch in f"{key[0]}_{key[1]}_d{payload['diagram']}")
            (out_dir / f"{safe}.dslib_coss.json").write_text(json.dumps(payload, indent=2) + "\n")
        if payload["status"] != "pass":
            rejected.append((key, payload["reasons"]))
            continue
        coss_entries.append(_coss_entry(key, result, item))
        source_entries.append(_source_entry(key, result, item))
        pending_coss.add(key)
        if payload.get("ciss_status") == "pass" and key not in existing_ciss and key not in pending_ciss:
            ciss_entries.append(_ciss_entry(key, result))
            pending_ciss.add(key)
        accepted.append(key)

    print("coss review import: %d green card(s), %d accepted, %d rejected, %d skipped" % (
        len(items), len(accepted), len(rejected), len(skipped)))
    for key in accepted:
        print("  ACCEPT", "%s/%s" % key)
    for key, reasons in rejected[:20]:
        print("  REJECT", "%s/%s" % key, "; ".join(reasons))
    if len(rejected) > 20:
        print("  ... %d more rejected" % (len(rejected) - 20))
    for item_id, reason, detail in skipped[:20]:
        print("  SKIP", item_id, reason, detail)
    if len(skipped) > 20:
        print("  ... %d more skipped" % (len(skipped) - 20))

    if not accepted:
        return
    if args.dry_run:
        print("dry-run: would update", args.curves_file)
        return
    _apply_insertions(args.curves_file, coss_entries, ciss_entries, source_entries,
                      pending_coss, pending_ciss)
    print("updated", args.curves_file)


if __name__ == "__main__":
    main()
