"""按梁、钢束、端位生成处置顺序与发运门禁。

处置是判验结果的派生视图：同一批内容重算只会复用同一张处置单，
不会因为重复上传而多开单。每端都保留原始读数（含被隔离和判重的行），
处置前后都能追溯到具体源行。
"""

from collections import OrderedDict

from app.modules.m1_sampling.service import END_NAMES
from app.modules.m8_disposition.rules import (
    NO_ACTION,
    PHYSICAL_REASONS,
    TYPE_ORDER_LABEL,
    code_for,
    disposition_type,
    explanation,
    group,
    is_field_retension,
    rank,
    recheck_reading,
    reason_type,
    stops_beam,
)

SIDE_TITLES = {"L": "左端", "R": "右端"}


def _ordered(values):
    seen = OrderedDict()
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _safe_text(value):
    if isinstance(value, str):
        return value[:80]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return "—"


def _side_codes(measurement, verdict, issues, end, total_reasons):
    codes = []
    if measurement.get("原因码"):
        codes.append(measurement["原因码"])
    for reason in verdict.get("证据", []):
        if reason.startswith(f"{end}-"):
            codes.append(reason.split("-", 1)[1])
    codes.extend(row["原因码"] for row in issues if row.get("端位") == end)
    if end in total_reasons:
        codes.append("TOTAL_TOLERANCE")
    return _ordered(codes)


def _total_ends(verdict, target, measurements, beam, strand):
    """合计超限落到真正超差的一端，避免两端重复开单。

    若已有单端超差，合计问题跟随该端；两端单端都合格时，
    落到偏离理论更大的那一端（并列取左端）做合计复核。
    """
    if "TOTAL_TOLERANCE" not in verdict.get("证据", []):
        return set()
    weak = {
        end for end in ("L", "R") if f"{end}-SIDE_TOLERANCE" in verdict.get("证据", [])
    }
    if weak:
        return weak
    scores = {}
    for end in ("L", "R"):
        actual = measurements[(beam, strand, end)].get("有效毫米")
        if actual is None:
            return {"L", "R"}
        scores[end] = abs(actual - target["theory"][end])
    return {max(("L", "R"), key=lambda end: (scores[end], end == "L"))}


def _side_status(codes):
    effective = [code for code in codes if reason_type(code) != NO_ACTION]
    if not effective:
        return "通过"
    return "超限" if set(effective) & PHYSICAL_REASONS else "待复测"


def _key_text(value):
    return value.strip() if isinstance(value, str) else value


def _raw_side(raw_rows, force_index, issue_codes, duplicate_codes, beam, strand, end):
    rows = []
    for offset, raw in enumerate(raw_rows, 1):
        if not isinstance(raw, dict):
            continue
        raw_end = raw.get("end")
        normalized = END_NAMES.get(_key_text(raw_end)) if isinstance(raw_end, str) else None
        if (_key_text(raw.get("beam")), _key_text(raw.get("strand")), normalized) != (
            beam,
            strand,
            end,
        ):
            continue
        state = "采信"
        if offset in issue_codes:
            state = f"隔离·{issue_codes[offset]}"
        elif offset in duplicate_codes:
            state = "重复"
        stroke = raw.get("stroke", raw.get("extension"))
        aligned = force_index.get(offset)
        rows.append(
            {
                "源行": offset,
                "力级%": _safe_text(raw.get("level")),
                "读数": _safe_text(raw.get("force")),
                "单位": _safe_text(raw.get("unit")),
                "位移": _safe_text(stroke),
                "位移单位": _safe_text(raw.get("displacement_unit", "mm")),
                "采信状态": state,
                "对齐千牛": None if aligned is None else aligned["kn"],
                "对齐位移毫米": None if aligned is None else aligned["stroke"],
            }
        )
    return rows


def _raw_line(raw_rows, line, force_index):
    """孤立问题（无对应钢束、设计外的行）也保留原始读数。"""
    if not 1 <= line <= len(raw_rows) or not isinstance(raw_rows[line - 1], dict):
        return []
    raw = raw_rows[line - 1]
    aligned = force_index.get(line)
    return [
        {
            "源行": line,
            "梁号": _safe_text(raw.get("beam")),
            "钢束": _safe_text(raw.get("strand")),
            "端位": _safe_text(raw.get("end")),
            "力级%": _safe_text(raw.get("level")),
            "读数": _safe_text(raw.get("force")),
            "单位": _safe_text(raw.get("unit")),
            "位移": _safe_text(raw.get("stroke", raw.get("extension"))),
            "位移单位": _safe_text(raw.get("displacement_unit", "mm")),
            "采信状态": "采信" if aligned is not None else "隔离",
            "对齐千牛": None if aligned is None else aligned["kn"],
            "对齐位移毫米": None if aligned is None else aligned["stroke"],
        }
    ]


def _next_steps(codes):
    steps = []
    for code in codes:
        step = recheck_reading(reason_type(code))
        if step and step not in steps:
            steps.append(step)
    return steps


