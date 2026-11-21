import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter

from app.config import VERSION
from app.modules.m1_sampling.service import accept
from app.modules.m1_sampling.source import load
from app.modules.m2_calibration.registry import calibrations
from app.modules.m2_calibration.service import convert
from app.modules.m3_alignment.service import align
from app.modules.m3_alignment.targets import parse_targets
from app.modules.m4_elongation.service import compensate
from app.modules.m5_verdicts.service import classify
from app.modules.m6_reconcile.service import ledger
from app.modules.m8_disposition.service import build as build_disposition
from app.modules.m7_runs.store import Stale
from app.stages import label


def digest(data):
    return hashlib.sha256(data).hexdigest()


def serialized(value):
    if isinstance(value, Decimal):
        return label(value)
    return value.isoformat()


def _tally(rows):
    counts = {}
    for row in rows:
        if row["待处置"]:
            counts[row["处置类型"]] = counts.get(row["处置类型"], 0) + 1
    return counts


def calculate(data):
    began = perf_counter()
    payload = load(data)
    records, first_issues, duplicates = accept(payload["readings"])
    registry = calibrations(payload["calibrations"])
    targets = parse_targets(payload["targets"])
    forces, calibration_issues = convert(records, registry)
    aligned, force_issues = align(forces, targets)
    measurements = compensate(aligned, targets)
    verdicts = classify(targets, measurements)
    issues = sorted(first_issues + calibration_issues + force_issues, key=lambda row: row["源行"])
    conservation, beams = ledger(len(payload["readings"]), aligned, issues, duplicates, verdicts)
    disposition = build_disposition(
        targets,
        measurements,
        verdicts,
        issues,
        duplicates,
        aligned,
        payload["readings"],
    )
    output = {
        "清单": {
            "编号": digest(VERSION.encode() + data)[:24],
            "摘要": digest(data),
            "规则": VERSION,
            "计算时间": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "时区": "Asia/Shanghai",
            "耗时毫秒": round((perf_counter() - began) * 1000),
            "处置结论": disposition["移交结论"],
            "待处置端位": disposition["待处置端位"],
        },
        "原始采信": [
            {
                "源行": r["line"],
                "梁号": r["beam"],
                "钢束": r["strand"],
                "端位": r["end"],
                "位移毫米": r["stroke"],
                "读数": r["force"],
                "单位": r["unit"],
            }
            for r in records
        ],
        "标定依据": [
            {
                "千斤顶": r["jack"],
                "版本": r["revision"],
                "生效日": r["start"],
                "截止日": r["end"],
                "斜率": r["slope"],
                "截距": r["offset"],
            }
            for r in registry
        ],
        "力级记录": [
            {
                "源行": r["line"],
                "梁号": r["beam"],
                "钢束": r["strand"],
                "端位": r["end"],
                "力级%": r["level"],
                "载荷千牛": r["kn"],
                "采信来源": r["revision"],
            }
            for r in aligned.values()
        ],
        "补偿记录": [
            {"梁号": key[0], "钢束": key[1], "端位": key[2], **r} for key, r in measurements.items()
        ],
        "判验": verdicts,
        "读数勾稽": conservation,
        "梁号勾稽": beams,
        "处置摘要": {
            "移交结论": disposition["移交结论"],
            "待处置端位": disposition["待处置端位"],
            "优先现场处置": disposition["优先现场处置"],
            "梁": [
                {
                    "梁号": row["梁号"],
                    "结论": row["结论"],
                    "可移交发运": row["可移交发运"],
                    "阻断钢束": row["阻断钢束"],
                }
                for row in disposition["梁发运"]
            ],
            "按类型": _tally(disposition["处置顺序"]),
        },
        **disposition,
        "隔离": issues,
        "重复": duplicates,
    }
    return json.loads(json.dumps(output, default=serialized, ensure_ascii=False))


def run_once(history, data, refresh=False):
    """同一批内容只开一张处置单；refresh 时才重算同一张单。

    重算失败会抛出 History 的 Stale，旧版处置单原样保留。
    """
    key = digest(VERSION.encode() + data)[:24]
    existing = history.find(key)
    if existing is not None and not refresh:
        return existing, True
    if existing is None:
        return history.publish(key, lambda: calculate(data), source=data)
    return history.recompute(key, lambda: calculate(data)), True


def run_stored(history, key):
    """从存档的原始上传重算同一张处置单，不新开单。

    没有原始上传（旧版只存结果）或重算失败时抛 History 的 Stale。
    """
    source = history.source_of(key)
    if source is None:
        raise Stale("该批次没有保存原始上传，无法原地重算")
    return history.recompute(key, lambda: calculate(source))