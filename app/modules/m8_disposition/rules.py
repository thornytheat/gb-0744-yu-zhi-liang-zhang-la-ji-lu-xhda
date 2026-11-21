"""异常钢束的处置分类。

现场问题（锚回缩超限、伸长超限）才安排现场处置；缺力级、
同号冲突、证书重叠等属于记录问题，只补测补录或核对，不派现场复张，
避免梁无谓停工。真实锚回缩超限优先级最高，不会被一句“复测”带过。
"""

NO_ACTION = "放行"
REVIEW = "合计复核"
RETENSION = "现场复张"
ANCHOR = "锚回缩处置"
REMEASURE = "补测补录"
RECORD = "记录核对"
CERTIFICATE = "证书核对"

FIELD = "现场处置"
PAPER = "记录处理"

# 数值越小越先处置。锚回缩是真实且不可逆的现场问题，排第一。
TYPE_RANK = {
    NO_ACTION: 0,
    ANCHOR: 1,
    RETENSION: 2,
    REVIEW: 3,
    REMEASURE: 4,
    RECORD: 5,
    CERTIFICATE: 6,
}

TYPE_CODE = {
    NO_ACTION: "PASS",
    ANCHOR: "ANCHOR_SLIP",
    RETENSION: "FIELD_RETENSION",
    REVIEW: "TOTAL_REVIEW",
    REMEASURE: "REMEASURE",
    RECORD: "RECORD_CHECK",
    CERTIFICATE: "CERT_CHECK",
}

# 夜间先后顺序：先做真实、会影响结构受力的现场处置，再做记录类核对。
TYPE_ORDER_LABEL = {
    ANCHOR: "第一优先：立即现场处置（锚回缩）",
    RETENSION: "第一优先：立即现场处置（伸长超限）",
    REVIEW: "第二优先：现场复核合计",
    REMEASURE: "第三优先：补测补录，不安排现场复张",
    RECORD: "第三优先：记录核对，不安排现场复张",
    CERTIFICATE: "第三优先：证书核对，不安排现场复张",
}

TYPE_GROUP = {
    NO_ACTION: "放行",
    ANCHOR: FIELD,
    RETENSION: FIELD,
    REVIEW: FIELD,
    REMEASURE: PAPER,
    RECORD: PAPER,
    CERTIFICATE: PAPER,
}

# 只有真实锚固/伸长问题需要现场复张并停等；记录问题当天可并行处理。
FIELD_RETENSION = {ANCHOR: True, RETENSION: True, REVIEW: False}
STOPS_BEAM = {ANCHOR: True, RETENSION: True}

REASON_LABEL = {
    "SIDE_TOLERANCE": "单端有效伸长相对偏差超过 10%",
    "TOTAL_TOLERANCE": "双端合计相对偏差超过 6%",
    "NO_EXTENSION": "锚固回缩吃掉全部伸长（锚回缩超限）",
    "MISSING_LEVEL": "缺少 20%/40%/100% 力级读数",
    "REVERSED": "位移随力级未严格增加，读数顺序不可用",
    "ID_CONFLICT": "同一流水号读数互相矛盾，整组隔离",
    "LEVEL_CONFLICT": "同一端同一力级存在两条合格读数",
    "CAL_OVERLAP": "千斤顶同一天存在多份有效证书",
    "CAL_MISSING": "千斤顶在读数日没有有效证书",
    "CAL_NEGATIVE": "证书折算后的载荷非正",
    "BAD_READING": "原始读数结构无效或位移缺失",
    "FORCE_TOLERANCE": "实测载荷超出力级 ±5%",
    "NO_TARGET": "读数没有对应的设计钢束",
    "DUPLICATE": "重复流水号，保留首条",
}

CERT_REASONS = {"CAL_OVERLAP", "CAL_MISSING", "CAL_NEGATIVE"}
PHYSICAL_REASONS = {"SIDE_TOLERANCE", "TOTAL_TOLERANCE", "NO_EXTENSION"}
RECORD_REASONS = {"ID_CONFLICT", "LEVEL_CONFLICT", "NO_TARGET"}


def reason_type(code):
    if code == "NO_EXTENSION":
        return ANCHOR
    if code == "SIDE_TOLERANCE":
        return RETENSION
    if code == "TOTAL_TOLERANCE":
        return REVIEW
    if code in CERT_REASONS:
        return CERTIFICATE
    if code in RECORD_REASONS:
        return RECORD
    if code == "DUPLICATE":
        return NO_ACTION
    return REMEASURE


def disposition_type(codes):
    """取最重的处置类型；同一端的所有原因都保留在依据里。"""
    candidates = [reason_type(code) for code in codes]
    if not candidates:
        return NO_ACTION
    return min(candidates, key=lambda name: TYPE_RANK[name])


def rank(name):
    return TYPE_RANK.get(name, len(TYPE_RANK))


def group(name):
    return TYPE_GROUP.get(name, PAPER)


def code_for(name):
    return TYPE_CODE.get(name, "UNKNOWN")


def is_field_retension(name):
    return FIELD_RETENSION.get(name, False)


def stops_beam(name):
    return STOPS_BEAM.get(name, False)


def explanation(code):
    return REASON_LABEL.get(code, code)


def recheck_reading(hint):
    """处置依据里给班组的下一动作，避免把记录问题当成现场复张。"""
    if hint == ANCHOR:
        return "复核锚具与锚固回缩记录，按工艺要求现场处置并重测该端三力级"
    if hint == RETENSION:
        return "核对该端张拉规程后现场复张，留取处置后的三力级读数"
    if hint == REVIEW:
        return "现场量测两端伸长并复算合计，不需要整束重拉"
    if hint == REMEASURE:
        return "补齐缺失力级或重测该端，不安排现场复张"
    if hint == RECORD:
        return "核对流水号、力级与原始记录，确认后补录，不安排现场复张"
    if hint == CERTIFICATE:
        return "核对千斤顶标定证书覆盖期，换用唯一有效证书后复算"
    return ""