def _side_row(beam, strand, end, verdict, codes, raw, force_index, issue_codes, dup_codes):
    kind = disposition_type(codes)
    return {
        "梁号": beam,
        "钢束": strand,
        "端位": end,
        "端位名称": SIDE_TITLES[end],
        "钢束判验": verdict["判验"],
        "端判验": _side_status(codes),
        "处置类型": kind,
        "处置编码": code_for(kind),
        "处置分组": group(kind),
        "处置优先级": TYPE_ORDER_LABEL.get(kind, ""),
        "下一步": _next_steps(codes),
        "待处置": kind != NO_ACTION,
        "现场复张": is_field_retension(kind),
        "处置依据": codes,
        "依据说明": [explanation(code) for code in codes],
        "今晚顺序": None,
        "停工": stops_beam(kind),
        "原读数": _raw_side(
            raw, force_index, issue_codes, dup_codes, beam, strand, end
        ),
    }


def build(targets, measurements, verdicts, issues, duplicates, aligned, raw_rows):
    verdict_index = {(row["梁号"], row["钢束"]): row for row in verdicts}
    aligned_index = {row["line"]: row for row in aligned.values()}
    issue_index, issue_codes = {}, {}
    for row in issues:
        issue_index.setdefault((row.get("梁号"), row.get("钢束"), row.get("端位")), []).append(row)
        issue_codes[row["源行"]] = row["原因码"]
    duplicate_codes = {row["源行"]: row["原因码"] for row in duplicates}

    rows, beam_index = [], {}
    for (beam, strand), target in targets.items():
        verdict = verdict_index[(beam, strand)]
        total_ends = _total_ends(verdict, target, measurements, beam, strand)
        strand_rows = []
        for end in ("L", "R"):
            measurement = measurements[(beam, strand, end)]
            codes = _side_codes(
                measurement,
                verdict,
                issue_index.get((beam, strand, end), []),
                end,
                total_ends,
            )
            strand_rows.append(
                _side_row(
                    beam,
                    strand,
                    end,
                    verdict,
                    codes,
                    raw_rows,
                    aligned_index,
                    issue_codes,
                    duplicate_codes,
                )
            )
        rows.extend(strand_rows)
        pending = [row for row in strand_rows if row["待处置"]]
        entry = beam_index.setdefault(
            beam,
            {
                "梁号": beam,
                "设计钢束": 0,
                "已通过钢束": 0,
                "待处置端位": 0,
                "阻断钢束": [],
            },
        )
        entry["设计钢束"] += 1
        entry["已通过钢束"] += int(verdict["判验"] == "通过")
        entry["待处置端位"] += len(pending)
        for row in pending:
            if row["钢束"] not in entry["阻断钢束"]:
                entry["阻断钢束"].append(row["钢束"])

    beams = []
    for entry in beam_index.values():
        complete = entry["待处置端位"] == 0 and entry["已通过钢束"] == entry["设计钢束"]
        entry.update(
            {
                "处置完毕": not entry["阻断钢束"],
                "结论": "通过" if complete else "不可移交",
                "可移交发运": complete,
            }
        )
        beams.append(entry)

    actionable = [row for row in rows if row["待处置"]]
    actionable.sort(key=lambda row: (rank(row["处置类型"]), row["梁号"], row["钢束"], row["端位"]))
    for index, row in enumerate(actionable, 1):
        row["今晚顺序"] = index
    rows.sort(key=lambda row: (row["梁号"], row["钢束"], row["端位"]))

    attached = {
        (row["梁号"], row["钢束"], code)
        for row in rows
        for code in row["处置依据"]
    }
    seen_lines = set()
    orphans = []
    for row in list(issues) + list(duplicates):
        # 重复行只作采信说明，不另开一张处置单；其余无归属的问题单列。
        if row.get("原因码") == "DUPLICATE":
            continue
        if (row.get("梁号"), row.get("钢束"), row.get("原因码")) in attached:
            continue
        key = (row.get("梁号"), row.get("钢束"), row.get("端位"), row.get("原因码"))
        if key in seen_lines:
            continue
        seen_lines.add(key)
        orphans.append(
            {
                "源行": row["源行"],
                "梁号": row.get("梁号", ""),
                "钢束": row.get("钢束", ""),
                "端位": row.get("端位", ""),
                "原因码": row["原因码"],
                "处置类型": reason_type(row["原因码"]),
                "说明": explanation(row["原因码"]),
                "下一步": _next_steps([row["原因码"]]),
                "停工": False,
                "原读数": _raw_line(raw_rows, row["源行"], aligned_index),
            }
        )

    return {
        "处置顺序": rows,
        "梁发运": sorted(beams, key=lambda row: row["梁号"]),
        "附带记录问题": sorted(orphans, key=lambda row: row["源行"]),
        "移交结论": "可移交发运"
        if beams and all(row["可移交发运"] for row in beams)
        else "暂缓发运",
        "待处置端位": len(actionable),
        "优先现场处置": sum(1 for row in actionable if row["现场复张"]),
    }
