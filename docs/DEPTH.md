# 深度登记 预制梁张拉记录

- 规模：中型
- 核心规则：按实测力级外推零点，分端补偿锚回缩，然后同时复核双端与合计。
- 使用者与流程：班组质检员导入三份读数，按梁复核并归档。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 采信 | 检视有效读数、隔离及重复 | `GET /api/sampling/{id}` | `app/modules/m1_sampling/source.py` | `tests/test_sampling.py` |
| M2 标定 | 查看标定登记及版本有效日 | `GET /api/calibration/{id}` | `app/modules/m2_calibration/registry.py` | `tests/test_calibration.py` |
| M3 对齐 | 按力级核对实测载荷及原设计 | `GET /api/alignment/{id}` | `app/modules/m3_alignment/service.py` | `tests/test_alignment.py` |
| M4 补偿 | 查外推零点与锚回缩 | `GET /api/elongation/{id}` | `app/modules/m4_elongation/formula.py` | `tests/test_elongation.py` |
| M5 判验 | 比较两端允许偏差并查看总伸长 | `GET /api/verdicts/{id}` | `app/modules/m5_verdicts/service.py` | `tests/test_verdicts.py` |
| M6 勾稽 | 检查读数守恒及梁的钢束归类 | `GET /api/reconcile/{id}` | `app/modules/m6_reconcile/service.py` | `tests/test_reconcile.py` |
| M7 复算 | 重跑班次、查看批号并导出 | `GET /api/runs/{id}` | `app/modules/m7_runs/service.py` | `tests/test_runs.py` |
| M8 处置 | 按端给出处置类型、依据与今晚先后顺序，并裁决梁能否移交发运 | `GET /api/disposition/{id}`、`POST /api/release/{id}` | `app/modules/m8_disposition/service.py` | `tests/test_disposition.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 加 BOM 的对照文件 | 首字符损坏 | 支持 UTF-8 BOM | `app/modules/m1_sampling/source.py` | `tests/test_sampling.py::test_bom` |
| TRAP-06 | 夜班表全角小数 | 解析失败 | NFKC 后按严格十进制处理 | `app/stages.py` | `tests/test_sampling.py::test_fullwidth_and_centimetres` |
| TRAP-07 | 夜班位移 N/A | 被当零点 | 隔离无效记录 | `app/modules/m1_sampling/service.py` | `tests/test_sampling.py::test_na_is_not_displacement` |
| TRAP-08 | 夜班梁号有前导零 | 被改成 7 | 保留字符串 | `app/stages.py` | `tests/test_sampling.py::test_identifier_zeros` |
| TRAP-14 | 同一夜班流水有两个位移 | 后写覆盖 | 同号两条均隔离 | `app/modules/m1_sampling/service.py` | `tests/test_sampling.py::test_disagreeing_ids_both_isolated` |
| TRAP-15 | 夜班位移 cm，载荷混 MPa 和 kN | 伸长差十倍或混算压力 | 统一毫米、用证书折算压力 | `app/modules/m1_sampling/service.py` | `tests/test_sampling.py::test_fullwidth_and_centimetres` |
| TRAP-16 | 对照文件缺尾部 | 流式写入半批 | 解析完毕才计算保存 | `app/modules/m1_sampling/source.py` | `tests/test_sampling.py::test_truncated_file_is_rejected` |
| TRAP-17 | 夜班表旧列 extension | 位移丢失 | 双字段择一兼容 | `app/modules/m1_sampling/service.py` | `tests/test_sampling.py::test_legacy_field` |
| TRAP-23 | 校准证书刚开始生效 | 误报过期 | 生效日含左端 | `app/modules/m2_calibration/registry.py` | `tests/test_calibration.py::test_valid_at_start` |
| TRAP-25 | 同一千斤顶两个证书同日有效 | 随顺序选版 | 隔离对应压力读数 | `app/modules/m2_calibration/service.py` | `tests/test_calibration.py::test_overlap_has_evidence` |
| TRAP-31 | 缺力级、同号冲突被派成现场复张 | 梁无谓停工 | 记录类问题一律补测/核对，不安排现场复张 | `app/modules/m8_disposition/rules.py` | `tests/test_disposition.py::test_missing_level_is_not_field_retension` |
| TRAP-32 | 锚回缩超限被一句“复测”带过 | 真实结构问题漏判 | `NO_EXTENSION` 判为超限并单列锚回缩处置，排今晚第一 | `app/modules/m5_verdicts/service.py`、`app/modules/m8_disposition/rules.py` | `tests/test_disposition.py::test_anchor_slip_is_anchor_case` |
| TRAP-33 | 只按钢束结论放行 | 个别端未处置梁也被移交 | 每端处置完毕且全部钢束通过才可移交发运 | `app/modules/m8_disposition/service.py` | `tests/test_disposition.py::test_beam_gate_requires_every_strand_passed` |
| TRAP-34 | 重复上传重复开单 | 同批出现多张处置单 | 内容+规则版本哈希作唯一编号，已有结果直接复用 | `app/modules/m7_runs/store.py` | `tests/test_disposition.py::test_repeat_upload_reuses_same_sheet` |
| TRAP-35 | 重算失败覆盖旧版处置单 | 旧结论丢失 | 先在事务外计算，成功才写回；失败返回 409 并保留旧版 | `app/modules/m7_runs/store.py` | `tests/test_disposition.py::test_refresh_failure_returns_stale` |
| TRAP-36 | 隔离行不进出处置单，查不到原读数 | 处置后无法追溯 | 每端原读数含隔离/判重行，附带记录问题也保留源行 | `app/modules/m8_disposition/service.py` | `tests/test_disposition.py::test_raw_readings_available_per_side` |

## 对账与限制

原始读数与设计钢束分别对账。班组可在结果中查到每条读数的行号，缺测阶段不会补值。样例按单日、单次张拉和三力级设计，实际施工验收须对照项目工艺要求。

## 异常处置口径

- 处置按每一端给出：`处置类型` 取该端全部原因里最重的一类，`处置依据` 保留全部原因码与中文说明，`今晚顺序` 只在待处置端位间连续编号。
- 类型优先级：锚回缩处置 → 现场复张（单端超差）→ 合计复核 → 补测补录 / 记录核对 / 证书核对。前三类属现场处置，现场复张与锚回缩处置会让该梁停等；后三类只补记录，不派现场复张。
- 合计超限只落到真正超差的一端；两端单端都合格时落到偏离理论更大的一端复核，不重复向两端开单。
- 移交发运：某一梁必须全部设计钢束处置完毕且判验为通过（`可移交发运`），本批全部梁可移交时 `移交结论` 才是「可移交发运」；`POST /api/release/{id}` 在仍有未处置或未通过钢束时返回 409。
- 幂等：编号 = sha256(规则版本 + 原始上传)，同批重复上传或重跑只引用同一张处置单（200），不带 `refresh` 不会重算。
- 失败保留：`refresh=1` 时才重算同一张单；计算在事务外完成，失败返回 409 `STALE`，旧版处置单原样可查。
- 原读数：每条处置行内嵌该端全部原始读数（含隔离、判重行与采信状态），附带记录问题保留源行与原读数；处置前后都可在页面或导出中查到。
- 导出：`GET /api/export/{id}` 包含 `清单.处置结论`、`处置摘要`、`处置顺序`、`梁发运`、`附带记录问题` 与各端原读数。
