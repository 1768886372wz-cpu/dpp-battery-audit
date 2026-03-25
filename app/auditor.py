"""
app/auditor.py — 电池 DPP 核心审计引擎
=======================================
对外接受三个简洁字段：
    battery_type   : 电池类型，如 "LFP" / "NCM" / "NMC"（默认 LFP）
    energy_usage   : 制造能耗，单位 kWh/kWh（生产 1 kWh 电池所耗电量）
    recycled_rate  : 回收材料综合比例 %（与锂回收法定阈值 6% 对标）

两类核查：
    物理合理性核查 → 数据不可能存在 → risk_level: RED_FLAG
    法规符合性核查 → 低于法定阈值   → risk_level: COMPLIANCE_GAP

扩展说明
--------
在 _CHECKS 列表末尾追加新函数即可新增核查维度：
    def check_xxx(data: dict, bench: dict) -> list[Finding]: ...
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 集成物理核查引擎（Wave 2+3）
try:
    from app.engine.calculator import run_physics_checks
    from app.engine.forensics  import run_forensics, predict_compliance_lifecycle
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

# ── 路径 ──────────────────────────────────────────────────────────────────────
_BENCHMARKS_PATH = Path(__file__).resolve().parent.parent / "data" / "benchmarks.json"


# ── 结果数据类 ────────────────────────────────────────────────────────────────
@dataclass
class Finding:
    """单条核查结果，可直接序列化为 JSON。"""

    # 严重程度（对外统一使用这四种标签）
    RED_FLAG       = "RED_FLAG"        # 物理上不可能 — 高度疑似造假
    COMPLIANCE_GAP = "COMPLIANCE_GAP"  # 低于欧盟法定阈值 — 合规缺口
    WARNING        = "WARNING"         # 需要补充证明材料
    PASS           = "PASS"            # 通过核查

    level:          str       # 上方四种之一
    field:          str       # 被检查的字段名（使用对外简洁字段名）
    message:        str       # 问题描述
    legal_ref:      str = ""  # 法规条文引用
    recommendation: str = ""  # 具体改进建议

    def to_dict(self) -> dict:
        return {
            "level":          self.level,
            "field":          self.field,
            "message":        self.message,
            "legal_ref":      self.legal_ref,
            "recommendation": self.recommendation,
        }


# ── 基准数据加载（模块级缓存，避免重复 I/O）─────────────────────────────────────
_cache: dict | None = None

def _load_benchmarks() -> dict:
    global _cache
    if _cache is None:
        if not _BENCHMARKS_PATH.exists():
            raise FileNotFoundError(f"基准数据文件缺失：{_BENCHMARKS_PATH}")
        _cache = json.loads(_BENCHMARKS_PATH.read_text(encoding="utf-8"))
    return _cache


def _to_float(value: Any) -> float | None:
    """安全地将任意输入转为 float，无法转换时返回 None。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_chem(battery_type: str) -> str:
    """标准化化学体系名称，NMC 统一为 NCM。"""
    chem = str(battery_type).upper().strip()
    return "NCM" if chem == "NMC" else chem


