import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "apps" / "import_coss_review_greens.py"
spec = importlib.util.spec_from_file_location("import_coss_review_greens", SCRIPT)
assert spec and spec.loader
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)


def test_green_items_dedupes_same_review_id(tmp_path):
    review = tmp_path / "packet.review.json"
    item = dict(
        id="infineon/PART/capacitance/fig01",
        mfr="infineon",
        part="PART",
        chart_type="capacitance",
        values="infineon/PART/digitized/capacitance/fig01/values.verify.json",
        human_review={"status": "green"},
    )
    review.write_text(json.dumps(dict(packet="pkt", items=[item, dict(item)])))

    items = imp._green_items([review])

    assert len(items) == 1
    assert items[0]["id"] == "infineon/PART/capacitance/fig01"


def test_green_items_fail_closed_on_conflicting_status(tmp_path):
    green = tmp_path / "green.review.json"
    red = tmp_path / "red.review.json"
    item = dict(id="mfr/PART/capacitance/fig01", mfr="mfr", part="PART",
                chart_type="capacitance", values="mfr/PART/digitized/capacitance/fig01/values.verify.json")
    green.write_text(json.dumps(dict(exported_at="2026-01-01T00:00:00", items=[
        dict(item, human_review={"status": "green"})])))
    red.write_text(json.dumps(dict(exported_at="2026-01-02T00:00:00", items=[
        dict(item, human_review={"status": "rework"})])))

    assert imp._green_items([green, red]) == []
    assert imp._green_items([red, green]) == []


def _write_empty_curves(path):
    path.write_text(
        "COSS_CURVES = {\n}\n"
        "CRSS_CURVES = {\n}\n"
        "CISS_CURVES = {\n}\n"
        "COSS_CURVE_SOURCE = {\n}\n"
        "COSS_CURVE_META = {}\n")


def test_value_path_prefers_shared_backlog(tmp_path):
    backlog = tmp_path / "shared"
    rel = Path("infineon/PART/digitized/capacitance/fig01/values.verify.json")
    path = backlog / rel
    path.parent.mkdir(parents=True)
    path.write_text("{}")

    got_path, got_root = imp._value_path(backlog, {"values": str(rel)})

    assert got_path == path
    assert got_root == backlog


def test_main_skips_second_accepted_curve_for_same_key(monkeypatch, tmp_path):
    curves = tmp_path / "coss_curves.py"
    _write_empty_curves(curves)
    backlog = tmp_path / "backlog"
    rels = []
    for fig in ("fig01", "fig02"):
        rel = Path(f"mfr/PART/digitized/capacitance/{fig}/values.verify.json")
        path = backlog / rel
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"part": "PART", "diagram": fig[-2:]}))
        rels.append(rel)
    review = tmp_path / "packet.review.json"
    review.write_text(json.dumps(dict(items=[
        dict(id="mfr/PART/capacitance/fig01", mfr="mfr", part="PART",
             chart_type="capacitance", values=str(rels[0]), human_review={"status": "green"}),
        dict(id="mfr/PART/capacitance/fig02", mfr="mfr", part="PART",
             chart_type="capacitance", values=str(rels[1]), human_review={"status": "green"}),
    ])))

    @dataclass
    class Result:
        part: str = "PART"
        diagram: str = "01"
        status: str = "pass"
        reasons: list = field(default_factory=list)
        curve: list = field(default_factory=lambda: [(0.0, 1.0, 0.1), (1.0, 0.5, 0.05)])
        anchor_check: dict = field(default_factory=dict)
        qoss_pc: object = None
        knots: int = 2
        source_points: int = 2
        overlay: object = None
        points_csv: object = None
        pdf: object = None
        ciss_status: str = "absent"
        ciss_reasons: list = field(default_factory=lambda: ["no_ciss_trace"])
        ciss_curve: list = field(default_factory=list)

    monkeypatch.setattr(imp, "_load_dsdig_export", lambda _home: lambda _row, _root: Result())
    monkeypatch.setattr(imp.sys, "argv", [
        "import_coss_review_greens.py", "--backlog-root", str(backlog),
        "--curves-file", str(curves), str(review)])

    imp.main()

    text = curves.read_text()
    assert text.count("('mfr', 'PART')") == 3  # Coss + Crss + source; Ciss absent


