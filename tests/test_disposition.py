import io
import json

import pytest

from app.modules.m7_runs.service import calculate, run_once
from app.modules.m7_runs.store import History, Stale
from app.modules.m8_disposition.rules import (
    ANCHOR,
    CERTIFICATE,
    NO_ACTION,
    RECORD,
    REMEASURE,
    RETENSION,
    REVIEW,
)
from app.modules.m8_disposition.service import build


def side(rows, beam, strand, end):
    return next(
        row
        for row in rows
        if (row["梁号"], row["钢束"], row["端位"]) == (beam, strand, end)
    )


def test_every_target_has_both_ends(report):
    assert len(report["处置顺序"]) == 2 * len(report["判验"])
    assert {row["端位"] for row in report["处置顺序"]} == {"L", "R"}


def test_missing_level_is_not_field_retension(report):
    row = side(report["处置顺序"], "0007", "S03", "R")
    assert row["处置类型"] == REMEASURE
    assert row["现场复张"] is False and row["停工"] is False


def test_id_conflict_is_record_check(report):
    row = side(report["处置顺序"], "0009", "S03", "R")
    assert row["处置类型"] == REMEASURE
    assert "ID_CONFLICT" in row["处置依据"]
    assert row["现场复张"] is False


def test_certificate_overlap_is_certificate_check(report):
    row = side(report["处置顺序"], "0008", "S02", "L")
    assert "CAL_OVERLAP" in row["处置依据"]
    assert row["现场复张"] is False


def test_side_tolerance_is_field_retension(report):
    row = side(report["处置顺序"], "0007", "S02", "L")
    assert row["处置类型"] == RETENSION
    assert row["现场复张"] is True and row["停工"] is True
    assert row["处置依据"] == ["SIDE_TOLERANCE", "TOTAL_TOLERANCE"]


def test_anchor_slip_is_anchor_case():
    content = json.loads(open("sample_data/checked.json", "rb").read())
    content["targets"][0]["L_anchor"] = "40"
    report = calculate(json.dumps(content, ensure_ascii=False).encode())
    row = side(report["处置顺序"], "0007", "S01", "L")
    assert row["处置类型"] == ANCHOR
    assert report["判验"][0]["判验"] == "超限"


def test_passing_strand_is_released(report):
    row = side(report["处置顺序"], "0007", "S01", "L")
    assert row["处置类型"] == NO_ACTION and row["今晚顺序"] is None


def test_field_work_comes_before_record_work(report):
    ordered = [row for row in report["处置顺序"] if row["今晚顺序"] is not None]
    ordinals = sorted(row["今晚顺序"] for row in ordered)
    assert ordinals == list(range(1, len(ordered) + 1))
    positions = {row["今晚顺序"]: row for row in ordered}
    assert positions[1]["现场复张"] is True
    assert all(not positions[index]["现场复张"] for index in ordinals if index > 1)


def test_order_has_no_gaps_or_duplicates(report):
    numbers = [row["今晚顺序"] for row in report["处置顺序"] if row["今晚顺序"] is not None]
    assert numbers == list(range(1, len(numbers) + 1))


def test_beam_cannot_ship_with_open_items(report):
    for row in report["梁发运"]:
        assert row["可移交发运"] is False
        assert row["结论"] == "不可移交"
        assert row["阻断钢束"]


def test_clean_batch_ships(check):
    assert check["移交结论"] == "可移交发运"
    assert all(row["可移交发运"] for row in check["梁发运"])
    assert check["待处置端位"] == 0


def test_beam_gate_requires_every_strand_passed(check):
    content = json.loads(open("sample_data/checked.json", "rb").read())
    content["targets"].append(
        {**content["targets"][0], "strand": "S02", "L_mm": "20", "R_mm": "20"}
    )
    report = calculate(json.dumps(content, ensure_ascii=False).encode())
    gate = next(row for row in report["梁发运"] if row["梁号"] == "0007")
    assert gate["设计钢束"] == 2 and gate["已通过钢束"] == 1
    assert gate["可移交发运"] is False
    assert gate["阻断钢束"] == ["S02"]


def test_raw_readings_available_per_side(report):
    row = side(report["处置顺序"], "0008", "S02", "R")
    lines = [raw["源行"] for raw in row["原读数"]]
    assert lines == [28, 29, 30, 37]
    assert any(raw["采信状态"].startswith("隔离") for raw in row["原读数"])