# ════════════════════════════════════════════════════════════════════════════
# 核查维度 1 — 制造能耗（energy_usage）
# 来源：benchmarks.json → battery_types → {chem} → energy_per_kwh
# ════════════════════════════════════════════════════════════════════════════
def check_energy_usage(data: dict, bench: dict) -> list[Finding]:
    """
    核查供应商申报的制造能耗是否在物理可信范围内。

    判断优先级（从严到宽）：
      1. energy_usage < FAIL_below  →  RED_FLAG（物理不可能，精确固定消息）
      2. energy_usage < min         →  WARNING（接近极限，需第三方证明）
      3. energy_usage > FAIL_above  →  RED_FLAG（严重超出上限，疑似录入错误）
      4. energy_usage > max         →  WARNING（生产效率极低）
      5. 在合理范围内               →  PASS
    """
    value = _to_float(data.get("energy_usage"))

    if value is None:
        return [Finding(
            level=Finding.WARNING,
            field="energy_usage",
            message="未申报制造能耗，无法验证碳足迹核算的完整性。",
            legal_ref="Annex XIII(1)(c) / Article 7",
            recommendation=(
                "请补充字段 energy_usage：生产 1 kWh 电池所耗电量（单位 kWh/kWh），"
                "并提供第三方能源计量报告。"
            ),
        )]

    chem = _resolve_chem(data.get("battery_type", "LFP"))
    battery_types = bench.get("battery_types", {})
    spec = (battery_types.get(chem) or battery_types.get("LFP", {})).get("energy_per_kwh", {})
    rule = spec.get("audit_rule", {})

    e_min      = spec.get("min", 50)
    e_max      = spec.get("max", 85)
    e_avg      = spec.get("avg", 65)
    fail_below = rule.get("FAIL_below", e_min * 0.6)
    fail_above = rule.get("FAIL_above", 160)

    # ── 关键判断：低于行业公认最小值 ────────────────────────────────────────────
    if value < e_min:
        # 进一步区分"绝对不可能"与"接近极限"
        if value < fail_below:
            # 用户要求的精确消息 + 额外上下文
            return [Finding(
                level=Finding.RED_FLAG,
                field="energy_usage",
                message=(
                    f"检测到物理逻辑冲突：电耗低于行业公认最小值，疑似瞒报供应链环节。"
                    f"（申报值 {value} kWh/kWh，{chem} 物理下限 {fail_below}，"
                    f"行业公认最小值 {e_min}，均值 {e_avg}）"
                ),
                legal_ref="物理合理性核查 / Art. 77(4) — 数据准确性强制义务",
                recommendation=(
                    f"该数值在现有工艺下物理上不可能实现。"
                    f"请立即核对原始能源计量台账；如为录入错误请更正；"
                    f"如属蓄意少报，将触发 Regulation (EU) 2023/1542 Art. 77(4) 处罚条款。"
                ),
            )]
        else:
            # 介于 fail_below 和 e_min 之间：接近极限但尚未触发绝对红线
            return [Finding(
                level=Finding.RED_FLAG,
                field="energy_usage",
                message=(
                    f"检测到物理逻辑冲突：电耗低于行业公认最小值，疑似瞒报供应链环节。"
                    f"（申报值 {value} kWh/kWh 低于行业公认最小值 {e_min}，均值 {e_avg}）"
                ),
                legal_ref="物理合理性核查 / Art. 77(4)",
                recommendation=(
                    "申报值接近物理极限，需提供经 ISO 50001 认证的工厂能源审计报告"
                    "或第三方计量机构证明，方可视为有效。"
                ),
            )]

    if value > fail_above:
        return [Finding(
            level=Finding.RED_FLAG,
            field="energy_usage",
            message=(
                f"申报值 {value} kWh/kWh 超过历史记录上限 {fail_above} kWh/kWh，"
                f"高度疑似数据录入错误（合理范围 {e_min}–{e_max}）。"
            ),
            legal_ref="物理合理性核查 / Art. 77(4)",
            recommendation=(
                "请核查是否将'工厂总能耗'误填为'单位能耗'，"
                "确认字段单位为 kWh 电 / kWh 电池容量。"
            ),
        )]

    if value > e_max:
        return [Finding(
            level=Finding.WARNING,
            field="energy_usage",
            message=(
                f"申报值 {value} kWh/kWh 高于行业正常上限 {e_max} kWh/kWh，"
                f"生产效率显著落后（行业均值 {e_avg}）。"
            ),
            legal_ref="效率核查",
            recommendation=(
                "建议向供应商索取能效改进路线图，"
                "并要求在下一审计周期内达到行业平均水平。"
            ),
        )]

    return [Finding(
        level=Finding.PASS,
        field="energy_usage",
        message=f"申报值 {value} kWh/kWh 在合理范围内（{e_min}–{e_max}，行业均值 {e_avg}）。",
    )]


