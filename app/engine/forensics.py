"""
app/engine/forensics.py — 数据法医模块 (Wave 4)
=================================================
对供应商连续月度数据进行统计分析，检测人为篡改痕迹。

核心检测逻辑：
  1. 自然波动率校验：真实生产数据的变异系数（CV）应 > 2%
     若 CV ≤ 1%，判定为"人工修改痕迹"
  2. 平滑度异常检测：真实数据不会完美线性增减
  3. 整数偏好检测：真实计量数据不会全部精确到整数
  4. 合规生命周期预测：根据当前数据预测哪年被欧盟清票

参考：
  - 数字取证领域的 Benford's Law（第一位数字分布）
  - 《数据质量在 ESG 报告中的应用》，GBA 透明度报告 2024
  - EU 2023/1542 合规时间轴（Article 7、8、77）
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any


# ── 统计阈值 ─────────────────────────────────────────────────────────────────
CV_FRAUD_THRESHOLD    = 0.01   # 变异系数 ≤ 1% → 人为修改
CV_WARNING_THRESHOLD  = 0.02   # 变异系数 ≤ 2% → 需要解释
INT_RATIO_THRESHOLD   = 0.80   # 整数比例 ≥ 80% → 精度可疑
LINEAR_R2_THRESHOLD   = 0.99   # R² ≥ 0.99 → 数据过于"完美"


@dataclass
class ForensicFinding:
    """单条法医核查结果"""
    level:          str   # RED_FLAG / WARNING / PASS
    check_name:     str
    message:        str
    evidence:       dict  # 统计证据
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "level":          self.level,
            "field":          self.check_name,
            "message":        self.message,
            "evidence":       self.evidence,
            "recommendation": self.recommendation,
        }


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_squared(series: list[float]) -> float:
    """计算数据序列与最优线性拟合的 R²（越接近 1 越"完美"）。"""
    n = len(series)
    if n < 3:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = statistics.mean(series)
    ss_res, ss_tot = 0.0, 0.0
    slope = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(series)) / \
            sum((i - x_mean) ** 2 for i in range(n))
    intercept = y_mean - slope * x_mean
    for i, y in enumerate(series):
        y_pred = slope * i + intercept
        ss_res += (y - y_pred) ** 2
        ss_tot += (y - y_mean) ** 2
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


# ── 核查 1：自然波动率校验 ─────────────────────────────────────────────────────
def check_natural_variation(monthly_data: list[float], field_name: str) -> ForensicFinding:
    """
    真实生产数据必须有自然波动（季节性、设备维护、生产调度）。
    若变异系数（标准差/均值）≤ 1%，认定为人工修改数据。
    """
    if len(monthly_data) < 3:
        return ForensicFinding(
            level="WARNING",
            check_name=f"{field_name}_variation",
            message=f"数据点不足（{len(monthly_data)} 个月），无法进行完整波动率分析，建议提供至少 12 个月数据。",
            evidence={"n_months": len(monthly_data)},
        )

    mean = statistics.mean(monthly_data)
    if mean == 0:
        return ForensicFinding(
            level="WARNING",
            check_name=f"{field_name}_variation",
            message="数据均值为 0，无法计算变异系数。",
            evidence={"mean": 0},
        )

    std  = statistics.stdev(monthly_data)
    cv   = std / abs(mean)
    r2   = _r_squared(monthly_data)

    evidence = {
        "n_months": len(monthly_data),
        "mean": round(mean, 4),
        "std_dev": round(std, 4),
        "cv_pct": round(cv * 100, 3),
        "linear_r2": round(r2, 4),
        "min": round(min(monthly_data), 4),
        "max": round(max(monthly_data), 4),
    }

    # 最严重：CV 趋近于零
    if cv <= CV_FRAUD_THRESHOLD:
        return ForensicFinding(
            level="RED_FLAG",
            check_name=f"{field_name}_variation",
            message=(
                f"检测到人工修改痕迹，数据非真实采集，涉嫌系统性瞒报。"
                f"连续 {len(monthly_data)} 个月的 {field_name} 变异系数仅 {cv*100:.3f}%（阈值：>1%）。"
                f"真实生产数据不可能如此均匀，高度疑似手工填入固定值或经过统计平滑处理。"
            ),
            evidence=evidence,
            recommendation=(
                "请提供原始生产台账（DCS/MES 系统导出数据），并由第三方审计机构核实。"
                "自然生产数据的变异系数通常在 3%–15% 之间（季节、维护、订单波动）。"
                "EU Art. 77(4) 要求数据准确完整，系统性填报虚假数据将触发处罚条款。"
            ),
        )

    # 中级警告：CV 偏低 + 线性度过高
    if cv <= CV_WARNING_THRESHOLD or r2 >= LINEAR_R2_THRESHOLD:
        reasons = []
        if cv <= CV_WARNING_THRESHOLD:
            reasons.append(f"变异系数 {cv*100:.2f}% 低于正常水平（典型值 3%–15%）")
        if r2 >= LINEAR_R2_THRESHOLD:
            reasons.append(f"数据呈几乎完美线性趋势（R²={r2:.4f}），疑似人工插值")

        return ForensicFinding(
            level="WARNING",
            check_name=f"{field_name}_variation",
            message=f"数据统计特征异常：{'; '.join(reasons)}。",
            evidence=evidence,
            recommendation="建议提供 DCS 系统原始采集日志，证明数据来自实时计量而非手工录入。",
        )

    return ForensicFinding(
        level="PASS",
        check_name=f"{field_name}_variation",
        message=(
            f"{field_name} 连续 {len(monthly_data)} 个月数据统计特征正常"
            f"（CV={cv*100:.2f}%，R²={r2:.3f}）。"
        ),
        evidence=evidence,
    )


# ── 核查 2：整数精度异常检测 ──────────────────────────────────────────────────
def check_integer_bias(monthly_data: list[float], field_name: str) -> ForensicFinding:
    """
    真实能耗计量不会全部落在整数上。
    若 ≥80% 的月度值是整数，认为精度异常。
    """
    if len(monthly_data) < 3:
        return ForensicFinding(
            level="PASS",
            check_name=f"{field_name}_precision",
            message="数据点不足，跳过精度检测。",
            evidence={},
        )

    int_count = sum(1 for v in monthly_data if v == int(v))
    int_ratio = int_count / len(monthly_data)

    if int_ratio >= INT_RATIO_THRESHOLD:
        return ForensicFinding(
            level="WARNING",
            check_name=f"{field_name}_precision",
            message=(
                f"{field_name} 中 {int_count}/{len(monthly_data)} 个月度值为整数"
                f"（比例 {int_ratio*100:.0f}%），精度异常，疑似手动填报。"
            ),
            evidence={"integer_ratio_pct": round(int_ratio * 100, 1), "n_integers": int_count},
            recommendation="真实能源计量系统（智能电表/DCS）输出的数据通常有 2-4 位小数，请提供原始导出记录。",
        )

    return ForensicFinding(
        level="PASS",
        check_name=f"{field_name}_precision",
        message=f"{field_name} 精度分布正常（整数比例 {int_ratio*100:.0f}%）。",
        evidence={"integer_ratio_pct": round(int_ratio * 100, 1)},
    )


# ── 核查 3：合规生命周期预测 ──────────────────────────────────────────────────
# EU 2023/1542 合规时间轴（关键节点）
_COMPLIANCE_TIMELINE = [
    {
        "year": 2025,
        "month": 2,
        "event": "碳足迹申报义务生效（EV 电池）",
        "legal_ref": "Article 7(1), effective 2025-02-18",
        "requirement": "EV 电池必须提交碳足迹声明（kg CO2e/kWh）",
        "risk_if_missing": "HIGH",
    },
    {
        "year": 2026,
        "month": 2,
        "event": "碳足迹申报义务生效（工业电池 >2kWh，非外接储能）",
        "legal_ref": "Article 7(1), effective 2026-02-18",
        "requirement": "工业电池须提交碳足迹声明",
        "risk_if_missing": "HIGH",
    },
    {
        "year": 2027,
        "month": 2,
        "event": "电池数字护照（DPP）强制生效",
        "legal_ref": "Article 77(1), effective 2027-02-18",
        "requirement": "EV、LMT、工业电池（>2kWh）必须具备 DPP",
        "risk_if_missing": "CRITICAL",
    },
    {
        "year": 2027,
        "month": 8,
        "event": "供应链尽职调查义务生效",
        "legal_ref": "Article 52, effective 2027-08-18（由 2025-08 推迟）",
        "requirement": "钴/锂/镍/天然石墨供应链须完成 OECD 标准尽职调查",
        "risk_if_missing": "HIGH",
    },
    {
        "year": 2028,
        "month": 8,
        "event": "回收含量申报文件义务生效",
        "legal_ref": "Article 8(1), effective 2028-08-18",
        "requirement": "须随附回收钴/锂/镍比例的申报文件",
        "risk_if_missing": "MEDIUM",
    },
    {
        "year": 2031,
        "month": 8,
        "event": "回收含量强制最低比例生效",
        "legal_ref": "Article 8(2), effective 2031-08-18",
        "requirement": "Co≥16%, Pb≥85%, Li≥6%, Ni≥6%（必须达到，否则无法上市）",
        "risk_if_missing": "CRITICAL",
    },
    {
        "year": 2036,
        "month": 8,
        "event": "更严格回收含量要求生效",
        "legal_ref": "Article 8(3), effective 2036-08-18",
        "requirement": "Co≥26%, Li≥12%, Ni≥15%",
        "risk_if_missing": "CRITICAL",
    },
]


def predict_compliance_lifecycle(data: dict, reference_year: int = 2026) -> dict:
    """
    生存预测：根据当前申报数据，预测产品在哪一年会被欧盟市场正式清票。

    Returns
    -------
    {
        "survival_year": int | None,      # 预计被清票年份（None = 当前就已违规）
        "timeline": [...],                # 完整时间轴
        "critical_gaps": [...],           # 高危缺口
        "verdict": str,                   # 总结
    }
    """
    has_carbon_declaration = data.get("carbon_footprint_kg_co2e_per_kwh") is not None
    has_dpp_fields = data.get("battery_type") is not None
    recycled_rate  = data.get("recycled_rate")
    mineral_origin = str(data.get("mineral_origin", "")).lower()
    has_dd_audit   = "oecd" in mineral_origin or "rmi" in mineral_origin or data.get("has_due_diligence_audit", False)

    # 各年份合规状态评估
    timeline_with_status = []
    critical_gaps = []
    survival_year = None

    for milestone in _COMPLIANCE_TIMELINE:
        year = milestone["year"]
        passes = True
        gap_reason = None

        if "碳足迹" in milestone["event"] and not has_carbon_declaration:
            passes = False
            gap_reason = "未提供碳足迹声明"

        if "数字护照" in milestone["event"] and not has_dpp_fields:
            passes = False
            gap_reason = "DPP 必填字段缺失"

        if "尽职调查" in milestone["event"] and not has_dd_audit:
            if any(risk in mineral_origin for risk in ["drc", "congo", "xinjiang"]):
                passes = False
                gap_reason = "高风险区域供应商无 OECD/RMI 尽职调查证明"

        if "强制最低比例" in milestone["event"]:
            if recycled_rate is not None and float(recycled_rate) < 6.0:
                passes = False
                gap_reason = f"回收率 {recycled_rate}% < 法定 6%"

        status = "PASS" if passes else "FAIL"
        if not passes and survival_year is None and year >= reference_year:
            survival_year = year
            critical_gaps.append({
                "year": year,
                "event": milestone["event"],
                "reason": gap_reason,
                "legal_ref": milestone["legal_ref"],
            })

        timeline_with_status.append({
            **milestone,
            "status": status,
            "gap_reason": gap_reason,
        })

    if not critical_gaps:
        verdict = "基于当前申报数据，产品在已知合规时间轴上未发现高危缺口。建议持续监控法规更新。"
    elif survival_year is not None:
        verdict = (
            f"预测：若不改进，该产品将于 {survival_year} 年无法满足欧盟市场要求，"
            f"触发清票风险。关键缺口：{'; '.join(g['reason'] for g in critical_gaps)}。"
        )
    else:
        verdict = "当前数据存在合规缺口，建议立即启动整改。"

    return {
        "survival_year":   survival_year,
        "years_remaining": (survival_year - reference_year) if survival_year else None,
        "timeline":        timeline_with_status,
        "critical_gaps":   critical_gaps,
        "verdict":         verdict,
    }


# ── 公开接口 ──────────────────────────────────────────────────────────────────
def run_forensics(monthly_energy_data: list[float] | None = None,
                  monthly_recycled_data: list[float] | None = None,
                  input_data: dict | None = None) -> dict:
    """
    运行所有法医核查，返回结构化结果。

    Parameters
    ----------
    monthly_energy_data  : 连续月度制造能耗数据列表（kWh/kWh）
    monthly_recycled_data: 连续月度回收率数据列表（%）
    input_data           : 原始申报数据字典（用于生命周期预测）

    Returns
    -------
    {
        "forensic_findings": [...],
        "lifecycle_prediction": {...},
        "overall_forensic_risk": "HIGH" | "MEDIUM" | "LOW",
    }
    """
    findings: list[ForensicFinding] = []
    data = input_data or {}

    if monthly_energy_data:
        findings.append(check_natural_variation(monthly_energy_data, "energy_usage"))
        findings.append(check_integer_bias(monthly_energy_data, "energy_usage"))

    if monthly_recycled_data:
        findings.append(check_natural_variation(monthly_recycled_data, "recycled_rate"))
        findings.append(check_integer_bias(monthly_recycled_data, "recycled_rate"))

    red_flags = [f for f in findings if f.level == "RED_FLAG"]
    warnings  = [f for f in findings if f.level == "WARNING"]

    overall_risk = "HIGH" if red_flags else ("MEDIUM" if warnings else "LOW")

    lifecycle = predict_compliance_lifecycle(data)

    return {
        "forensic_findings":   [f.to_dict() for f in findings],
        "lifecycle_prediction": lifecycle,
        "overall_forensic_risk": overall_risk,
    }