def test_raw_readings_survive_after_disposition(report, checked):
    before = side(report["处置顺序"], "0007", "S02", "L")["原读数"]
    after = side(calculate(checked)["处置顺序"], "0007", "S01", "L")["原读数"]
    assert before and after
    assert [raw["源行"] for raw in before] == [8, 9, 10]


def test_orphan_row_keeps_its_raw_line(report):
    orphan = report["附带记录问题"][0]
    assert orphan["原因码"] == "NO_TARGET"
    assert orphan["原读数"][0]["源行"] == 33
    assert orphan["原读数"][0]["读数"] == "100"


def test_repeat_upload_reuses_same_sheet(tmp_path, checked):
    history = History(tmp_path / "runs.sqlite")
    first, reused = run_once(history, checked)
    second, reused_again = run_once(history, checked)
    assert (reused, reused_again) == (False, True)
    assert first["清单"]["编号"] == second["清单"]["编号"]
    assert len(history.recent()) == 1


def test_failed_recompute_keeps_old_sheet(tmp_path, checked):
    history = History(tmp_path / "runs.sqlite")
    sheet, _ = run_once(history, checked)
    key = sheet["清单"]["编号"]
    with pytest.raises(Stale):
        history.recompute(key, lambda: (_ for _ in ()).throw(RuntimeError("计算失败")))
    kept = history.find(key)
    assert kept["处置顺序"] == sheet["处置顺序"]
    assert kept["移交结论"] == sheet["移交结论"]


def test_refresh_recomputes_in_place(tmp_path, checked):
    history = History(tmp_path / "runs.sqlite")
    sheet, _ = run_once(history, checked)
    key = sheet["清单"]["编号"]
    refreshed, reused = run_once(history, checked, refresh=True)
    assert reused and refreshed["清单"]["编号"] == key
    assert len(history.recent()) == 1


def test_refresh_failure_returns_stale(client, monkeypatch):
    run = client.post("/api/runs", json={"sample": "checked"}).json
    from app.modules.m7_runs import service as service_module

    def boom(data):
        raise RuntimeError("坏数据")

    monkeypatch.setattr(service_module, "calculate", boom)
    response = client.post("/api/runs", json={"sample": "checked", "refresh": True})
    assert response.status_code == 409
    assert response.json["code"] == "STALE"
    kept = client.get(f"/api/disposition/{run['id']}").json
    assert kept["移交结论"] == "可移交发运"


def test_release_gate_blocks_open_items(client):
    run = client.post("/api/runs", json={"sample": "yard"}).json
    response = client.post(f"/api/release/{run['id']}")
    assert response.status_code == 409
    assert response.json["code"] == "NOT_RELEASABLE"


def test_release_gate_allows_clean_beam(client):
    run = client.post("/api/runs", json={"sample": "checked"}).json
    response = client.post(f"/api/release/{run['id']}")
    assert response.status_code == 200
    assert response.json["code"] == "RELEASED"


def test_corrected_upload_keeps_old_batch_readings(client, yard):
    original = client.post("/api/runs", data={"file": (io.BytesIO(yard), "yard.json")}).json
    content = json.loads(yard)
    content["readings"][9]["stroke"] = "27"  # 处置后重录：0007/S02 左端峰值归一
    corrected = client.post(
        "/api/runs", data={"file": (io.BytesIO(json.dumps(content).encode()), "fixed.json")}
    ).json
    assert corrected["id"] != original["id"]
    old = client.get(f"/api/disposition/{original['id']}").json
    new = client.get(f"/api/disposition/{corrected['id']}").json
    old_side = side(old["处置顺序"], "0007", "S02", "L")
    new_side = side(new["处置顺序"], "0007", "S02", "L")
    assert old_side["原读数"][2]["位移"] == "32"
    assert new_side["原读数"][2]["位移"] == "27"
    assert old_side["处置类型"] == RETENSION
    assert new_side["处置类型"] == NO_ACTION


def test_export_carries_disposition(client):
    run = client.post("/api/runs", json={"sample": "yard"}).json
    export = client.get(f"/api/export/{run['id']}").json
    assert export["清单"]["处置结论"] == "暂缓发运"
    assert export["处置摘要"]["待处置端位"] == export["待处置端位"]
    assert export["处置顺序"][0]["原读数"]
    assert export["梁发运"]