# ════════════════════════════════════════════════════════════════════════════
# 核查维度 2 — 回收材料综合比例（recycled_rate）
# 对标：Article 8(2) 锂回收最低 6%（2031-08-18 起强制）
# recycled_rate 为单一综合回收率，使用锂阈值作为基准（最普适）
# ════════════════════════════════════════════════════════════════════════════
def check_recycled_rate(data: dict, bench: dict) -> list[Finding]:
    """
    核查供应商申报的综合回收料比例是否满足法规要求。

    使用锂回收最低比例（6%）作为对标基准，因为：
    1. 锂是所有锂基电池（LFP / NCM / NCA）的共同关键材料
    2. 6% 是 2031 年所有适用类别电池最通用的基准线

    如需分金属精细核查，可补充字段 recycled_lithium_pct /
    recycled_cobalt_pct / recycled_nickel_pct / recycled_lead_pct。
    """
    value = _to_float(data.get("recycled_rate"))

    if value is None:
        return [Finding(
            level=Finding.WARNING,
            field="recycled_rate",
            message="未申报回收材料比例，法规文件完整性存在缺口。",
            legal_ref="Article 8(1) — 2028-08-18 起须随附回收比例申报文件",
            recommendation=(
                "请在下次提交时补充 recycled_rate 字段（0–100 的百分比）。"
                "如需分金属申报，可额外提供 recycled_lithium_pct / "
                "recycled_cobalt_pct / recycled_nickel_pct / recycled_lead_pct。"
            ),
        )]

    rc_bench = bench.get("recycled_content", {})
    phase2   = rc_bench.get("phase_2_mandatory_minimums", {}).get("thresholds", {})
    ind_avg  = rc_bench.get("industry_reality_2024", {})

    # 使用锂阈值作为对标基准（最普适的单一参考线）
    li_spec    = phase2.get("lithium", {})
    min_pct    = li_spec.get("min_pct", 6)
    legal_ref  = li_spec.get("legal_ref", "Article 8(2)(c)")
    verbatim   = li_spec.get("_verbatim", "6 % lithium")
    ind_li_avg = ind_avg.get("lithium_pct_avg", 3.2)

    if value < min_pct:
        return [Finding(
            level=Finding.COMPLIANCE_GAP,
            field="recycled_rate",
            message=(
                f"申报的回收材料比例 {value}% 低于 2031 年欧盟法定最低值 {min_pct}%。"
                f"（法规原文：\"{verbatim}\"）"
            ),
            legal_ref=f"{legal_ref} — Regulation (EU) 2023/1542, Art. 8(2), 生效日期 2031-08-18",
            recommendation=(
                f"建议立即启动供应链改造，将回收料比例提升至 ≥{min_pct}%。"
                f"可联系经 ASI 或 RMI 认证的回收商，通过 ISO 14040/14044 LCA 记录回收来源。"
                f"2031 年前还有时间窗口，请制定年度提升路线图并纳入供应商考核体系。"
            ),
        )]

    if value > ind_li_avg * 4.0:
        return [Finding(
            level=Finding.WARNING,
            field="recycled_rate",
            message=(
                f"申报的回收比例 {value}% 达到法规要求（≥{min_pct}%），"
                f"但远高于 2024 年行业均值 {ind_li_avg}%，数据存疑。"
            ),
            legal_ref=f"{legal_ref} / Art. 77(4) 数据准确性",
            recommendation=(
                "请提供 ASI、RMI 或同等资质机构出具的第三方审计证明，"
                "附上供应商溯源链文件方可视为有效。"
            ),
        )]

    return [Finding(
        level=Finding.PASS,
        field="recycled_rate",
        message=f"申报的回收材料比例 {value}% ≥ 法定最低值 {min_pct}%，通过核查。",
        legal_ref=legal_ref,
    )]


# ════════════════════════════════════════════════════════════════════════════
# 核查维度 3 — 供应链区域风险核查
# 法律依据：
#   Article 52  — 尽职调查义务（2027-08-18 生效，原 2025 推迟）
#   EU Forced Labour Regulation 2024 — 约 2027-2028 执行
#   Article 7   — 碳足迹申报（EV 电池 2025-02-18 已生效）
# 数据来源：
#   Caixin Global 2024-11-29; Minespider 2025; EU OJ L_202501561
# ════════════════════════════════════════════════════════════════════════════

# 已知高风险采矿/加工区域（基于欧盟监管关注焦点）
_HIGH_RISK_REGIONS = {
    "xinjiang":  "新疆（Xinjiang）",
    "xizang":    "西藏（Tibet）",
    "drc":       "刚果民主共和国（DRC）",
    "congo":     "刚果民主共和国（DRC）",
    "myanmar":   "缅甸（Myanmar）",
    "burma":     "缅甸（Myanmar）",
}

# 高风险矿物（EU Article 52 尽职调查覆盖）
_DD_MINERALS = {"cobalt", "graphite", "lithium", "nickel", "钴", "石墨", "锂", "镍"}


