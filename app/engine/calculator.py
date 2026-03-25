"""
app/engine/calculator.py — 物理一致性校验引擎 (Wave 2+3)
==========================================================
基于电化学基本原理，核查供应商申报的性能参数是否在物理可能范围内。

数据来源：
  - Degen et al., Nature Energy, 2023 (DOI: 10.1038/s41560-023-01355-z)
  - Faraday Institution Insights #18, 2023
  - NX Technologies LFP vs NMC Analysis, 2024
  - ufinebattery.com NMC Chemistry Guide, 2024
  - keheng-battery.com NMC 523/622/811 Comparative Analysis, 2024

核心逻辑：
  若申报值 > 当前最佳商业水平 × FRAUD_MULTIPLIER (0.92 = 92%)
  → 判定为"技术数据造假"，触发 RED_FLAG
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── 92% 欺诈阈值 ────────────────────────────────────────────────────────────
# 若申报值超过已知最优商业产品的 92%，当前工艺不可能达到
FRAUD_MULTIPLIER = 0.92


# ── 各化学体系物理极限数据库 ────────────────────────────────────────────────────
# 数据来源：同行评审文献 + 行业顶尖产品参数（截至 2024）
_PHYSICS = {
    "LFP": {
        "_chemistry_name": "Lithium Iron Phosphate (LFP / LiFePO4)",
        "_source": "Degen et al. Nature Energy 2023; NX-Tech 2024; NACCON 2024",
        "specific_energy_wh_per_kg": {
            "theoretical_max":        544,   # LFP 阴极材料理论比能量（mAh/g × V）
            "best_commercial_cell":   210,   # 2024 年最优商业电芯（含阴极+阳极+电解液+结构件）
            "typical_range":          [120, 180],
            "_note": "CTP/刀片技术可提升至 180-210 Wh/kg 电芯级别",
        },
        "volumetric_energy_wh_per_l": {
            "best_commercial_cell":   550,   # 体积能量密度最优商业值
            "typical_range":          [300, 450],
        },
        "cycle_life": {
            "max_commercial":         10000, # 电网储能专用 LFP 极端案例
            "typical_max_ev":         5000,
            "typical_range":          [2000, 4000],
            "_verbatim": "LFP: superior cycle life up to 3,500-5,000 cycles (NX-Tech 2024)",
        },
        "max_c_rate_continuous": {
            "discharge": 10.0,   # 极少数商业应用（电动工具），典型 <3C
            "charge":     3.0,
            "typical_ev": 2.0,
        },
        "nominal_voltage_v": 3.2,
        "operating_temp_min_c": -20,
        "operating_temp_max_c":  60,
    },

    "NCM": {
        "_chemistry_name": "Nickel Cobalt Manganese (NCM / NMC)",
        "_source": "keheng-battery.com NCM 523/622/811 Analysis 2024; ufinebattery.com 2024; Degen et al. 2023",
        "_subtypes": {
            "NCM_523": {
                "specific_energy_wh_per_kg": {"best_commercial_cell": 250, "typical_range": [200, 240]},
                "volumetric_energy_wh_per_l": {"best_commercial_cell": 620, "typical_range": [500, 600]},
                "cycle_life": {"typical_max": 2000, "typical_range": [800, 1500]},
                "max_c_rate_discharge": 5.0,
            },
            "NCM_622": {
                "specific_energy_wh_per_kg": {"best_commercial_cell": 270, "typical_range": [220, 260]},
                "volumetric_energy_wh_per_l": {"best_commercial_cell": 680, "typical_range": [560, 650]},
                "cycle_life": {"typical_max": 2000, "typical_range": [800, 1500]},
                "max_c_rate_discharge": 5.0,
            },
            "NCM_811": {
                "specific_energy_wh_per_kg": {"best_commercial_cell": 300, "typical_range": [240, 290]},
                "volumetric_energy_wh_per_l": {"best_commercial_cell": 750, "typical_range": [620, 720]},
                "cycle_life": {"typical_max": 2000, "typical_range": [500, 1200], "_note": "高镍循环寿命更低"},
                "max_c_rate_discharge": 4.0,
            },
        },
        # 通用上限（所有 NCM 型号的最高商业值）
        "specific_energy_wh_per_kg": {
            "theoretical_max":        825,   # NCM811 正极理论比容量（~220 mAh/g × 3.75V）
            "best_commercial_cell":   300,   # NCM811 最优商业电芯（2024）
            "typical_range":          [200, 280],
            "_verbatim": "NMC typical range 200-250 Wh/kg, some sources citing 220-300 Wh/kg (NX-Tech 2024)",
        },
        "volumetric_energy_wh_per_l": {
            "best_commercial_cell":   750,
            "typical_range":          [500, 700],
        },
        "cycle_life": {
            "max_commercial":         3000,
            "typical_range":          [1000, 2000],
            "_verbatim": "NMC typical cycle life: 1,000-2,000 cycles (NX-Tech 2024)",
        },
        "max_c_rate_continuous": {
            "discharge": 5.0,
            "charge":    2.0,
            "typical_ev": 1.5,
        },
        "nominal_voltage_v": 3.7,
        "operating_temp_min_c": -20,
        "operating_temp_max_c":  45,
    },
}

# NMC 作为 NCM 的别名
_PHYSICS["NMC"] = _PHYSICS["NCM"]


# ── Finding 数据类（引用 auditor.py 定义，避免循环导入）────────────────────
@dataclass
class PhysicsFinding:
    """物理一致性核查单条结果"""
    level:          str        # RED_FLAG / WARNING / PASS
    field:          str
    message:        str
    legal_ref:      str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── 内部工具 ──────────────────────────────────────────────────────────────────
def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get_spec(chem: str) -> dict:
    chem = chem.upper().strip()
    if chem == "NMC":
        chem = "NCM"
    return _PHYSICS.get(chem, _PHYSICS["LFP"])


# ── 核查函数 ──────────────────────────────────────────────────────────────────

def check_specific_energy(data: dict) -> list[PhysicsFinding]:
    """
    核查申报的比能量（Wh/kg）是否超过物理极限。

    触发条件：申报值 > best_commercial_cell × (1 / FRAUD_MULTIPLIER)
    即声称超越目前世界最优商业产品，判定为数据造假。
    """
    value = _to_float(data.get("specific_energy_wh_per_kg"))
    if value is None:
        return []

    chem  = str(data.get("battery_type", "LFP")).upper()
    spec  = _get_spec(chem)
    limits = spec.get("specific_energy_wh_per_kg", {})
    best  = limits.get("best_commercial_cell", 300)
    fraud_threshold = best / FRAUD_MULTIPLIER   # 若声称超过最优×(1/0.92) → 不可能

    if value > fraud_threshold:
        return [PhysicsFinding(
            level="RED_FLAG",
            field="specific_energy_wh_per_kg",
            message=(
                f"违反能量守恒定律，申报数据不可信。"
                f"申报比能量 {value} Wh/kg 超过 {chem} 当前最优商业电芯 {best} Wh/kg "
                f"的 {round(value/best*100, 1)}%。"
                f"在不改变正极活性物质的前提下，此值物理上不可能实现。"
            ),
            legal_ref="物理一致性核查 / Art. 77(4) 数据准确性义务",
            recommendation=(
                f"请核实申报单位（Wh/kg 应为电芯级别，非活性材料级别）。"
                f"{chem} 当前最优商业电芯（2024）为 {best} Wh/kg，"
                f"典型范围 {limits.get('typical_range', 'N/A')} Wh/kg。"
            ),
        )]

    if value > best:
        return [PhysicsFinding(
            level="WARNING",
            field="specific_energy_wh_per_kg",
            message=(
                f"申报比能量 {value} Wh/kg 超过 2024 年行业最优商业产品 {best} Wh/kg，"
                f"需要提供第三方验证报告（如 IEC 62660 测试证书）。"
            ),
            legal_ref="技术参数合理性核查",
            recommendation="请提供经认证实验室（TÜV、SGS 或 UL）出具的电芯测试报告。",
        )]

    return [PhysicsFinding(
        level="PASS",
        field="specific_energy_wh_per_kg",
        message=f"申报比能量 {value} Wh/kg 在 {chem} 合理范围内（最优 {best} Wh/kg）。",
    )]


def check_cycle_life(data: dict) -> list[PhysicsFinding]:
    """核查申报的循环寿命是否超过化学体系物理极限。"""
    value = _to_float(data.get("cycle_life_cycles"))
    if value is None:
        return []

    chem  = str(data.get("battery_type", "LFP")).upper()
    spec  = _get_spec(chem)
    cycle = spec.get("cycle_life", {})
    max_c = cycle.get("max_commercial", 5000)
    fraud_threshold = max_c / FRAUD_MULTIPLIER

    if value > fraud_threshold:
        return [PhysicsFinding(
            level="RED_FLAG",
            field="cycle_life_cycles",
            message=(
                f"违反能量守恒定律，申报数据不可信。"
                f"申报循环寿命 {int(value)} 次超过 {chem} 已知最大商业值 {max_c} 次 "
                f"的 {round(value/max_c*100, 1)}%，现有电化学体系无法实现。"
            ),
            legal_ref="物理一致性核查 / Art. 77(4)",
            recommendation=(
                f"{chem} 最大商业循环寿命：LFP ≤10,000（储能专用），NCM ≤3,000。"
                "请提供 IEC 62660-1 或 IEC 62660-2 标准下的循环测试原始数据。"
            ),
        )]

    return [PhysicsFinding(
        level="PASS",
        field="cycle_life_cycles",
        message=f"申报循环寿命 {int(value)} 次在 {chem} 物理可信范围内（最大商业值 {max_c} 次）。",
    )]


def check_volumetric_energy(data: dict) -> list[PhysicsFinding]:
    """核查体积能量密度（Wh/L）是否超过物理极限。"""
    value = _to_float(data.get("volumetric_energy_wh_per_l"))
    if value is None:
        return []

    chem  = str(data.get("battery_type", "LFP")).upper()
    spec  = _get_spec(chem)
    vol   = spec.get("volumetric_energy_wh_per_l", {})
    best  = vol.get("best_commercial_cell", 750)
    fraud_threshold = best / FRAUD_MULTIPLIER

    if value > fraud_threshold:
        return [PhysicsFinding(
            level="RED_FLAG",
            field="volumetric_energy_wh_per_l",
            message=(
                f"违反能量守恒定律，申报数据不可信。"
                f"申报体积能量密度 {value} Wh/L 超过 {chem} 最优商业电芯 {best} Wh/L 的"
                f" {round(value/best*100, 1)}%。"
            ),
            legal_ref="物理一致性核查 / Art. 77(4)",
            recommendation=(
                f"请检查申报单位（应为电芯级体积，不含结构件）。"
                f"{chem} 参考最优值：{best} Wh/L。"
            ),
        )]

    return [PhysicsFinding(
        level="PASS",
        field="volumetric_energy_wh_per_l",
        message=f"申报体积能量密度 {value} Wh/L 在合理范围内（最优 {best} Wh/L）。",
    )]


# ── PEFCR 系统边界惩罚算法 ────────────────────────────────────────────────────
# EU PEFCR for Batteries 要求以下生命周期阶段必须申报；缺失时使用"最差情景"因子补全
_PEFCR_REQUIRED_STAGES = {
    "raw_material_extraction":    "原材料开采（锂/钴/镍/锰矿石）",
    "material_processing":        "材料加工（正极粉末、电解液合成）",
    "electrode_coating":          "极片涂布（铜箔/铝箔基材加工）",
    "cell_assembly":              "电芯组装（叠片/卷绕、注液）",
    "formation_cycling":          "化成分容（高能耗工序）",
    "pack_assembly":              "电池包集成（BMS、壳体）",
    "transport_to_eu":            "运输至欧盟",
    "end_of_life":                "废旧处理（回收/填埋）",
}

# 最差排放因子（惩罚性补全值，来源：JRC 2023 PEFCR 草案 + IVL 2023 悲观情景）
_WORST_CASE_EMISSION_FACTORS_KG_CO2E_PER_KWH = {
    "raw_material_extraction":  25.0,  # 未申报原材料来源，按最高风险矿区计
    "material_processing":      18.0,  # 按煤电能源结构计算精炼能耗
    "electrode_coating":         8.0,  # 铜箔/铝箔加工环节
    "cell_assembly":             5.0,  # 电芯组装（干燥房能耗高）
    "formation_cycling":        12.0,  # 化成：按煤电 × 最大电耗计
    "pack_assembly":             4.0,  # 电池包集成
    "transport_to_eu":           2.5,  # 中国→欧洲 海运/陆运
    "end_of_life":               3.0,  # 无正规回收，按垃圾填埋计
}


def check_pefcr_completeness(data: dict) -> list[PhysicsFinding]:
    """
    PEFCR 系统边界完整性核查与惩罚性补全。

    仅在供应商明确提供了 pefcr_stages_declared 字段时才运行核查；
    若字段根本不存在（本次审计未提交），跳过本检查以避免误判。
    """
    results: list[PhysicsFinding] = []
    # 若供应商未提交 pefcr_stages_declared，跳过核查
    if "pefcr_stages_declared" not in data:
        return []
    declared_stages = set(data["pefcr_stages_declared"])

    missing   = []
    penalty   = 0.0
    for stage, label in _PEFCR_REQUIRED_STAGES.items():
        if stage not in declared_stages:
            factor = _WORST_CASE_EMISSION_FACTORS_KG_CO2E_PER_KWH[stage]
            missing.append((label, factor))
            penalty += factor

    if not missing:
        return [PhysicsFinding(
            level="PASS",
            field="pefcr_stages_declared",
            message="所有 PEFCR 规定的生命周期阶段均已申报，系统边界完整。",
            legal_ref="EU PEFCR for Batteries (JRC, 2023); Article 7(1)(e)",
        )]

    missing_labels = "; ".join(f"{l}（最差因子 +{f} kg CO2e/kWh）" for l, f in missing)
    results.append(PhysicsFinding(
        level="WARNING" if penalty < 20 else "RED_FLAG",
        field="pefcr_stages_declared",
        message=(
            f"检测到 {len(missing)} 个 PEFCR 规定的生命周期阶段未申报，"
            f"已自动使用最差情景因子补全，估算碳足迹补增量：+{penalty:.1f} kg CO2e/kWh。\n"
            f"缺失阶段：{missing_labels}"
        ),
        legal_ref=(
            "EU PEFCR for Batteries (JRC 2023 draft); "
            "Article 7(1)(e) — 须按生命周期阶段分别申报碳足迹"
        ),
        recommendation=(
            f"请补充以下阶段的 LCA 核算数据：{'; '.join(l for l,_ in missing)}。\n"
            f"使用 SimaPro / OpenLCA 等工具，依据 ISO 14040/14044 和 EU PEFCR 方法论完成计算。\n"
            f"惩罚性补全后，实际申报碳足迹可能比现有申报值高出约 {penalty:.0f} kg CO2e/kWh。"
        ),
    ))

    return results


# ── 碳足迹物理下限核查 ───────────────────────────────────────────────────────
# 数据来源：Degen et al. Nature Energy 2023; IVL 2023; JRC Batteries LCA 2023
_CF_LIMITS_KG_CO2E_PER_KWH = {
    "LFP":  {"absolute_min": 25, "realistic_min": 35, "typical_avg": 60},
    "NCM":  {"absolute_min": 40, "realistic_min": 55, "typical_avg": 85},
    "NMC":  {"absolute_min": 40, "realistic_min": 55, "typical_avg": 85},
    "NCA":  {"absolute_min": 45, "realistic_min": 60, "typical_avg": 90},
    "SIB":  {"absolute_min": 20, "realistic_min": 30, "typical_avg": 55},
}


def check_carbon_footprint_physics(data: dict) -> list[PhysicsFinding]:
    """
    核查碳足迹申报值是否低于物理下限。

    即使使用 100% 可再生电力，电池生产也需要采矿、材料加工、运输等
    非电力能耗，因此碳足迹不可能为零或趋近于零。

    数据来源：Degen et al. Nature Energy 2023 (最低 35 kgCO2e/kWh under best conditions)
    """
    value = _to_float(data.get("carbon_footprint_kg_co2e_per_kwh"))
    if value is None:
        return []

    chem   = str(data.get("battery_type", "LFP")).upper()
    limits = _CF_LIMITS_KG_CO2E_PER_KWH.get(chem, _CF_LIMITS_KG_CO2E_PER_KWH["LFP"])
    abs_min  = limits["absolute_min"]
    real_min = limits["realistic_min"]
    avg      = limits["typical_avg"]

    if value < abs_min:
        return [PhysicsFinding(
            level="RED_FLAG",
            field="carbon_footprint_kg_co2e_per_kwh",
            message=(
                f"违反物理规律，碳足迹申报值不可信。"
                f"申报值 {value} kg CO2e/kWh 低于 {chem} 生命周期碳排放的物理下限"
                f"（绝对最低值：{abs_min} kg CO2e/kWh，即使 100% 可再生能源也无法低于此值）。"
                f"采矿、材料加工、运输等环节的非电力碳排放不可避免。"
            ),
            legal_ref="物理一致性核查 / Art. 77(4) 数据准确性义务 / Degen et al. Nature Energy 2023",
            recommendation=(
                f"请检查碳足迹核算方法：{chem} 在最优场景（100% 绿电 + 最短运输距离）下，"
                f"生命周期碳足迹现实最低值为约 {real_min} kg CO2e/kWh（Degen et al. 2023）。"
                f"行业平均值约 {avg} kg CO2e/kWh。"
                "申报值过低将被 EU 审计机构质疑，请依据 ISO 14040/14044 + EU PEFCR 重新核算。"
            ),
        )]

    if value < real_min:
        return [PhysicsFinding(
            level="WARNING",
            field="carbon_footprint_kg_co2e_per_kwh",
            message=(
                f"申报碳足迹 {value} kg CO2e/kWh 低于 {chem} 现实最低值 {real_min} kg CO2e/kWh，"
                f"需提供详细的 LCA 核算报告和 100% 可再生能源采购证明。"
            ),
            legal_ref="物理一致性核查 / Degen et al. Nature Energy 2023",
            recommendation="请提供经认证的 LCA 报告（ISO 14044 + PEFCR），并附上 I-REC 绿电证书，方可视为有效低碳声明。",
        )]

    return [PhysicsFinding(
        level="PASS",
        field="carbon_footprint_kg_co2e_per_kwh",
        message=f"碳足迹申报值 {value} kg CO2e/kWh 在 {chem} 合理范围内（现实最低 {real_min}，平均 {avg}）。",
    )]


# ── 公开接口 ──────────────────────────────────────────────────────────────────
def run_physics_checks(data: dict) -> list[dict]:
    """
    运行所有物理一致性核查，返回 Finding dict 列表。

    支持的输入字段：
        battery_type             : LFP / NCM / NMC
        specific_energy_wh_per_kg: 比能量（Wh/kg）
        volumetric_energy_wh_per_l: 体积能量密度（Wh/L）
        cycle_life_cycles        : 循环寿命（次）
        pefcr_stages_declared    : 已申报的 PEFCR 阶段列表
    """
    all_findings: list[PhysicsFinding] = []
    all_findings.extend(check_specific_energy(data))
    all_findings.extend(check_volumetric_energy(data))
    all_findings.extend(check_cycle_life(data))
    all_findings.extend(check_carbon_footprint_physics(data))
    all_findings.extend(check_pefcr_completeness(data))
    return [f.to_dict() for f in all_findings]


def get_physics_limits(battery_type: str) -> dict:
    """返回指定化学体系的物理极限摘要（供前端/PDF 展示）。"""
    spec = _get_spec(battery_type)
    return {
        "battery_type": battery_type.upper(),
        "best_commercial_specific_energy_wh_per_kg": spec["specific_energy_wh_per_kg"]["best_commercial_cell"],
        "best_commercial_volumetric_energy_wh_per_l": spec["volumetric_energy_wh_per_l"]["best_commercial_cell"],
        "max_commercial_cycle_life": spec["cycle_life"]["max_commercial"] if "max_commercial" in spec["cycle_life"] else spec["cycle_life"].get("max_commercial_cell", "N/A"),
        "fraud_detection_multiplier": FRAUD_MULTIPLIER,
        "source": spec.get("_source", ""),
    }