def test_main_accepts_coss_and_ciss_when_crss_is_rejected(monkeypatch, tmp_path):
    curves = tmp_path / "coss_curves.py"
    _write_empty_curves(curves)
    backlog = tmp_path / "backlog"
    rel = Path("mfr/PART/digitized/capacitance/fig01/values.verify.json")
    path = backlog / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"part": "PART", "diagram": "01"}))
    review = tmp_path / "packet.review.json"
    review.write_text(json.dumps(dict(items=[
        dict(id="mfr/PART/capacitance/fig01", mfr="mfr", part="PART",
             chart_type="capacitance", values=str(rel),
             human_review={"status": "green"}),
    ])))

    @dataclass
    class Result:
        part: str = "PART"
        diagram: str = "01"
        status: str = "rejected"
        reasons: list = field(default_factory=lambda: ["crss_anchor_mismatch:+50%"])
        curve: list = field(default_factory=list)
        coss_status: str = "pass"
        coss_reasons: list = field(default_factory=list)
        coss_curve: list = field(
            default_factory=lambda: [(0.0, 1000.0), (40.0, 500.0)])
        crss_status: str = "rejected"
        crss_reasons: list = field(
            default_factory=lambda: ["crss_anchor_mismatch:+50%"])
        crss_curve: list = field(default_factory=list)
        anchor_check: dict = field(default_factory=lambda: {
            "Coss": {"spec_pf": 500.0, "vds_v": 40.0, "rel_error": 0.0},
            "Ciss": {"spec_pf": 2000.0, "vds_v": 40.0, "rel_error": 0.0},
        })
        qoss_pc: object = None
        knots: int = 2
        source_points: int = 2
        overlay: object = None
        points_csv: object = None
        pdf: object = None
        ciss_status: str = "pass"
        ciss_reasons: list = field(default_factory=list)
        ciss_curve: list = field(
            default_factory=lambda: [(0.0, 2100.0), (40.0, 2000.0)])

    monkeypatch.setattr(imp, "_load_dsdig_export",
                        lambda _home: lambda _row, _root: Result())
    monkeypatch.setattr(imp.sys, "argv", [
        "import_coss_review_greens.py", "--backlog-root", str(backlog),
        "--curves-file", str(curves), str(review)])

    imp.main()

    namespace = {}
    exec(curves.read_text(), namespace)
    key = ("mfr", "PART")
    assert namespace["COSS_CURVES"][key] == [(0.0, 1000.0), (40.0, 500.0)]
    assert key not in namespace["CRSS_CURVES"]
    assert namespace["CISS_CURVES"][key] == [(0.0, 2100.0), (40.0, 2000.0)]
    validation = namespace["COSS_CURVE_SOURCE"][key]["validation_method"]
    assert "Coss + Qoss" in validation
    assert "Ciss" not in validation


def test_main_existing_coss_does_not_block_new_ciss(monkeypatch, tmp_path):
    curves = tmp_path / "coss_curves.py"
    curves.write_text(
        "COSS_CURVES = {\n"
        "    ('mfr', 'PART'): [(0, 1000, 100), (40, 500, 20)],\n"
        "}\n"
        "CRSS_CURVES = {\n}\n"
        "CISS_CURVES = {\n}\n"
        "COSS_CURVE_SOURCE = {\n"
        "    ('mfr', 'PART'): {},\n"
        "}\n"
        "COSS_CURVE_META = {}\n")
    backlog = tmp_path / "backlog"
    rel = Path("mfr/PART/digitized/capacitance/fig01/values.verify.json")
    path = backlog / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"part": "PART", "diagram": "01"}))
    review = tmp_path / "packet.review.json"
    review.write_text(json.dumps(dict(items=[
        dict(id="mfr/PART/capacitance/fig01", mfr="mfr", part="PART",
             chart_type="capacitance", values=str(rel),
             human_review={"status": "green"}),
    ])))

    @dataclass
    class Result:
        part: str = "PART"
        diagram: str = "01"
        status: str = "pass"
        reasons: list = field(default_factory=list)
        curve: list = field(
            default_factory=lambda: [(0.0, 1000.0, 100.0), (40.0, 500.0, 20.0)])
        anchor_check: dict = field(default_factory=dict)
        qoss_pc: object = None
        knots: int = 2
        source_points: int = 2
        overlay: object = None
        points_csv: object = None
        pdf: object = None
        ciss_status: str = "pass"
        ciss_reasons: list = field(default_factory=list)
        ciss_curve: list = field(
            default_factory=lambda: [(0.0, 2100.0), (40.0, 2000.0)])

    monkeypatch.setattr(imp, "_load_dsdig_export",
                        lambda _home: lambda _row, _root: Result())
    monkeypatch.setattr(imp.sys, "argv", [
        "import_coss_review_greens.py", "--backlog-root", str(backlog),
        "--curves-file", str(curves), str(review)])

    imp.main()

    namespace = {}
    exec(curves.read_text(), namespace)
    assert namespace["CISS_CURVES"][("mfr", "PART")] == [
        (0.0, 2100.0), (40.0, 2000.0)]


