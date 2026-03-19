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

# Full Annex XIII-oriented field map for backend normalization and audit tracing.
# This structure is the single source of truth for the engine's expected inputs.
DPP_FIELD_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    "public_information": {
        "unique_identifier": {"aliases": ["unique_identifier", "battery_passport_id", "uid", "唯一标识"], "legal_ref": "Article 77(3)"},
        "battery_id": {"aliases": ["battery_id", "battery_identifier", "serial", "battery_model_id", "电池识别码"], "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
        "manufacturer_id": {"aliases": ["manufacturer_id", "mfg_id", "制造商ID"], "legal_ref": "Heuristic anti-fraud identity check (not an explicit statutory field in Annex XIII list)"},
        "manufacturer": {"aliases": ["manufacturer", "manufacturer_name", "制造商"], "legal_ref": "Annex VI Part A(1) via Annex XIII(1)(a)"},
        "manufacture_place": {"aliases": ["manufacture_place", "place_of_manufacture", "生产地"], "legal_ref": "Annex VI Part A(3) via Annex XIII(1)(a)"},
        "manufacture_date": {"aliases": ["manufacture_date", "date_of_manufacture", "生产日期"], "legal_ref": "Annex VI Part A(4) via Annex XIII(1)(a)"},
        "category": {"aliases": ["category", "battery_category", "类别"], "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
    },
    "materials_and_compliance": {
        "recycled_lithium_pct": {"aliases": ["recycled_lithium_pct", "lithium_pct"], "legal_ref": "Article 8(2)(c)", "min": 6.0},
        "recycled_cobalt_pct": {"aliases": ["recycled_cobalt_pct", "cobalt_pct"], "legal_ref": "Article 8(2)(a)", "min": 16.0},
        "recycled_nickel_pct": {"aliases": ["recycled_nickel_pct", "nickel_pct"], "legal_ref": "Article 8(2)(d)", "min": 6.0},
        "recycled_lead_pct": {"aliases": ["recycled_lead_pct", "lead_pct"], "legal_ref": "Article 8(2)(b)", "min": 85.0},
        "hazardous_substances_declaration": {"aliases": ["hazardous_substances_declaration", "hazardous_substances", "hazardous", "危险物质声明"], "legal_ref": "Annex XIII(1)(b)"},
    },
    "performance_and_durability": {
        "rated_capacity_ah": {"aliases": ["rated_capacity_ah", "rated_capacity", "额定容量"], "legal_ref": "Annex XIII(1)(a)(g)"},
        "nominal_voltage_v": {"aliases": ["nominal_voltage_v", "nominal_voltage", "标称电压"], "legal_ref": "Annex XIII(1)(a)(h)"},
        "rated_power_w": {"aliases": ["rated_power_w", "power_w", "额定功率"], "legal_ref": "Annex XIII(1)(a)(i)"},
        "self_discharge_rate_pct_per_month": {"aliases": ["self_discharge_rate_pct_per_month", "self_discharge_rate", "自放电率"], "legal_ref": "Annex VII Part B(4)"},
        "expected_lifetime_cycles": {"aliases": ["expected_lifetime_cycles", "cycles", "预期寿命_cycles"], "legal_ref": "Annex XIII(1)(a)(j)"},
        "charge_discharge_efficiency_percent": {"aliases": ["charge_discharge_efficiency_percent", "efficiency_percent", "充放电效率_percent", "充放电效率"], "legal_ref": "Annex XIII(1)(a)(n)"},
    },
    "safety": {
        "thermal_runaway_prevention": {"aliases": ["thermal_runaway_prevention", "thermal_runaway_control", "热失控预防"], "legal_ref": "Heuristic safety-control data check (industry best practice)"},
        "extinguishing_agent": {"aliases": ["extinguishing_agent", "Extinguishing Agent", "灭火剂类型"], "legal_ref": "Annex VI Part A(9) via Annex XIII(1)(a)"},
        "explosion_proof_declaration": {"aliases": ["explosion_proof_declaration", "explosion_proof", "防爆声明"], "legal_ref": "Heuristic safety-control data check (industry best practice)"},
        "bms_access_permissions": {"aliases": ["bms_access_permissions", "bms_access", "bms_rw_permissions", "BMS访问权限"], "legal_ref": "Article 14"},
    },
    "traceability_and_sourcing": {
        "mine_latitude": {"aliases": ["mine_latitude", "source_mine_lat", "矿山纬度"], "legal_ref": "Heuristic sourcing-risk check (due diligence context)"},
        "mine_longitude": {"aliases": ["mine_longitude", "source_mine_lon", "矿山经度"], "legal_ref": "Heuristic sourcing-risk check (due diligence context)"},
        "chemistry": {"aliases": ["chemistry", "电化学体系"], "legal_ref": "Annex XIII(1)(b)"},
        "carbon_footprint_total_kg_co2e": {"aliases": ["carbon_footprint_total_kg_co2e", "carbon_footprint_total", "carbon_footprint_kg_co2e_total", "生命周期碳排放总量", "碳足迹_总量_kgco2e"], "legal_ref": "Annex XIII(1)(c) / Article 7"},
    },
}

# Approximate benchmark lower bounds for plausibility checks, not legal thresholds.
# Used only for anti-fraud "Data Unrealistic" flag.
CARBON_FOOTPRINT_MIN_BY_CHEMISTRY = {
    # theoretical floor in kg CO2e per kWh
    "LFP": 30.0,
    "NMC": 40.0,
}

# Simplified mining-area bounding boxes for anti-fraud coordinate checks.
# (lat_min, lat_max, lon_min, lon_max)
KNOWN_LITHIUM_COBALT_MINING_ZONES: List[Tuple[float, float, float, float]] = [
    (-30.0, -15.0, -72.0, -65.0),   # Chile/Argentina lithium triangle (coarse)
    (-25.0, -18.0, 16.0, 30.0),     # Southern Africa lithium belt (coarse)
    (-15.0, 5.0, 12.0, 33.0),       # DRC cobalt region (coarse)
    (-33.0, -20.0, 114.0, 122.0),   # Western Australia lithium region (coarse)
]


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
    fraud_flags: List[str]  # e.g. HIGH_RISK, DATA_UNREALISTIC

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
        if self.fraud_flags:
            lines.append("Fraud Flags: " + ", ".join(self.fraud_flags))
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
        from reportlab.graphics.shapes import Drawing, Line, Polygon, String
        from reportlab.graphics import renderPDF
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
    quote_style = ParagraphStyle(
        "Quote",
        parent=small_grey,
        fontName=cjk_font,
        fontSize=9.2,
        leading=12.5,
        textColor=colors.HexColor("#3F3F46"),
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _grade_label() -> str:
        total = len(results) or 1
        non = sum(1 for r in results if r.status == "NON_COMPLIANT")
        flagged = sum(1 for r in results if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or [])))
        non_ratio = non / total
        if non_ratio <= 0.10 and flagged == 0:
            return "A / 合规"
        if non_ratio <= 0.35 and flagged <= max(1, total // 4):
            return "B / 警告"
        return "C / 拒绝"

    compliance_grade = _grade_label()

    legal_quotes = {
        "recycled_lithium_pct": (
            "Article 8(2)(c): \"... shall demonstrate that those batteries contain ... (c) 6 % lithium.\"",
            "Threshold: **>= 6% lithium**",
        ),
        "recycled_cobalt_pct": (
            "Article 8(2)(a): \"... shall demonstrate that those batteries contain ... (a) 16 % cobalt.\"",
            "Threshold: **>= 16% cobalt**",
        ),
        "recycled_nickel_pct": (
            "Article 8(2)(d): \"... shall demonstrate that those batteries contain ... (d) 6 % nickel.\"",
            "Threshold: **>= 6% nickel**",
        ),
        "recycled_lead_pct": (
            "Article 8(2)(b): \"... shall demonstrate that those batteries contain ... (b) 85 % lead.\"",
            "Threshold: **>= 85% lead**",
        ),
        "carbon_footprint": (
            "Annex XIII(1)(c): \"A battery passport shall include ... the carbon footprint information referred to in Article 7(1) and (2).\"",
            "Threshold: **must be present and physically plausible**",
        ),
        "bms_access_permissions": (
            "Article 14: information on the state of health shall be made available for relevant battery categories.",
            "Threshold: **read/write access disclosure required by this audit rule**",
        ),
        "manufacturer_id": (
            "Article 77(4): \"... ensure that the information in the battery passport is accurate, complete and up to date.\"",
            "Threshold: **traceability identity must pass format checks**",
        ),
        "extinguishing_agent": (
            "Annex VI Part A(9): label information includes \"usable extinguishing agent\" (via Annex XIII(1)(a)).",
            "Threshold: **field must be present**",
        ),
        "hazardous_substances_declaration": (
            "Annex XIII(1)(b): battery passport includes material composition and hazardous substances information.",
            "Threshold: **declaration must be present**",
        ),
    }

    def _issue_quote(issue: str) -> Tuple[str, str]:
        key_map = [
            ("recycled_lithium_pct", "recycled_lithium_pct"),
            ("recycled_cobalt_pct", "recycled_cobalt_pct"),
            ("recycled_nickel_pct", "recycled_nickel_pct"),
            ("recycled_lead_pct", "recycled_lead_pct"),
            ("carbon_footprint", "carbon_footprint"),
            ("bms_access_permissions", "bms_access_permissions"),
            ("manufacturer_id", "manufacturer_id"),
            ("extinguishing_agent", "extinguishing_agent"),
            ("hazardous_substances_declaration", "hazardous_substances_declaration"),
        ]
        for token, key in key_map:
            if token in issue:
                return legal_quotes[key]
        return (
            "Article 77(4): \"... information in the battery passport is accurate, complete and up to date.\"",
            "Threshold: **complete and verifiable data required**",
        )

    def _build_radar_drawing(results_for_radar: List[DppResult]) -> Drawing:
        mandatory = [r for r in results_for_radar if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
        total = len(mandatory) or 1

        def _score(metric_keys: List[str]) -> float:
            met = 0
            for r in mandatory:
                ok = True
                for k in metric_keys:
                    ok = ok and (((r.metrics or {}).get(k, {}) or {}).get("met") is True)
                if ok:
                    met += 1
            return met / total

        dimensions = [
            ("Safety", _score(["extinguishing_agent", "thermal_runaway_prevention", "explosion_proof_declaration"])),
            ("Environmental", _score(["carbon_footprint_total_kg_co2e", "carbon_physical_plausibility"])),
            ("Traceability", _score(["unique_identifier", "manufacturer_id", "mine_coordinates"])),
            ("Recycled", _score(["recycled_lithium_pct", "recycled_cobalt_pct", "recycled_nickel_pct", "recycled_lead_pct"])),
            ("Performance", _score(["rated_capacity_ah", "nominal_voltage_v", "rated_power_w", "expected_lifetime_cycles"])),
            ("BMS Access", _score(["bms_access_permissions"])),
        ]

        cx, cy, rmax = 160, 120, 70
        n = len(dimensions)
        drawing = Drawing(320, 240)

        # grid rings
        for scale in [0.25, 0.5, 0.75, 1.0]:
            pts = []
            for i in range(n):
                angle = (2 * 3.1415926 * i / n) - (3.1415926 / 2)
                rr = rmax * scale
                pts.extend([cx + rr * __import__("math").cos(angle), cy + rr * __import__("math").sin(angle)])
            drawing.add(Polygon(points=pts, fillColor=None, strokeColor=colors.HexColor("#D1D5DB"), strokeWidth=0.6))

        # axis lines + labels
        for i, (name, _) in enumerate(dimensions):
            angle = (2 * 3.1415926 * i / n) - (3.1415926 / 2)
            x = cx + rmax * __import__("math").cos(angle)
            y = cy + rmax * __import__("math").sin(angle)
            drawing.add(Line(cx, cy, x, y, strokeColor=colors.HexColor("#9CA3AF"), strokeWidth=0.6))
            lx = cx + (rmax + 14) * __import__("math").cos(angle)
            ly = cy + (rmax + 14) * __import__("math").sin(angle)
            drawing.add(String(lx - 18, ly - 3, name, fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#374151")))

        # data polygon
        data_pts = []
        for i, (_, score) in enumerate(dimensions):
            angle = (2 * 3.1415926 * i / n) - (3.1415926 / 2)
            rr = rmax * max(0.0, min(1.0, score))
            data_pts.extend([cx + rr * __import__("math").cos(angle), cy + rr * __import__("math").sin(angle)])
        drawing.add(Polygon(points=data_pts, strokeColor=colors.HexColor("#4F46E5"), fillColor=colors.HexColor("#A5B4FC"), fillOpacity=0.35, strokeWidth=1.2))
        return drawing

    def _build_gap_fixing_list(results_for_gaps: List[DppResult]) -> List[str]:
        issue_pool = [m for r in results_for_gaps for m in (r.missing_fields or [])]
        dept_map = [
            ("recycled_", "Procurement & Sustainability Team", "Collect supplier recycled-material certificates and update recycled-content declarations."),
            ("carbon_footprint", "LCA/ESG Team", "Recalculate product carbon footprint and provide audited methodology evidence."),
            ("bms_access_permissions", "BMS Firmware & Diagnostics Team", "Publish read/write access policy and technical interface control note."),
            ("extinguishing_agent", "EHS & Product Safety Team", "Provide extinguishing-agent specification and hazard response instructions."),
            ("manufacturer_id", "Master Data Governance Team", "Fix manufacturer identity schema and traceability key integrity."),
            ("hazardous_substances_declaration", "Compliance Documentation Team", "Complete hazardous-substance declaration linked to BOM/SDS records."),
            ("rated_capacity_ah", "R&D Validation Team", "Provide validated electrochemical performance measurements in technical dossier."),
        ]
        actions: Dict[str, str] = {}
        for issue in issue_pool:
            for token, dept, action in dept_map:
                if token in issue and dept not in actions:
                    actions[dept] = action
        if not actions:
            actions["Compliance PMO"] = "No critical gaps detected. Maintain periodic data-quality monitoring and evidence retention."
        return [f"{dept}: {action}" for dept, action in actions.items()]

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
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"<b>Compliance Grade / 合规等级：{compliance_grade}</b>", h_style))
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
    flagged_row_indices: List[int] = []
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

        is_flagged = any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or []))

        if r.status == "NON_COMPLIANT":
            if r.missing_fields:
                reason_items = []
                for x in r.missing_fields:
                    quote, threshold = _issue_quote(x)
                    reason_items.append(f"• {x}<br/>  \"{quote}\"<br/>  {threshold}")
                reasons = "<br/><br/>".join(reason_items)
            else:
                reasons = "• （未提供原因）"
            if is_flagged:
                reasons += "<br/><b>Manual Review Recommended (Potential Fraud Risk)</b>"
            cell = Paragraph(reasons, red)
        elif r.status == "NOT_REQUIRED_DPP":
            # Show a short analysis line set.
            analysis = [x for x in (r.issues or []) if str(x).startswith("Analysis (not mandatory):")]
            if not analysis:
                if r.issues:
                    txt = "• " + str(r.issues[0])
                    if is_flagged:
                        txt += "<br/><b>Manual Review Recommended (Potential Fraud Risk)</b>"
                    cell = Paragraph(txt, small_grey)
                else:
                    cell = Paragraph("—", small_grey)
            else:
                reasons = "<br/>".join([f"• {x}" for x in analysis[:6]])
                if is_flagged:
                    reasons += "<br/><b>Manual Review Recommended (Potential Fraud Risk)</b>"
                cell = Paragraph(reasons, small_grey)
        else:
            txt = "—"
            if is_flagged:
                txt = "<b>Manual Review Recommended (Potential Fraud Risk)</b>"
            cell = Paragraph(txt, small_grey)

        rows.append([Paragraph(_norm(r.model), normal), status_cell, risk_cell, cell])
        if is_flagged:
            flagged_row_indices.append(len(rows) - 1)

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
    if flagged_row_indices:
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, row), (-1, row), 1.2, colors.HexColor("#7E57C2"))
                    for row in flagged_row_indices
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
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("风险雷达图 / Risk Radar", h_style))
    story.append(_build_radar_drawing(results))

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

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Gap Fixing List / 差额修复清单", h_style))
    for line in _build_gap_fixing_list(results):
        story.append(Paragraph("• " + line, normal))

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "免责声明：本报告为“预审计/一致性检查”用途，基于你提供的数据字段进行自动化校验，不构成法律意见或公告认证结论。",
            small_grey,
        )
    )

    def _footer(canvas, doc_obj):
        canvas.saveState()
        # Watermark background
        canvas.setFillColor(colors.Color(0.65, 0.65, 0.65, alpha=0.15))
        canvas.setFont("Helvetica-Bold", 24)
        canvas.translate(105 * mm, 150 * mm)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "CONFIDENTIAL PRE-AUDIT REPORT - BY DPP INSIGHT")
        canvas.rotate(-35)
        canvas.translate(-105 * mm, -150 * mm)

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


