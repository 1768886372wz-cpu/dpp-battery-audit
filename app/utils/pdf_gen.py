"""
app/utils/pdf_gen.py — PDF 报告生成器
======================================
使用 WeasyPrint 将 Jinja2 HTML 模板渲染为 PDF。

中文不乱码的关键：
  1. HTML 中声明 @font-face，src 使用绝对 file:// URI
  2. 字体必须已复制到 fonts/ 目录（NotoSansSC-Regular.otf）
  3. WeasyPrint 在解析 CSS 时会将字体二进制嵌入 PDF，无需系统字体

使用方法：
    from app.utils.pdf_gen import build_pdf
    pdf_bytes = build_pdf(audit_result, request_data)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

# ── 路径常量 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT  = Path(__file__).resolve().parent.parent.parent
_FONT_PATH     = _PROJECT_ROOT / "fonts" / "NotoSansSC-Regular.otf"
_TEMPLATE_DIR  = _PROJECT_ROOT / "app" / "templates"


# ── 风格主题：根据 risk_level 选取颜色方案 ────────────────────────────────────
_THEMES: dict[str, dict] = {
    "RED_FLAG": {
        "accent_dark":    "#8B0000",   # 深红
        "accent_color":   "#E74C3C",   # 亮红
        "banner_bg":      "#E74C3C",
        "banner_fg":      "#FFFFFF",
        "summary_bg":     "#FFF0F0",
        "summary_fg":     "#8B0000",
        "risk_icon":      "🚨",
        "risk_level_display": "RED FLAG — 高风险 / HIGH RISK",
    },
    "COMPLIANCE_GAP": {
        "accent_dark":    "#7D4A00",
        "accent_color":   "#E67E22",
        "banner_bg":      "#E67E22",
        "banner_fg":      "#FFFFFF",
        "summary_bg":     "#FFF8F0",
        "summary_fg":     "#7D4A00",
        "risk_icon":      "⚠️",
        "risk_level_display": "COMPLIANCE GAP — 合规缺口 / MEDIUM RISK",
    },
    "WARNING": {
        "accent_dark":    "#5A4A00",
        "accent_color":   "#F1C40F",
        "banner_bg":      "#F1C40F",
        "banner_fg":      "#5A4A00",
        "summary_bg":     "#FFFDF0",
        "summary_fg":     "#5A4A00",
        "risk_icon":      "⚡",
        "risk_level_display": "WARNING — 需补充证明 / LOW RISK",
    },
    "PASS": {
        "accent_dark":    "#1A5C38",
        "accent_color":   "#27AE60",
        "banner_bg":      "#27AE60",
        "banner_fg":      "#FFFFFF",
        "summary_bg":     "#F0FFF6",
        "summary_fg":     "#1A5C38",
        "risk_icon":      "✅",
        "risk_level_display": "PASS — 通过核查 / COMPLIANT",
    },
}
_DEFAULT_THEME = _THEMES["WARNING"]


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe(v, fallback: str = "—") -> str:
    """将 None 转为占位符，其余转为字符串。"""
    return fallback if v is None else str(v)


def _color_for_level(level: str) -> str:
    """根据 Finding 等级返回显示颜色。"""
    return {
        "RED_FLAG":      "#C0392B",
        "COMPLIANCE_GAP":"#D35400",
        "WARNING":       "#8A7000",
        "PASS":          "#1A7A40",
    }.get(level, "#1A1A2E")


def _bar_pct(value: float, bar_max: float) -> float:
    """将数值映射到 0–95% 的进度条宽度，防止溢出。"""
    if bar_max <= 0:
        return 0.0
    return min(round(value / bar_max * 100, 1), 95.0)


# ── 核心：构建模板上下文 ──────────────────────────────────────────────────────
def _build_context(audit_result: dict, request_data: dict) -> dict:
    """将审计结果和请求数据转换为模板所需的上下文字典。"""

    risk_level = audit_result.get("risk_level", "WARNING")
    theme      = _THEMES.get(risk_level, _DEFAULT_THEME)

    findings      = audit_result.get("findings", [])
    count_red     = len(audit_result.get("red_flags", []))
    count_gap     = len(audit_result.get("compliance_gaps", []))
    count_warn    = len(audit_result.get("warnings", []))
    count_pass    = len(audit_result.get("passed", []))

    recs_raw       = audit_result.get("recommendations", [])
    recommendations = list(enumerate(recs_raw, start=1))  # [(1, "..."), (2, "...")]

    battery_type = str(request_data.get("battery_type", "LFP")).upper()
    energy_value = request_data.get("energy_usage")
    recycled_val = request_data.get("recycled_rate")

    # 能耗可视化参数（基于电池类型选取范围）
    energy_ranges = {
        "LFP": (50, 85, 65),   # (min, max, avg)
        "NCM": (60, 110, 85),
        "NMC": (60, 110, 85),
    }
    e_min, e_max, e_avg = energy_ranges.get(battery_type, (50, 85, 65))
    energy_bar_max = e_max * 1.4   # 条形图满格 = 合理上限 × 1.4

    # ── CEO 看板变量 ─────────────────────────────────────────────────────
    # 合规星级
    star_map = {"RED_FLAG": "★☆☆☆☆", "COMPLIANCE_GAP": "★★☆☆☆", "WARNING": "★★★☆☆", "PASS": "★★★★★"}
    grade_map = {"RED_FLAG": "F — 高风险", "COMPLIANCE_GAP": "C — 合规缺口", "WARNING": "B — 需改进", "PASS": "A — 优秀"}

    # 碳排缺口
    cf_val = _to_float(request_data.get("carbon_footprint_kg_co2e_per_kwh"))
    cf_avg = {"LFP": 60, "NCM": 85, "NMC": 85}.get(battery_type, 65)
    if cf_val is not None:
        gap = cf_val - cf_avg
        carbon_gap_display = f"+{gap:.0f}" if gap > 0 else f"{gap:.0f}"
        carbon_gap_color   = "#C0392B" if gap > 0 else "#1A5C38"
    else:
        carbon_gap_display, carbon_gap_color = "未申报", "#8a8fa8"

    # 造假风险
    fraud_level   = "高" if count_red > 0 else ("中" if count_gap > 0 else "低")
    fraud_bg      = "#FFF0F0" if count_red > 0 else ("#FFFFF0" if count_gap > 0 else "#F0FFF6")
    fraud_border  = "#E74C3C" if count_red > 0 else ("#E67E22" if count_gap > 0 else "#27AE60")
    fraud_color   = "#C0392B" if count_red > 0 else ("#D35400" if count_gap > 0 else "#1A5C38")

    # 生存预测
    lifecycle = audit_result.get("lifecycle_prediction", {})
    survival_year = lifecycle.get("survival_year")
    if survival_year is None:
        survival_display = "安全"
        survival_color   = "#1A5C38"
    else:
        survival_display = str(survival_year)
        survival_color   = "#C0392B" if survival_year <= 2027 else "#D35400"

    # 供应链穿透图节点
    mineral_origin = str(request_data.get("mineral_origin", "")).strip()
    mfg_country    = str(request_data.get("manufacturing_country", "")).strip()
    has_cf         = cf_val is not None
    has_recycled   = _to_float(request_data.get("recycled_rate")) is not None

    _high_risk = ["xinjiang", "drc", "congo", "myanmar"]
    origin_risk = any(r in mineral_origin.lower() for r in _high_risk)

    supply_chain_nodes = [
        {"icon": "⛏",  "label": "矿山 Mining",      "status": "高风险" if origin_risk else "未知",
         "color": "#C0392B" if origin_risk else "#E67E22"},
        {"icon": "🏭",  "label": "精炼 Refining",    "status": "黑盒" if not mineral_origin else "已知",
         "color": "#E74C3C" if not mineral_origin else "#E67E22"},
        {"icon": "⚗",   "label": "电芯 Cell",        "status": "审计" if has_cf else "未审计",
         "color": "#27AE60" if has_cf else "#E74C3C"},
        {"icon": "🔋",  "label": "电池包 Pack",      "status": "审计" if has_recycled else "部分",
         "color": "#27AE60" if has_recycled else "#E67E22"},
        {"icon": "🚢",  "label": "运输 Transport",   "status": "已知" if mfg_country else "黑盒",
         "color": "#27AE60" if mfg_country else "#E74C3C"},
        {"icon": "🇪🇺", "label": "欧盟 EU Market",  "status": "目标市场",
         "color": "#2C3E7A"},
    ]

    # 生命周期时间轴（仅取前 6 个里程碑）
    lifecycle_events = lifecycle.get("timeline", [])[:6]
    lifecycle_verdict = lifecycle.get("verdict", "")

    ctx: dict = {
        # 字体
        "font_url": _FONT_PATH.as_uri(),

        # 主题色
        **theme,

        # 元数据
        "report_id":    str(uuid.uuid4())[:8].upper(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M UTC+8"),
        "battery_type": battery_type,

        # 风险摘要
        "risk_level":  risk_level,
        "summary":     audit_result.get("summary", ""),

        # CEO 看板
        "compliance_stars": star_map.get(risk_level, "★★☆☆☆"),
        "compliance_grade": grade_map.get(risk_level, "C"),
        "carbon_gap_display": carbon_gap_display,
        "carbon_gap_color":   carbon_gap_color,
        "fraud_level":    fraud_level,
        "fraud_bg":       fraud_bg,
        "fraud_border":   fraud_border,
        "fraud_color":    fraud_color,
        "red_flag_count": count_red,
        "survival_display": survival_display,
        "survival_color":   survival_color,

        # 供应链穿透图
        "supply_chain_nodes": supply_chain_nodes,

        # 统计
        "total_findings": len(findings),
        "count_red":   count_red,
        "count_gap":   count_gap,
        "count_warn":  count_warn,
        "count_pass":  count_pass,

        # 指标卡片
        "energy_display":  _safe(energy_value, "未申报"),
        "energy_color":    "#C0392B" if (energy_value is not None and energy_value < e_min) else "#1A5C38",
        "energy_range":    f"{e_min}–{e_max}",
        "energy_avg":      e_avg,

        "recycled_display": _safe(recycled_val, "未申报"),
        "recycled_color":   "#C0392B" if (recycled_val is not None and recycled_val < 6) else "#1A5C38",

        # 能耗进度条
        "energy_value":         energy_value,
        "energy_bar_pct":       _bar_pct(energy_value, energy_bar_max) if energy_value is not None else 0,
        "energy_min_mark_pct":  _bar_pct(e_min, energy_bar_max),
        "energy_bar_max":       energy_bar_max,

        # 详细结果
        "findings":          findings,
        "recommendations":   recommendations,
        "lifecycle_events":  lifecycle_events,
        "lifecycle_verdict": lifecycle_verdict,
    }

    return ctx


# ── 公开接口 ──────────────────────────────────────────────────────────────────
def build_pdf(audit_result: dict, request_data: dict) -> bytes:
    """
    将审计结果渲染为 PDF，返回 bytes。

    Parameters
    ----------
    audit_result  : audit_battery_data() 的返回值
    request_data  : 原始请求字段（battery_type / energy_usage / recycled_rate）

    Returns
    -------
    bytes : PDF 文件内容，可直接写入文件或通过 FastAPI Response 返回
    """
    # ── 字体检查 ────────────────────────────────────────────────────────────
    if not _FONT_PATH.exists():
        raise FileNotFoundError(
            f"中文字体缺失：{_FONT_PATH}\n"
            "请将 NotoSansSC-Regular.otf 放入项目根目录的 fonts/ 文件夹。"
        )

    # ── Jinja2 环境 ─────────────────────────────────────────────────────────
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # 注册 enumerate 供模板使用
    env.globals["enumerate"] = enumerate

    template = env.get_template("report.html")
    ctx      = _build_context(audit_result, request_data)
    html_str = template.render(**ctx)

    # ── WeasyPrint 渲染 ─────────────────────────────────────────────────────
    # base_url 设为项目根目录，确保相对路径资源可被正确解析
    pdf_bytes = HTML(
        string=html_str,
        base_url=str(_PROJECT_ROOT),
    ).write_pdf()

    return pdf_bytes