def test_absolute_value_path_derives_backlog_root():
    path = Path("/tmp/shared/mfr/PART/digitized/capacitance/fig01/values.verify.json")

    got_path, got_root = imp._value_path(Path("/unused"), {"values": str(path)})

    assert got_path == path
    assert got_root == Path("/tmp/shared")


def test_value_path_prefers_packet_local_review_backlog_over_shared(tmp_path):
    backlog = tmp_path / "shared"
    run_dir = tmp_path / "run"
    review = run_dir / "packet.review.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}")
    rel = Path("infineon/PART/digitized/capacitance/fig01/values.verify.json")
    shared = backlog / rel
    shared.parent.mkdir(parents=True)
    shared.write_text("shared")
    local = run_dir / "review-backlog" / rel
    local.parent.mkdir(parents=True)
    local.write_text("local")

    got_path, got_root = imp._value_path(
        backlog, {"values": str(rel), "_packet_file": str(review)})

    assert got_path == local
    assert got_root == run_dir / "review-backlog"


def test_main_skips_values_file_for_different_part(monkeypatch, tmp_path):
    curves = tmp_path / "coss_curves.py"
    _write_empty_curves(curves)
    backlog = tmp_path / "backlog"
    rel = Path("mfr/PART/digitized/capacitance/fig01/values.verify.json")
    path = backlog / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"part": "OTHER", "diagram": "01"}))
    review = tmp_path / "packet.review.json"
    review.write_text(json.dumps(dict(items=[
        dict(id="mfr/PART/capacitance/fig01", mfr="mfr", part="PART",
             chart_type="capacitance", values=str(rel), human_review={"status": "green"}),
    ])))
    calls = []
    monkeypatch.setattr(imp, "_load_dsdig_export", lambda _home: lambda _row, _root: calls.append(_row))
    monkeypatch.setattr(imp.sys, "argv", [
        "import_coss_review_greens.py", "--backlog-root", str(backlog),
        "--curves-file", str(curves), str(review)])

    imp.main()

    assert calls == []
    assert "('mfr', 'PART')" not in curves.read_text()


def test_value_path_falls_back_to_out_review_backlog_for_detached_review(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(imp, "REPO", repo)
    rel = Path("epc/EPC2361/digitized/capacitance/fig901/values.verify.json")
    path = repo / "out" / "proj" / "coss-review-top50-date" / "review-backlog" / rel
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    detached = repo / ".vibe-drops" / "packet.review.json"
    detached.parent.mkdir(parents=True)
    detached.write_text("{}")

    got_path, got_root = imp._value_path(
        tmp_path / "shared", {"values": str(rel), "_packet_file": str(detached)})

    assert got_path == path
    assert got_root == path.parents[5]


def test_value_path_falls_back_to_packet_local_review_backlog(tmp_path):
    backlog = tmp_path / "shared"
    run_dir = tmp_path / "run"
    review = run_dir / "packet.review.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}")
    rel = Path("infineon/PART/digitized/capacitance/fig01/values.verify.json")
    path = run_dir / "review-backlog" / rel
    path.parent.mkdir(parents=True)
    path.write_text("{}")

    got_path, got_root = imp._value_path(
        backlog, {"values": str(rel), "_packet_file": str(review)})

    assert got_path == path
    assert got_root == run_dir / "review-backlog"
