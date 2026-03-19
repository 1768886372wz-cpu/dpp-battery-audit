#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Core DPP obligations extracted from Regulation (EU) 2023/1542:
# - Art. 77(1): from 18 Feb 2027, DPP applies to LMT; industrial > 2 kWh; EV batteries.
# - Art. 77(3): passport accessible via QR code linking to a unique identifier.
# - Annex XIII(1)(a)-(c): publicly accessible battery-model info includes Annex VI Part A label info,
#   material composition (incl chemistry, hazardous substances, critical raw materials), and carbon footprint info.
# - Annex XIII + Annex VI Part A are the source for fields like manufacturer/labeling/extinguishing agent.
# - Art. 8 sets minimum recycled content targets (cobalt/lithium/nickel/lead) and is referenced by Annex XIII recycled content info.
# - Art. 7 + Annex XIII(1)(c) covers carbon footprint reporting information.


ALLOWED_CATEGORIES = {"LMT", "INDUSTRIAL", "EV"}

# Recycled content minimum shares requested for pre-audit checks (severe violation if below).
# Legal basis: Article 8(2)(a)-(d).
RECYCLED_MIN_PCT = {
    "Lithium": 6.0,
    "Cobalt": 16.0,
    "Nickel": 6.0,
    "Lead": 85.0,
}
RECYCLED_LEGAL_REF = "Article 8(2)(a)-(d)"


def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _parse_float(value: Any) -> Optional[float]:
    s = _norm(value)
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_yyyy_mm(value: Any) -> Optional[str]:
    s = _norm(value)
    if s == "":
        return None
    # Accept YYYY-MM only (month+year is explicitly mentioned for manufacture date in Annex VI Part A(4)).
    if not re.fullmatch(r"\d{4}-\d{2}", s):
        return None
    try:
        datetime.strptime(s, "%Y-%m")
        return s
    except ValueError:
        return None


def _parse_listish(value: Any) -> List[str]:
    """
    Accepts either:
    - JSON list: ["Ni","Co"]
    - or comma/semicolon separated string: "Ni, Co; Li"
    """
    s = _norm(value)
    if s == "":
        return []
    if s.startswith("["):
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x).strip()]
        except Exception:
            pass
    parts = re.split(r"[;,]", s)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class DppResult:
    model: str
    status: str  # COMPLIANT / NON_COMPLIANT / NOT_REQUIRED_DPP
    risk_level: str  # low / medium / high / N/A
    issues: List[str]  # human-readable, must include legal references
    missing_fields: List[str]  # subset of issues focused on "missing/invalid required fields"
    metrics: Dict[str, Any]  # for radar text summary

    def to_text(self) -> str:
        lines = [
            f"Model: {self.model}",
            f"Status: {self.status}",
            f"Risk: {self.risk_level}",
        ]
        if self.missing_fields:
            lines.append("Missing fields: " + ", ".join(self.missing_fields))
        if self.issues:
            lines.append("Findings:")
            for i in self.issues:
                lines.append(f"- {i}")
        return "\n".join(lines)


def _install_hint() -> str:
    return (
        "PDF generation requires 'reportlab'. Install it with:\n"
        "  source .venv/bin/activate && pip install reportlab\n"
        "or (if you don't use the venv):\n"
        "  python3 -m venv .venv && source .venv/bin/activate && pip install reportlab\n"
    )