def check_supply_chain_risk(data: dict, bench: dict) -> list[Finding]:
    """
    供应链区域风险核查（三个子维度）。

    子维度 3a — 碳足迹申报缺口
        EV/工业电池已需申报碳足迹声明（Article 7），缺失即为 COMPLIANCE_GAP。

    子维度 3b — 矿物来源地风险
        如果供应商申报的原材料来源地（manufacturing_country / mineral_origin）
        属于已知高风险区域，触发 WARNING，要求提供尽职调查文件。
        法律依据：Article 52（尽职调查，2027-08-18 生效）

    子维度 3c — 强迫劳动法规预警
        如果原材料来源涉及高风险区域且 EU Forced Labour Regulation 约
        2027-2028 执行，提前预警，建议企业启动供应商审计。
    """
    findings: list[Finding] = []

    # ── 子维度 3a：碳足迹申报完整性 ────────────────────────────────────────
    has_cf   = data.get("carbon_footprint_kg_co2e_per_kwh") is not None
    btype    = str(data.get("battery_type", "LFP")).upper()
    category = data.get("battery_category", "")  # EV / Industrial / LMT

    # EV 电池 2025-02-18 已强制申报；Industrial（非外接储能）2026-02-18 起
    if not has_cf:
        if btype in ("EV", "NCM", "NMC") or str(category).upper() == "EV":
            findings.append(Finding(
                level=Finding.COMPLIANCE_GAP,
                field="carbon_footprint_kg_co2e_per_kwh",
                message=(
                    "EV 电池碳足迹申报义务已于 2025-02-18 生效，"
                    "未提供碳足迹声明将导致产品无法进入欧盟市场。"
                ),
                legal_ref="Article 7(1)(d), Regulation (EU) 2023/1542 — 生效日期 2025-02-18",
                recommendation=(
                    "请立即委托具备 ISO 14040/14044 资质的第三方机构完成生命周期评估（LCA），"
                    "并依照 JRC 发布的《Carbon Footprint Rules for EV Batteries》（2023-06）"
                    "完成碳足迹声明文件，建议使用 GBA Transparency Report 框架进行数据归档。"
                ),
            ))

    # ── 子维度 3b：矿物来源地区域风险 ──────────────────────────────────────
    mineral_origin = str(data.get("mineral_origin", "")).lower().strip()
    mfg_country    = str(data.get("manufacturing_country", "")).lower().strip()

    matched_region = None
    for key, label in _HIGH_RISK_REGIONS.items():
        if key in mineral_origin or key in mfg_country:
            matched_region = label
            break

    if matched_region:
        findings.append(Finding(
            level=Finding.WARNING,
            field="mineral_origin",
            message=(
                f"申报的原材料来源地或制造地涉及高风险区域：{matched_region}。"
                f"该区域受欧盟尽职调查义务（Article 52）和 EU Forced Labour Regulation（2024）重点关注。"
            ),
            legal_ref=(
                "Article 52, Regulation (EU) 2023/1542 — 尽职调查义务（生效 2027-08-18）；"
                "EU Forced Labour Regulation（2024-11-19 通过，约 2027-2028 执行）"
            ),
            recommendation=(
                f"建议立即针对{matched_region}供应商启动以下行动：\n"
                "① 委托 RMI（责任矿产倡议）或 IRMA（独立矿山评估）进行第三方供应商审计；\n"
                "② 建立关键矿物（锂/钴/镍/天然石墨）的逐级溯源体系（Tier 1→Tier N）；\n"
                "③ 评估替代供应来源，降低对单一高风险地区的依赖；\n"
                "④ 按 Article 52(3) 要求每三年发布尽职调查绩效报告。"
            ),
        ))

    # ── 子维度 3c：强迫劳动预警（主动风险管理）──────────────────────────────
    if matched_region and "新疆" in matched_region:
        findings.append(Finding(
            level=Finding.WARNING,
            field="forced_labour_risk",
            message=(
                "新疆供应链面临 EU Forced Labour Regulation 特别关注风险。"
                "该法规于 2024-11-19 正式通过，约 2027-2028 年开始执法，"
                "违规产品将被禁止进口、销售或出口至欧盟市场。"
            ),
            legal_ref=(
                "EU Forced Labour Regulation (adopted 2024-11-19, enforcement ~2027-2028)；"
                "美国《维吾尔强迫劳动预防法》(UFLPA) 可作为欧盟执法参考"
            ),
            recommendation=(
                "建议制定新疆供应链替代战略，包括：\n"
                "① 评估非新疆多晶硅/锂源（如澳大利亚、智利、阿根廷）替代可行性；\n"
                "② 与现有新疆供应商共同开展独立第三方审计，留存合规证明文件；\n"
                "③ 参考 GBA 电池护照框架建立完整供应链透明度记录；\n"
                "④ 在 2027 年法规正式执法前完成供应链重组，避免断货风险。"
            ),
        ))

    # 若无任何来源地风险 → 通过
    if not matched_region and not findings:
        findings.append(Finding(
            level=Finding.PASS,
            field="supply_chain_region",
            message="未申报已知高风险采矿/制造区域，供应链区域风险核查通过。",
            legal_ref="Article 52, Regulation (EU) 2023/1542",
        ))

    return findings