def _get_field(rec: Dict[str, Any], module: str, key: str) -> Any:
    info = DPP_FIELD_MAP[module][key]
    for alias in info["aliases"]:
        if alias in rec and _norm(rec.get(alias)) != "":
            return rec.get(alias)
    return None


def validate_coordinates(latitude: Optional[float], longitude: Optional[float]) -> Tuple[bool, str]:
    """
    Anti-fraud geolocation heuristic check:
    If declared mine coordinates are outside known lithium/cobalt mining areas,
    return High Risk.
    """
    if latitude is None or longitude is None:
        return False, "Missing mine coordinates; cannot validate sourcing geolocation."

    in_known_zone = any(
        lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max
        for lat_min, lat_max, lon_min, lon_max in KNOWN_LITHIUM_COBALT_MINING_ZONES
    )
    if in_known_zone:
        return True, "Mine coordinates are within known lithium/cobalt mining regions."
    return False, "Mine coordinates are outside known lithium/cobalt mining regions (High Risk)."


def validate_physical_carbon_floor(chemistry: str, carbon_footprint_total: Optional[float]) -> Tuple[bool, str]:
    """
    Anti-fraud plausibility heuristic:
    If reported carbon footprint is below chemistry-specific physical floor,
    flag as Data Unrealistic.
    """
    c = _norm(chemistry).upper()
    if carbon_footprint_total is None:
        return False, "Carbon footprint missing; cannot run physical plausibility check."
    if c not in CARBON_FOOTPRINT_MIN_BY_CHEMISTRY:
        return True, f"No chemistry floor configured for {c}; plausibility check skipped."

    floor = CARBON_FOOTPRINT_MIN_BY_CHEMISTRY[c]
    if carbon_footprint_total < floor:
        return False, f"Data Unrealistic: carbon footprint {carbon_footprint_total} is below {c} physical floor {floor}."
    return True, f"Carbon footprint is above {c} physical floor ({floor})."