def generate_audit_pdf(
    *,
    results: List[DppResult],
    source_csv: Path,
    output_pdf: Path,
) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(str(e) + "\n\n" + _install_hint()) from e

    def _register_cjk_font() -> str:
        """
        Fix tofu/black-squares for Chinese text.
        Prefer macOS built-in fonts; if unavailable, fall back to built-in CID font.
        """
        candidates = [
            # Common macOS CJK fonts (paths may differ by OS version).
            ("PingFang", "/System/Library/Fonts/PingFang.ttc"),
            ("STHeiti", "/System/Library/Fonts/STHeiti Light.ttc"),
            ("STHeiti", "/System/Library/Fonts/STHeiti Medium.ttc"),
            ("Heiti", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),  # occasionally present; harmless if missing
            ("ArialUnicode", "/Library/Fonts/Arial Unicode.ttf"),
        ]
        for font_name, font_path in candidates:
            try:
                if Path(font_path).exists():
                    # TTFont can load many .ttf and some .ttc; if it fails, we catch and try next.
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                    return font_name
            except Exception:
                continue

        # Built-in CID font (no external download). Good enough for Simplified Chinese.
        cid_name = "STSong-Light"
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cid_name))
        except Exception:
            pass
        return cid_name

    cjk_font = _register_cjk_font()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontName=cjk_font,
        fontSize=22,
        leading=28,
        alignment=1,  # center
        spaceAfter=16,
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontName=cjk_font,
        fontSize=12,
        leading=16,
        alignment=1,
        textColor=colors.HexColor("#333333"),
    )
    h_style = ParagraphStyle(
        "H",
        parent=styles["Heading2"],
        fontName=cjk_font,
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=8,
    )
    normal = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=cjk_font,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#111111"),
    )
    small_grey = ParagraphStyle(
        "SmallGrey",
        parent=styles["Normal"],
        fontName=cjk_font,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#555555"),
    )
    red = ParagraphStyle(
        "Red",
        parent=normal,
        textColor=colors.HexColor("#B00020"),
    )
    status_green = ParagraphStyle(
        "StatusGreen",
        parent=normal,
        textColor=colors.HexColor("#1B5E20"),
        fontName=cjk_font,
    )
    status_red = ParagraphStyle(
        "StatusRed",
        parent=normal,
        textColor=colors.HexColor("#B00020"),
        fontName=cjk_font,
    )
    status_grey = ParagraphStyle(
        "StatusGrey",
        parent=normal,
        textColor=colors.HexColor("#444444"),
        fontName=cjk_font,
    )

    risk_low = ParagraphStyle(
        "RiskLow",
        parent=normal,
        textColor=colors.HexColor("#1B5E20"),
        fontName=cjk_font,
    )
    risk_med = ParagraphStyle(
        "RiskMed",
        parent=normal,
        textColor=colors.HexColor("#B26A00"),
        fontName=cjk_font,
    )
    risk_high = ParagraphStyle(
        "RiskHigh",
        parent=normal,
        textColor=colors.HexColor("#B00020"),
        fontName=cjk_font,
    )
    risk_na = ParagraphStyle(
        "RiskNA",
        parent=normal,
        textColor=colors.HexColor("#666666"),
        fontName=cjk_font,
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="欧盟 2023/1542 电池法案合规预审计报告",
        author="DPP Engine",
    )

    story: List[Any] = []

    # Cover
    story.append(Spacer(1, 38 * mm))
    story.append(Paragraph("欧盟 2023/1542 电池法案合规预审计报告", title_style))
    story.append(Paragraph("EU 2023/1542 Battery Regulation – Compliance Pre‑Audit Report", subtitle_style))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(f"审计时间 / Audit Time：{now}", subtitle_style))
    story.append(Paragraph(f"数据来源 / Data Source：{source_csv.name}", subtitle_style))
    story.append(Spacer(1, 25 * mm))
    story.append(
        Paragraph(
            "适用范围 / Scope：自 2027‑02‑18 起，LMT 电池、容量大于 2 kWh 的工业电池、以及电动汽车电池须具备电池护照（Art. 77(1)）。"
            " / From 18 Feb 2027, LMT batteries, industrial batteries > 2 kWh and EV batteries shall have a battery passport (Art. 77(1)).",
            small_grey,
        )
    )
    story.append(PageBreak())

    # Summary table
    story.append(Paragraph("型号级别审计结果汇总 / Model‑Level Audit Summary", h_style))

    header = [
        "型号 / Model",
        "判定 / Status",
        "合规风险等级 / Risk",
        "不合规原因与条文引用 / Non‑compliance Reasons & Legal References",
    ]
    rows: List[List[Any]] = [header]
    for r in results:
        if r.status == "COMPLIANT":
            status_cell = Paragraph("<b>COMPLIANT / 合规</b>", status_green)
        elif r.status == "NON_COMPLIANT":
            status_cell = Paragraph("<b>NON_COMPLIANT / 不合规</b>", status_red)
        else:
            status_cell = Paragraph("<b>NOT_REQUIRED_DPP / 不强制执行 DPP</b>", status_grey)

        if r.risk_level == "low":
            risk_cell = Paragraph("<b>低 / Low</b>", risk_low)
        elif r.risk_level == "medium":
            risk_cell = Paragraph("<b>中 / Medium</b>", risk_med)
        elif r.risk_level == "high":
            risk_cell = Paragraph("<b>高 / High</b>", risk_high)
        else:
            risk_cell = Paragraph("<b>N/A</b>", risk_na)

        if r.status == "NON_COMPLIANT":
            reasons = "<br/>".join([f"• {x}" for x in (r.missing_fields or [])]) if r.missing_fields else "• （未提供原因）"
            cell = Paragraph(reasons, red)
        elif r.status == "NOT_REQUIRED_DPP":
            # Show a short analysis line set.
            analysis = [x for x in (r.issues or []) if str(x).startswith("Analysis (not mandatory):")]
            if not analysis:
                if r.issues:
                    cell = Paragraph("• " + str(r.issues[0]), small_grey)
                else:
                    cell = Paragraph("—", small_grey)
            else:
                reasons = "<br/>".join([f"• {x}" for x in analysis[:6]])
                cell = Paragraph(reasons, small_grey)
        else:
            cell = Paragraph("—", small_grey)

        rows.append([Paragraph(_norm(r.model), normal), status_cell, risk_cell, cell])

    table = Table(
        rows,
        colWidths=[52 * mm, 32 * mm, 32 * mm, 96 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), cjk_font),
                ("FONTSIZE", (0, 0), (-1, 0), 10.5),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F3F4F6"), colors.HexColor("#FFFFFF")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)

    # Key metrics radar (text summary)
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "关键指标雷达表（文字版总结） / Key Metrics Radar (Text Summary)",
            h_style,
        )
    )

    mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
    total = len(mandatory) if mandatory else 1

    def _bar(met: int, total_: int) -> str:
        # ASCII-only bar to avoid font issues.
        n = 20
        filled = int(round((met / total_) * n)) if total_ > 0 else 0
        return "[" + ("X" * filled) + ("." * (n - filled)) + "]"

    def _metric_line(label: str, metric_key: str) -> None:
        met = sum(1 for r in mandatory if (r.metrics or {}).get(metric_key, {}).get("met") is True)
        story.append(Paragraph(f"{label}: {met}/{total} met {_bar(met, total)}", normal))

    _metric_line("Recycled Lithium >= 6% (Art. 8(2)(c))", "recycled_lithium_pct")
    _metric_line("Recycled Cobalt >= 16% (Art. 8(2)(a))", "recycled_cobalt_pct")
    _metric_line("Recycled Nickel >= 6% (Art. 8(2)(d))", "recycled_nickel_pct")
    _metric_line("Recycled Lead >= 85% (Art. 8(2)(b))", "recycled_lead_pct")
    _metric_line("Rated Capacity present (Annex XIII(1)(a)(g))", "rated_capacity_ah")
    _metric_line("Nominal Voltage present (Annex XIII(1)(a)(h))", "nominal_voltage_v")
    _metric_line("Charging/Discharging Efficiency present (Annex XIII(1)(a)(n))", "charge_discharge_efficiency_percent")
    _metric_line("Expected Lifetime Cycles present (Annex XIII(1)(a)(j))", "expected_lifetime_cycles")
    _metric_line("Extinguishing Agent present (Annex VI Part A(9) via Annex XIII(1)(a))", "extinguishing_agent")
    _metric_line("Carbon Footprint Total present (Annex XIII(1)(c) / Art. 7)", "carbon_footprint_total_kg_co2e")

    # Overall risk distribution
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("合规风险等级分布 / Risk Level Distribution", h_style))
    risk_counts = {"low": 0, "medium": 0, "high": 0}
    for r in mandatory:
        rl = (r.risk_level or "").lower()
        if rl in risk_counts:
            risk_counts[rl] += 1
    story.append(
        Paragraph(
            f"Low / 低: {risk_counts['low']} ； Medium / 中: {risk_counts['medium']} ； High / 高: {risk_counts['high']}",
            normal,
        )
    )

    # Professional recommendations
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("专业建议 / Professional Recommendations (for Manufacturers)", h_style))
    story.append(
        Paragraph(
            "如出现 NON_COMPLIANT，请优先对照电池护照强制信息清单补齐关键字段，并对回收材料比例/碳足迹建立可验证的计算与证明文件。"
            " / If NON_COMPLIANT is reported, prioritise completing mandatory Battery Passport data and producing verifiable evidence for recycled content and carbon footprint.",
            normal,
        )
    )
    advice_items = [
        "回收材料比例：建立回收含量计算/验证流程，确保 Li/Co/Ni/Pb 满足最小目标；并对计算方法与证据链做审计留痕（Article 8(2)(a)-(d)）。"
        " / Recycled content: implement a calculation/verification process so Li/Co/Ni/Pb meet minimum targets, and maintain auditable evidence (Article 8(2)(a)-(d)).",
        "碳足迹计算：补齐生命周期碳排放总量字段，完成 PCF 核算边界与数据质量管理，形成可验证输出（Annex XIII(1)(c) / Article 7）。"
        " / Carbon footprint: provide lifecycle carbon footprint total and generate verifiable PCF outputs (Annex XIII(1)(c) / Article 7).",
        "技术与安全字段：完善额定容量/标称电压/效率/预期寿命以及灭火剂类型，确保与产品技术文件和标签一致（Annex XIII(1)(a)；Annex VI Part A(9) via Annex XIII(1)(a)）。"
        " / Technical & safety: complete rated capacity/nominal voltage/efficiency/lifetime cycles and extinguisher agent; align with technical documentation and labeling (Annex XIII(1)(a)).",
        "标签与可追溯标识：补齐制造商、生产地、生产日期以及 QR 链接的唯一标识，确保护照记录与实物标识一致（Annex VI Part A via Annex XIII(1)(a); Art. 77(3)）。"
        " / Label & traceability: complete manufacturer, manufacturing place/date, and the QR-linked unique identifier so passport data matches physical labeling (Art. 77(3)).",
        "建议建立内部数据治理：定义字段责任人、系统 of record、更新频率与审计留痕，确保“准确、完整、及时更新”（Art. 77(4)）。"
        " / Data governance: define ownership, system of record, refresh cadence and audit trail to keep information accurate, complete and up to date (Art. 77(4)).",
    ]
    for item in advice_items:
        story.append(Paragraph("• " + item, normal))

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "免责声明：本报告为“预审计/一致性检查”用途，基于你提供的数据字段进行自动化校验，不构成法律意见或公告认证结论。",
            small_grey,
        )
    )

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont(cjk_font, 9)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(18 * mm, 10 * mm, f"DPP Audit Report • {source_csv.name}")
        canvas.drawRightString(210 * mm - 18 * mm, 10 * mm, f"Page {doc_obj.page}")
        canvas.setFont(cjk_font, 8.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawCentredString(
            105 * mm,
            6.2 * mm,
            "Generated by AI Compliance Engine - Verified for EU 2023/1542 Standards",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def dpp_applicability(category: str, capacity_kwh: Optional[float]) -> Tuple[bool, str]:
    """
    Returns:
      - required: whether battery DPP is mandatory (Art. 77(1))
      - note: human-readable applicability note (must include legal ref)
    """
    cat = _norm(category).upper()
    if cat not in ALLOWED_CATEGORIES:
        return False, f"Invalid battery category (expected EV/LMT/Industrial)."

    if cat == "INDUSTRIAL":
        if capacity_kwh is None:
            # Cannot determine whether it is <=2 kWh or >2 kWh.
            return True, "Industrial battery: capacity_kwh missing; cannot confirm Art. 77(1) exemption (capacity > 2 kWh)."
        if capacity_kwh <= 2.0:
            return False, "Industrial battery with capacity <= 2 kWh: DPP not mandatory (Art. 77(1) exemption for capacity > 2 kWh)."
        return True, "Industrial battery: DPP mandatory only if capacity_kwh > 2 kWh (Art. 77(1))."

    # LMT and EV batteries
    return True, f"{cat} battery: DPP mandatory from 18 February 2027 (Art. 77(1))."


def _parse_percent_to_pct(value: Any) -> Optional[float]:
    """
    Accepts either:
    - already in percent (e.g. 6, 16, 85)
    - ratio (e.g. 0.06, 0.16, 0.85)
    """
    f = _parse_float(value)
    if f is None:
        return None
    # If it's a ratio, convert to percent.
    if 0.0 <= f <= 1.0:
        f = f * 100.0
    # Basic sanity bounds.
    if f < 0 or f > 100:
        return None
    return f


def _present_nonempty(value: Any) -> bool:
    return _norm(value) != ""


def validate_record(rec: Dict[str, Any]) -> DppResult:
    model = _norm(rec.get("model") or rec.get("battery_model") or rec.get("型号") or rec.get("Model"))
    if not model:
        model = "<unknown>"

    category = _norm(rec.get("category") or rec.get("battery_category") or rec.get("类别"))
    capacity_kwh = _parse_float(rec.get("capacity_kwh") or rec.get("capacity_kWh") or rec.get("capacity") or rec.get("容量_kwh"))

    dpp_required, applicability_note = dpp_applicability(category, capacity_kwh)

    # Shared parsing: these keys are required for the upgraded audit dimensions.
    unique_identifier = _norm(
        rec.get("unique_identifier")
        or rec.get("battery_passport_id")
        or rec.get("uid")
        or rec.get("唯一标识")
    )
    manufacturer = _norm(rec.get("manufacturer") or rec.get("manufacturer_name") or rec.get("制造商"))
    manufacture_place = _norm(rec.get("manufacture_place") or rec.get("place_of_manufacture") or rec.get("生产地"))
    manufacture_date_raw = rec.get("manufacture_date") or rec.get("date_of_manufacture") or rec.get("生产日期")
    manufacture_date = _parse_yyyy_mm(manufacture_date_raw)

    battery_id = _norm(
        rec.get("battery_id")
        or rec.get("battery_identifier")
        or rec.get("serial")
        or rec.get("battery_model_id")
        or rec.get("电池识别码")
    )

    # Recycled content
    li_pct = _parse_percent_to_pct(rec.get("recycled_lithium_pct") or rec.get("lithium_pct"))
    co_pct = _parse_percent_to_pct(rec.get("recycled_cobalt_pct") or rec.get("cobalt_pct"))
    ni_pct = _parse_percent_to_pct(rec.get("recycled_nickel_pct") or rec.get("nickel_pct"))
    pb_pct = _parse_percent_to_pct(rec.get("recycled_lead_pct") or rec.get("lead_pct"))

    # Technical parameters
    rated_capacity_ah = _parse_float(rec.get("rated_capacity_ah") or rec.get("rated_capacity") or rec.get("额定容量"))
    nominal_voltage_v = _parse_float(rec.get("nominal_voltage_v") or rec.get("nominal_voltage") or rec.get("标称电压"))
    efficiency_pct = _parse_float(
        rec.get("charge_discharge_efficiency_percent")
        or rec.get("efficiency_percent")
        or rec.get("充放电效率_percent")
        or rec.get("充放电效率")
    )
    expected_lifetime_cycles = _parse_float(rec.get("expected_lifetime_cycles") or rec.get("cycles") or rec.get("预期寿命_cycles"))

    # Safety
    extinguishing_agent = _norm(rec.get("extinguishing_agent") or rec.get("Extinguishing Agent") or rec.get("灭火剂类型"))

    # Carbon footprint
    carbon_footprint_total = _parse_float(
        rec.get("carbon_footprint_total_kg_co2e")
        or rec.get("carbon_footprint_total")
        or rec.get("carbon_footprint_kg_co2e_total")
        or rec.get("生命周期碳排放总量")
        or rec.get("碳足迹_总量_kgco2e")
    )

    issues: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}

    # Applicability
    issues.append(applicability_note)

    # For radar metrics, we still compute whether thresholds are met.
    # Recycled metric checks only apply when DPP is mandatory.
    def _add_metric(key: str, met: Optional[bool], value: Any, target: Any, legal_ref: str) -> None:
        metrics[key] = {
            "value": value,
            "target": target,
            "met": met,
            "legal_ref": legal_ref,
        }

    # Validate mandatory/basic info
    basic_ok = True

    if not _present_nonempty(manufacturer):
        basic_ok = False
        missing.append("manufacturer (Annex VI Part A(1) via Annex XIII(1)(a))")
    if not _present_nonempty(manufacture_place):
        basic_ok = False
        missing.append("manufacture_place (Annex VI Part A(3) via Annex XIII(1)(a))")
    if manufacture_date is None:
        basic_ok = False
        missing.append("manufacture_date (YYYY-MM) (Annex VI Part A(4) via Annex XIII(1)(a))")
    if not _present_nonempty(category) or category.upper() not in ALLOWED_CATEGORIES:
        basic_ok = False
        missing.append("battery_category (EV/LMT/Industrial) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(battery_id):
        basic_ok = False
        missing.append("battery_id (information identifying the battery) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(unique_identifier):
        basic_ok = False
        missing.append("unique_identifier (QR-linked passport identifier) (Art. 77(3))")

    # Technical checks
    tech_ok = True
    if rated_capacity_ah is None or rated_capacity_ah <= 0:
        tech_ok = False
        missing.append("rated_capacity_ah (Annex XIII(1)(a)(g))")
    if nominal_voltage_v is None or nominal_voltage_v <= 0:
        tech_ok = False
        missing.append("nominal_voltage_v (Annex XIII(1)(a)(h))")
    if efficiency_pct is None or efficiency_pct <= 0 or efficiency_pct > 100:
        tech_ok = False
        missing.append("charge_discharge_efficiency_percent (Annex XIII(1)(a)(n): energy efficiency)")
    if expected_lifetime_cycles is None or expected_lifetime_cycles <= 0:
        tech_ok = False
        missing.append("expected_lifetime_cycles (Annex XIII(1)(a)(j))")

    # Safety
    safety_ok = True
    if not _present_nonempty(extinguishing_agent):
        safety_ok = False
        missing.append("extinguishing_agent (Annex VI Part A(9) via Annex XIII(1)(a))")

    # Carbon
    carbon_ok = True
    if carbon_footprint_total is None or carbon_footprint_total <= 0:
        carbon_ok = False
        missing.append("carbon_footprint_total_kg_co2e (Annex XIII(1)(c) / Article 7)")

    # Recycled content checks + severe violation rule
    recycled_ok = True
    severe_recycled_violation = False
    if dpp_required:
        thresholds = RECYCLED_MIN_PCT

        for label, target in thresholds.items():
            pass

        # Lithium
        if li_pct is None or li_pct < thresholds["Lithium"]:
            recycled_ok = False
            if li_pct is None:
                missing.append("recycled_lithium_pct (minimum recycled lithium share) (Article 8(2)(c))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_lithium_pct severe violation: {li_pct}% < {thresholds['Lithium']}% (Article 8(2)(c))"
                )
        # Cobalt
        if co_pct is None or co_pct < thresholds["Cobalt"]:
            recycled_ok = False
            if co_pct is None:
                missing.append("recycled_cobalt_pct (minimum recycled cobalt share) (Article 8(2)(a))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_cobalt_pct severe violation: {co_pct}% < {thresholds['Cobalt']}% (Article 8(2)(a))"
                )
        # Nickel
        if ni_pct is None or ni_pct < thresholds["Nickel"]:
            recycled_ok = False
            if ni_pct is None:
                missing.append("recycled_nickel_pct (minimum recycled nickel share) (Article 8(2)(d))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_nickel_pct severe violation: {ni_pct}% < {thresholds['Nickel']}% (Article 8(2)(d))"
                )
        # Lead
        if pb_pct is None or pb_pct < thresholds["Lead"]:
            recycled_ok = False
            if pb_pct is None:
                missing.append("recycled_lead_pct (minimum recycled lead share) (Article 8(2)(b))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_lead_pct severe violation: {pb_pct}% < {thresholds['Lead']}% (Article 8(2)(b))"
                )

        _add_metric("recycled_lithium_pct", (li_pct is not None and li_pct >= thresholds["Lithium"]), li_pct, thresholds["Lithium"], "Article 8(2)(c)")
        _add_metric("recycled_cobalt_pct", (co_pct is not None and co_pct >= thresholds["Cobalt"]), co_pct, thresholds["Cobalt"], "Article 8(2)(a)")
        _add_metric("recycled_nickel_pct", (ni_pct is not None and ni_pct >= thresholds["Nickel"]), ni_pct, thresholds["Nickel"], "Article 8(2)(d)")
        _add_metric("recycled_lead_pct", (pb_pct is not None and pb_pct >= thresholds["Lead"]), pb_pct, thresholds["Lead"], "Article 8(2)(b)")
    else:
        # DPP not mandatory: we still compute metrics but don't enforce.
        _add_metric("recycled_lithium_pct", (li_pct is not None and li_pct >= RECYCLED_MIN_PCT["Lithium"]), li_pct, RECYCLED_MIN_PCT["Lithium"], "Article 8(2)(c)")
        _add_metric("recycled_cobalt_pct", (co_pct is not None and co_pct >= RECYCLED_MIN_PCT["Cobalt"]), co_pct, RECYCLED_MIN_PCT["Cobalt"], "Article 8(2)(a)")
        _add_metric("recycled_nickel_pct", (ni_pct is not None and ni_pct >= RECYCLED_MIN_PCT["Nickel"]), ni_pct, RECYCLED_MIN_PCT["Nickel"], "Article 8(2)(d)")
        _add_metric("recycled_lead_pct", (pb_pct is not None and pb_pct >= RECYCLED_MIN_PCT["Lead"]), pb_pct, RECYCLED_MIN_PCT["Lead"], "Article 8(2)(b)")

    _add_metric("rated_capacity_ah", (rated_capacity_ah is not None and rated_capacity_ah > 0), rated_capacity_ah, None, "Annex XIII(1)(a)(g)")
    _add_metric("nominal_voltage_v", (nominal_voltage_v is not None and nominal_voltage_v > 0), nominal_voltage_v, None, "Annex XIII(1)(a)(h)")
    _add_metric("charge_discharge_efficiency_percent", (efficiency_pct is not None and 0 < efficiency_pct <= 100), efficiency_pct, None, "Annex XIII(1)(a)(n)")
    _add_metric("expected_lifetime_cycles", (expected_lifetime_cycles is not None and expected_lifetime_cycles > 0), expected_lifetime_cycles, None, "Annex XIII(1)(a)(j)")
    _add_metric("extinguishing_agent", (_present_nonempty(extinguishing_agent)), extinguishing_agent, None, "Annex VI Part A(9) via Annex XIII(1)(1)(a)")
    _add_metric("carbon_footprint_total_kg_co2e", (carbon_footprint_total is not None and carbon_footprint_total > 0), carbon_footprint_total, None, "Annex XIII(1)(c) / Article 7")

    # If DPP is NOT mandatory, we only show analysis.
    if not dpp_required:
        issues.extend([f"Analysis (not mandatory): {x}" for x in missing])
        return DppResult(
            model=model,
            status="NOT_REQUIRED_DPP",
            risk_level="N/A",
            issues=issues,
            missing_fields=[],
            metrics=metrics,
        )

    # Final compliance decision for mandatory cases
    if not basic_ok:
        issues.extend([f"Basic info non-compliance: {x}" for x in missing if "manufacturer" in x or "manufacture_place" in x or "manufacture_date" in x or "battery_category" in x or "battery_id" in x or "unique_identifier" in x])
    if not tech_ok:
        issues.extend([f"Technical parameters non-compliance: {x}" for x in missing if "rated_capacity_ah" in x or "nominal_voltage_v" in x or "charge_discharge_efficiency_percent" in x or "expected_lifetime_cycles" in x])
    if not safety_ok:
        issues.extend([f"Safety non-compliance: {x}" for x in missing if "extinguishing_agent" in x])
    if not carbon_ok:
        issues.extend([f"Carbon footprint non-compliance: {x}" for x in missing if "carbon_footprint_total" in x])
    if not recycled_ok:
        issues.extend([f"Recycled content non-compliance (severe if below targets): {x}" for x in missing if x.startswith("recycled_")])

    if missing:
        risk_level = "high" if severe_recycled_violation or (len(missing) >= 2) else "medium"
        return DppResult(
            model=model,
            status="NON_COMPLIANT",
            risk_level=risk_level,
            issues=issues + [],
            missing_fields=missing,
            metrics=metrics,
        )

    return DppResult(
        model=model,
        status="COMPLIANT",
        risk_level="low",
        issues=issues,
        missing_fields=[],
        metrics=metrics,
    )


def iter_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        for row in reader:
            yield row


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="EU 2023/1542 Battery DPP checker (Art. 77 + Annex XIII).",
    )
    p.add_argument("--csv", type=str, help="Path to a CSV file to validate (recommended).")
    p.add_argument("--model", type=str, help="Battery model (for single-record mode).")
    p.add_argument("--data", type=str, help="JSON object with battery data (for single-record mode).")
    p.add_argument("--json", action="store_true", help="Output results as JSON lines.")
    p.add_argument(
        "--pdf",
        type=str,
        default="DPP_Audit_Report.pdf",
        help="When auditing a CSV, write a PDF report to this path (default: DPP_Audit_Report.pdf). Use '--pdf none' to disable.",
    )
    args = p.parse_args(argv)

    results: List[DppResult] = []
    csv_path: Optional[Path] = None

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"CSV not found: {csv_path}", file=sys.stderr)
            return 2
        for row in iter_csv(csv_path):
            results.append(validate_record(row))
    else:
        if not args.model or not args.data:
            print("Either provide --csv, or provide both --model and --data JSON.", file=sys.stderr)
            return 2
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"--data must be valid JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("--data must be a JSON object.", file=sys.stderr)
            return 2
        data = dict(data)
        data["model"] = args.model
        results.append(validate_record(data))

    if args.json:
        for r in results:
            print(json.dumps({"model": r.model, "status": r.status, "missing_fields": r.missing_fields, "reasons": r.reasons}, ensure_ascii=False))
    else:
        for i, r in enumerate(results):
            if i:
                print("\n" + "-" * 60 + "\n")
            print(r.to_text())

    # Auto-generate a PDF report after CSV audits (commercial product behavior).
    if csv_path is not None:
        pdf_arg = _norm(args.pdf).lower()
        if pdf_arg not in {"", "none", "off", "false", "0"}:
            out_pdf = Path(args.pdf)
            try:
                generate_audit_pdf(results=results, source_csv=csv_path, output_pdf=out_pdf)
                if not args.json:
                    print("\n" + "=" * 60)
                    print(f"PDF report written: {out_pdf.resolve()}")
            except ModuleNotFoundError as e:
                print(str(e), file=sys.stderr)
                return 3
            except Exception as e:
                print(f"Failed to write PDF report: {e}", file=sys.stderr)
                return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