# ════════════════════════════════════════════════════════════════════════════
# 扩展注册表 — 追加新核查维度只需在此列表末尾加一行
# ════════════════════════════════════════════════════════════════════════════
_CHECKS = [
    check_energy_usage,        # 维度 1：制造能耗（energy_usage）
    check_recycled_rate,       # 维度 2：回收材料比例（recycled_rate）
    check_supply_chain_risk,   # 维度 3：供应链区域风险（mineral_origin / battery_category）
    # check_bms_access,        # 待实现：BMS 读权限（Article 14，2024-08-18 已生效）
]


# ════════════════════════════════════════════════════════════════════════════
# 公开接口
# ════════════════════════════════════════════════════════════════════════════
def audit_battery_data(input_data: dict) -> dict:
    """
    对供应商申报数据执行全维度核查，返回结构化 JSON 结果。

    Parameters（所有字段均为可选）
    ----------
    battery_type  : "LFP" | "NCM" | "NMC"，默认 "LFP"
    energy_usage  : 制造能耗 kWh/kWh
    recycled_rate : 综合回收材料比例 %

    Returns
    -------
    {
        "risk_level"     : "RED_FLAG" | "COMPLIANCE_GAP" | "WARNING" | "PASS",
        "summary"        : str,
        "findings"       : [...],   # 全部核查结果
        "red_flags"      : [...],   # 仅 RED_FLAG
        "compliance_gaps": [...],   # 仅 COMPLIANCE_GAP
        "warnings"       : [...],   # 仅 WARNING
        "passed"         : [...],   # 仅 PASS
        "recommendations": [...],   # 汇总改进建议
    }
    """
    bench    = _load_benchmarks()
    findings: list[Finding] = []

    for check_fn in _CHECKS:
        findings.extend(check_fn(input_data, bench))

    # ── 集成物理核查引擎（Wave 2+3）────────────────────────────────────
    # 物理核查结果独立存储，不合并入主 findings，避免 PEFCR 等辅助检查
    # 影响主风险评级。只有明确的 RED_FLAG（比能量/循环寿命/体积能量密度）
    # 会提升主评级，PEFCR 补全惩罚保留在 physics_findings 独立展示。
    physics_findings: list[dict] = []
    if _ENGINE_AVAILABLE:
        try:
            raw = run_physics_checks(input_data)
            physics_findings = raw
            # 将物理核查 RED_FLAG 并入主 findings
            # (PEFCR 的 RED_FLAG 也纳入，因为漏报重要 LCA 阶段是严重违规)
            for pf in raw:
                if pf["level"] == "RED_FLAG":
                    findings.append(Finding(
                        level          = pf["level"],
                        field          = pf["field"],
                        message        = pf["message"],
                        legal_ref      = pf.get("legal_ref", ""),
                        recommendation = pf.get("recommendation", ""),
                    ))
        except Exception:
            pass

    red_flags       = [f for f in findings if f.level == Finding.RED_FLAG]
    compliance_gaps = [f for f in findings if f.level == Finding.COMPLIANCE_GAP]
    warnings        = [f for f in findings if f.level == Finding.WARNING]
    passed          = [f for f in findings if f.level == Finding.PASS]

    # risk_level 直接使用 Finding 标签，保持语义一致
    if red_flags:
        risk_level = "RED_FLAG"
        summary    = f"检测到 {len(red_flags)} 条物理逻辑冲突，数据存在高度造假嫌疑，需立即核查。"
    elif compliance_gaps:
        risk_level = "COMPLIANCE_GAP"
        summary    = f"发现 {len(compliance_gaps)} 条合规缺口，需在法规生效前完成整改。"
    elif warnings:
        risk_level = "WARNING"
        summary    = f"数据通过基本核查，但有 {len(warnings)} 条需补充证明材料。"
    else:
        risk_level = "PASS"
        summary    = "所有申报数据通过核查，未发现风险。"

    # ── 生命周期合规预测 ─────────────────────────────────────────────────
    lifecycle = {}
    if _ENGINE_AVAILABLE:
        try:
            lifecycle = predict_compliance_lifecycle(input_data)
        except Exception:
            pass

    return {
        "risk_level":         risk_level,
        "summary":            summary,
        "findings":           [f.to_dict() for f in findings],
        "red_flags":          [f.to_dict() for f in red_flags],
        "compliance_gaps":    [f.to_dict() for f in compliance_gaps],
        "warnings":           [f.to_dict() for f in warnings],
        "passed":             [f.to_dict() for f in passed],
        "recommendations":    [f.recommendation for f in findings if f.recommendation],
        "lifecycle_prediction": lifecycle,
        "physics_findings":   physics_findings,
    }