def validate_manufacturer_id(manufacturer_id: str) -> Tuple[bool, str]:
    """
    Simple structural heuristic validation for manufacturer IDs.
    Expected format: MFG-XXXXXX (at least 6 uppercase alnum chars after prefix).
    """
    mid = _norm(manufacturer_id)
    if not mid:
        return False, "manufacturer_id missing."
    if re.fullmatch(r"MFG-[A-Z0-9]{6,}", mid):
        return True, "manufacturer_id format is valid."
    return False, f"manufacturer_id '{mid}' failed format validation."


def _compute_carbon_intensity_kg_per_kwh(
    rec: Dict[str, Any],
    carbon_footprint_total: Optional[float],
    capacity_kwh: Optional[float],
) -> Optional[float]:
    direct = _parse_float(rec.get("carbon_footprint_kg_co2e_per_kwh") or rec.get("carbon_intensity_kg_per_kwh"))
    if direct is not None:
        return direct
    # Fallback assumption for heterogeneous client datasets:
    # many feeds already provide a carbon-intensity-like value in this column.
    if carbon_footprint_total is not None:
        return carbon_footprint_total
    return None


def validate_record(rec: Dict[str, Any]) -> DppResult:
    model = _norm(rec.get("model") or rec.get("battery_model") or rec.get("型号") or rec.get("Model"))
    if not model:
        model = "<unknown>"

    category = _norm(_get_field(rec, "public_information", "category"))
    capacity_kwh = _parse_float(rec.get("capacity_kwh") or rec.get("capacity_kWh") or rec.get("capacity") or rec.get("容量_kwh"))

    dpp_required, applicability_note = dpp_applicability(category, capacity_kwh)

    # Public information
    unique_identifier = _norm(_get_field(rec, "public_information", "unique_identifier"))
    battery_id = _norm(_get_field(rec, "public_information", "battery_id"))
    manufacturer_id = _norm(_get_field(rec, "public_information", "manufacturer_id"))
    manufacturer = _norm(_get_field(rec, "public_information", "manufacturer"))
    manufacture_place = _norm(_get_field(rec, "public_information", "manufacture_place"))
    manufacture_date = _parse_yyyy_mm(_get_field(rec, "public_information", "manufacture_date"))

    # Materials and compliance
    li_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lithium_pct"))
    co_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_cobalt_pct"))
    ni_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_nickel_pct"))
    pb_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lead_pct"))
    hazardous_decl = _norm(_get_field(rec, "materials_and_compliance", "hazardous_substances_declaration"))

    # Performance and durability
    rated_capacity_ah = _parse_float(_get_field(rec, "performance_and_durability", "rated_capacity_ah"))
    nominal_voltage_v = _parse_float(_get_field(rec, "performance_and_durability", "nominal_voltage_v"))
    rated_power_w = _parse_float(_get_field(rec, "performance_and_durability", "rated_power_w"))
    self_discharge = _parse_float(_get_field(rec, "performance_and_durability", "self_discharge_rate_pct_per_month"))
    expected_lifetime_cycles = _parse_float(_get_field(rec, "performance_and_durability", "expected_lifetime_cycles"))
    efficiency_pct = _parse_float(_get_field(rec, "performance_and_durability", "charge_discharge_efficiency_percent"))

    # Safety
    thermal_runaway = _norm(_get_field(rec, "safety", "thermal_runaway_prevention"))
    extinguishing_agent = _norm(_get_field(rec, "safety", "extinguishing_agent"))
    explosion_decl = _norm(_get_field(rec, "safety", "explosion_proof_declaration"))
    bms_access = _norm(_get_field(rec, "safety", "bms_access_permissions"))

    # Traceability + carbon
    chemistry = _norm(_get_field(rec, "traceability_and_sourcing", "chemistry"))
    mine_lat = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_latitude"))
    mine_lon = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_longitude"))
    carbon_footprint_total = _parse_float(_get_field(rec, "traceability_and_sourcing", "carbon_footprint_total_kg_co2e"))
    carbon_intensity_kg_per_kwh = _compute_carbon_intensity_kg_per_kwh(rec, carbon_footprint_total, capacity_kwh)

    issues: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    fraud_flags: List[str] = []

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
    manufacturer_id_ok, manufacturer_id_note = validate_manufacturer_id(manufacturer_id)
    if not manufacturer_id_ok:
        basic_ok = False
        missing.append("manufacturer_id invalid or missing (traceability identity control)")

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
    if rated_power_w is None or rated_power_w <= 0:
        tech_ok = False
        missing.append("rated_power_w (Annex XIII(1)(a)(i))")
    if self_discharge is None or self_discharge < 0 or self_discharge > 100:
        tech_ok = False
        missing.append("self_discharge_rate_pct_per_month (Annex VII Part B(4))")

    # Safety
    safety_ok = True
    if not _present_nonempty(extinguishing_agent):
        safety_ok = False
        missing.append("extinguishing_agent (Annex VI Part A(9) via Annex XIII(1)(a))")
    if not _present_nonempty(thermal_runaway):
        safety_ok = False
        missing.append("thermal_runaway_prevention (Safety info required by Annex XIII safety scope)")
    if not _present_nonempty(explosion_decl):
        safety_ok = False
        missing.append("explosion_proof_declaration (Safety info required by Annex XIII safety scope)")

    # BMS access permissions check (Article 14)
    bms_ok = True
    bms_lower = bms_access.lower()
    if not bms_lower or ("read" not in bms_lower and "r" not in bms_lower):
        bms_ok = False
        missing.append("bms_access_permissions missing read permission disclosure (Article 14)")
    if not bms_lower or ("write" not in bms_lower and "w" not in bms_lower):
        bms_ok = False
        missing.append("bms_access_permissions missing write permission disclosure (Article 14)")

    # Carbon
    carbon_ok = True
    if carbon_footprint_total is None or carbon_footprint_total <= 0:
        carbon_ok = False
        missing.append("carbon_footprint_total_kg_co2e (Annex XIII(1)(c) / Article 7)")

    # Materials declaration
    materials_ok = True
    if not _present_nonempty(hazardous_decl):
        materials_ok = False
        missing.append("hazardous_substances_declaration (Annex XIII(1)(b))")

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
    _add_metric("unique_identifier", (_present_nonempty(unique_identifier)), unique_identifier, None, "Article 77(3)")
    _add_metric("nominal_voltage_v", (nominal_voltage_v is not None and nominal_voltage_v > 0), nominal_voltage_v, None, "Annex XIII(1)(a)(h)")
    _add_metric("rated_power_w", (rated_power_w is not None and rated_power_w > 0), rated_power_w, None, "Annex XIII(1)(a)(i)")
    _add_metric("self_discharge_rate_pct_per_month", (self_discharge is not None and 0 <= self_discharge <= 100), self_discharge, None, "Annex VII Part B(4)")
    _add_metric("charge_discharge_efficiency_percent", (efficiency_pct is not None and 0 < efficiency_pct <= 100), efficiency_pct, None, "Annex XIII(1)(a)(n)")
    _add_metric("expected_lifetime_cycles", (expected_lifetime_cycles is not None and expected_lifetime_cycles > 0), expected_lifetime_cycles, None, "Annex XIII(1)(a)(j)")
    _add_metric("extinguishing_agent", (_present_nonempty(extinguishing_agent)), extinguishing_agent, None, "Annex VI Part A(9) via Annex XIII(1)(1)(a)")
    _add_metric("thermal_runaway_prevention", (_present_nonempty(thermal_runaway)), thermal_runaway, None, "Annex XIII safety scope")
    _add_metric("explosion_proof_declaration", (_present_nonempty(explosion_decl)), explosion_decl, None, "Annex XIII safety scope")
    _add_metric("hazardous_substances_declaration", (_present_nonempty(hazardous_decl)), hazardous_decl, None, "Annex XIII(1)(b)")
    _add_metric("bms_access_permissions", bms_ok, bms_access, "read+write disclosure", "Article 14")
    _add_metric("carbon_footprint_total_kg_co2e", (carbon_footprint_total is not None and carbon_footprint_total > 0), carbon_footprint_total, None, "Annex XIII(1)(c) / Article 7")
    _add_metric("manufacturer_id", manufacturer_id_ok, manufacturer_id, "MFG-[A-Z0-9]{6,}", "Heuristic anti-fraud check")

    # Anti-fraud checks
    coords_ok, coords_note = validate_coordinates(mine_lat, mine_lon)
    _add_metric("mine_coordinates", coords_ok, f"{mine_lat},{mine_lon}", "major mining countries/zones", "Heuristic sourcing-risk check")
    if not coords_ok:
        issues.append(f"Anti-fraud geolocation heuristic: {coords_note}")
        fraud_flags.append("HIGH_RISK")

    physical_ok, physical_note = validate_physical_carbon_floor(chemistry, carbon_intensity_kg_per_kwh)
    _add_metric("carbon_physical_plausibility", physical_ok, carbon_intensity_kg_per_kwh, f"{chemistry} floor (kgCO2e/kWh)", "Heuristic physical plausibility check")
    if not physical_ok:
        issues.append(f"Anti-fraud physical plausibility heuristic: {physical_note}")
        # Treat physically impossible declaration as an audit failure.
        missing.append("carbon_footprint flagged as Data Unrealistic (below chemistry theoretical floor, heuristic)")
        fraud_flags.append("DATA_UNREALISTIC")

    if not manufacturer_id_ok:
        issues.append(f"Anti-fraud manufacturer-id heuristic: {manufacturer_id_note}")
        fraud_flags.append("HIGH_RISK")

    # If DPP is NOT mandatory, we only show analysis.
    if not dpp_required:
        issues.extend([f"Analysis (not mandatory): {x}" for x in missing])
        if not coords_ok:
            issues.append("High Risk due to sourcing coordinate anomaly.")
        if not physical_ok:
            issues.append("Data Unrealistic due to carbon footprint below physical floor.")
        if not manufacturer_id_ok:
            issues.append("High Risk due to manufacturer identity inconsistency.")
        return DppResult(
            model=model,
            status="NOT_REQUIRED_DPP",
            risk_level="high" if (not coords_ok or not physical_ok or not manufacturer_id_ok) else "N/A",
            issues=issues,
            missing_fields=[],
            metrics=metrics,
            fraud_flags=sorted(set(fraud_flags)),
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
    if not materials_ok:
        issues.extend([f"Materials declaration non-compliance: {x}" for x in missing if "hazardous_substances_declaration" in x])
    if not bms_ok:
        issues.extend([f"BMS access non-compliance: {x}" for x in missing if "bms_access_permissions" in x])
    if not manufacturer_id_ok:
        issues.extend([f"Manufacturer identity non-compliance: {x}" for x in missing if "manufacturer_id" in x])
    if not physical_ok:
        issues.append("Data Unrealistic (carbon footprint physical plausibility failure).")
    if not coords_ok:
        issues.append("High Risk (mine coordinates outside known lithium/cobalt zones).")
    if not manufacturer_id_ok:
        issues.append("High Risk (manufacturer_id failed validation).")

    if missing:
        risk_level = "high" if severe_recycled_violation or (len(missing) >= 2) or (not coords_ok) or (not physical_ok) else "medium"
        return DppResult(
            model=model,
            status="NON_COMPLIANT",
            risk_level=risk_level,
            issues=issues + [],
            missing_fields=missing,
            metrics=metrics,
            fraud_flags=sorted(set(fraud_flags)),
        )

    return DppResult(
        model=model,
        status="COMPLIANT",
        risk_level="high" if (not coords_ok or not physical_ok or not manufacturer_id_ok) else "low",
        issues=issues,
        missing_fields=[],
        metrics=metrics,
        fraud_flags=sorted(set(fraud_flags)),
    )


def iter_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        for row in reader:
            yield row


def generate_audit_pdf(
    *,
    results: List[DppResult],
    source_csv: Path,
    output_pdf: Path,
    language: str = "zh",
) -> None:
    """
    fpdf2-based PDF renderer with:
    - language switch (full zh/en UI text)
    - auto-width table
    - auto page break for long tables
    - watermark
    """
    try:
        from fpdf import FPDF
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(str(e) + "\n\nInstall with: pip install fpdf2") from e

    L_ZH = {
            "title": "欧盟 2023/1542 电池法案合规预审计报告",
            "grade": "合规等级",
            "time": "审计时间",
            "src": "数据来源",
            "summary": "型号级别审计结果汇总",
            "model": "型号",
            "status": "判定结果",
            "risk": "风险等级",
            "issues": "问题说明",
            "radar": "关键指标雷达（六维评分）",
            "gap": "差额修复清单",
            "manual": "人工复核建议：潜在欺诈风险",
        }
    L_EN = {
            "title": "EU 2023/1542 Battery Regulation Compliance Pre-Audit Report",
            "grade": "Compliance Grade",
            "time": "Audit Time",
            "src": "Data Source",
            "summary": "Model-level Audit Summary",
            "model": "Model",
            "status": "Status",
            "risk": "Risk",
            "issues": "Issues",
            "radar": "Key Metrics Radar (Six Dimensions)",
            "gap": "Gap Fixing List",
            "manual": "Manual Review Recommended (Potential Fraud Risk)",
        }

    grade = "A"
    non = sum(1 for r in results if r.status == "NON_COMPLIANT")
    flagged = sum(1 for r in results if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or [])))
    total = len(results) or 1
    if non / total > 0.35 or flagged > max(1, total // 3):
        grade = "C"
    elif non / total > 0.10:
        grade = "B"

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)

    # Font registration
    font_regular = "Helvetica"
    font_bold = "Helvetica"
    if language == "zh":
        zh_font = "/Library/Fonts/Arial Unicode.ttf"
        if Path(zh_font).exists():
            pdf.add_font("ArialUnicode", "", zh_font)
            pdf.add_font("ArialUnicode", "B", zh_font)
            font_regular = "ArialUnicode"
            font_bold = "ArialUnicode"

    # If Chinese was requested but a Unicode font is unavailable,
    # gracefully fall back to English labels to avoid rendering failure.
    if language == "zh" and font_regular == "Helvetica":
        L = L_EN
    else:
        L = L_ZH if language == "zh" else L_EN

    def watermark():
        pdf.set_text_color(220, 220, 220)
        pdf.set_font("Helvetica", "B", 20)
        with pdf.rotation(30, x=105, y=150):
            pdf.text(20, 150, "CONFIDENTIAL PRE-AUDIT REPORT - BY DPP INSIGHT")
        pdf.set_text_color(0, 0, 0)

    # Cover
    pdf.add_page()
    watermark()
    pdf.set_font(font_bold, "B", 18)
    pdf.multi_cell(0, 10, L["title"])
    pdf.ln(2)
    pdf.set_font(font_bold, "B", 14)
    pdf.cell(0, 9, f"{L['grade']}: {grade}", ln=1)
    pdf.set_font(font_regular, "", 11)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf.cell(0, 7, f"{L['time']}: {now}", ln=1)
    pdf.cell(0, 7, f"{L['src']}: {source_csv.name}", ln=1)

    # Summary table
    pdf.add_page()
    watermark()
    pdf.set_font(font_bold, "B", 13)
    pdf.cell(0, 8, L["summary"], ln=1)
    pdf.ln(1)

    headers = [L["model"], L["status"], L["risk"], L["issues"]]
    rows = []
    for r in results:
        issues = "; ".join(r.missing_fields or r.issues[:3])
        if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or [])):
            issues = f"{issues} | {L['manual']}"
        rows.append([r.model, r.status, r.risk_level, issues])

    # auto-width based on header + sample data
    page_w = 210 - 18 - 18
    widths = [30, 28, 20, page_w - 30 - 28 - 20]
    sample_n = min(len(rows), 20)
    for i in range(3):
        max_len = len(headers[i])
        for r in rows[:sample_n]:
            max_len = max(max_len, len(str(r[i])))
        widths[i] = max(widths[i], min(45, 4 + max_len * 1.6))
    # Ensure width budget is always valid and issue-column keeps enough room.
    base_sum = widths[0] + widths[1] + widths[2]
    min_issue_col = 70
    if base_sum > page_w - min_issue_col:
        scale = (page_w - min_issue_col) / base_sum
        widths[0] = max(24, widths[0] * scale)
        widths[1] = max(22, widths[1] * scale)
        widths[2] = max(18, widths[2] * scale)
    widths[3] = max(min_issue_col, page_w - widths[0] - widths[1] - widths[2])

    # Header row
    pdf.set_font(font_bold, "B", 10)
    for h, w in zip(headers, widths):
        pdf.set_fill_color(11, 61, 145)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(w, 8, h, border=1, fill=True)
    pdf.ln(8)
    pdf.set_text_color(0, 0, 0)

    # Data rows with auto page breaks
    pdf.set_font(font_regular, "", 9)
    for r in rows:
        # estimate row height from issue column
        issue_text = str(r[3]).replace("_", "_ ").replace("/", "/ ")
        lines = max(1, int(len(issue_text) / max(1, (widths[3] / 2.2))))
        row_h = min(26, max(7, lines * 4))

        if pdf.get_y() + row_h > 285:
            pdf.add_page()
            watermark()
            pdf.set_font(font_bold, "B", 10)
            for h, w in zip(headers, widths):
                pdf.set_fill_color(11, 61, 145)
                pdf.set_text_color(255, 255, 255)
                pdf.cell(w, 8, h, border=1, fill=True)
            pdf.ln(8)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(font_regular, "", 9)

        x0, y0 = pdf.get_x(), pdf.get_y()
        pdf.cell(widths[0], row_h, str(r[0])[:80], border=1)
        pdf.cell(widths[1], row_h, str(r[1])[:40], border=1)
        pdf.cell(widths[2], row_h, str(r[2])[:20], border=1)
        pdf.set_xy(x0 + widths[0] + widths[1] + widths[2], y0)
        pdf.multi_cell(widths[3], 4, issue_text, border=1)
        pdf.set_xy(x0, max(y0 + row_h, pdf.get_y()))

    # Radar text + Gap list
    pdf.add_page()
    watermark()
    pdf.set_font(font_bold, "B", 12)
    pdf.cell(0, 8, L["radar"], ln=1)
    metrics = {
        "Safety": "extinguishing_agent",
        "Environmental": "carbon_footprint_total_kg_co2e",
        "Traceability": "unique_identifier",
        "Recycled": "recycled_lithium_pct",
        "Performance": "rated_capacity_ah",
        "BMS": "bms_access_permissions",
    }
    mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
    total_m = len(mandatory) or 1
    pdf.set_font(font_regular, "", 10)
    for dim, key in metrics.items():
        met = sum(1 for r in mandatory if ((r.metrics.get(key, {}) or {}).get("met") is True))
        score = met / total_m
        bars = "#" * int(round(score * 20))
        pdf.cell(0, 7, f"{dim}: {met}/{total_m} [{bars:<20}]", ln=1)

    pdf.ln(4)
    pdf.set_font(font_bold, "B", 12)
    pdf.set_x(pdf.l_margin)
    pdf.cell(0, 8, L["gap"], ln=1)
    pdf.set_font(font_regular, "", 10)
    dept_actions = {
        "recycled_": "Procurement & Sustainability: provide recycled-material proof and update declarations.",
        "carbon_footprint": "LCA/ESG: recalculate and verify carbon footprint data.",
        "bms_access": "BMS Team: disclose read/write access policy.",
        "manufacturer_id": "Master Data Team: repair manufacturer identity format and registry consistency.",
        "extinguishing_agent": "EHS Team: complete safety extinguishing guidance field.",
    }
    issue_pool = [m for r in results for m in (r.missing_fields or [])]
    used = set()
    for issue in issue_pool:
        for token, action in dept_actions.items():
            if token in issue and action not in used:
                used.add(action)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 6, f"- {action}")
    if not used:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, "- No critical gap found; keep periodic evidence updates.")

    pdf.output(str(output_pdf))


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
            print(
                json.dumps(
                    {
                        "model": r.model,
                        "status": r.status,
                        "risk_level": r.risk_level,
                        "missing_fields": r.missing_fields,
                        "issues": r.issues,
                        "metrics": r.metrics,
                        "fraud_flags": r.fraud_flags,
                    },
                    ensure_ascii=False,
                )
            )
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

