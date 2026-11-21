from app.web import batch
from flask import Blueprint, jsonify

router = Blueprint("disposition", __name__)

FIELDS = ("处置顺序", "梁发运", "附带记录问题", "移交结论", "待处置端位", "优先现场处置")


@router.get("/api/disposition/<key>")
def disposition(key):
    value = batch(key)
    if "处置顺序" not in value:
        return jsonify(code="LEGACY", detail="该批次由旧版规则存档，请重新复算后生成处置单"), 409
    return jsonify({field: value[field] for field in FIELDS})

