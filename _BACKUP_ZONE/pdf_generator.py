"""pdf_generator.py — PDF report generation for DPP Expert 3.0.

Single responsibility: build and return PDF bytes for an audit run.

Font policy
-----------
Only NotoSansSC-Regular.otf is used (project root, auto-downloaded if absent).
No system fonts (Arial/STHeiti/PingFang) — those embed inconsistently and
appear garbled in browser PDF viewers.

Public API
----------
  create_pdf_instance() -> FPDF
      Returns an FPDF object with NotoSans already registered and set as default.

  generate_audit_pdf(results, language, report_no, client_name, project_code) -> bytes
      Builds a full audit report PDF and returns raw bytes.
"""
from __future__ import annotations

import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import FONT_FILE, FONT_URLS
from dpp_engine import DppResult
from translations import PDF_LABELS_EN, PDF_LABELS_ZH

# ── Font paths ────────────────────────────────────────────────────────────────
_FONT_DIR  = Path(__file__).resolve().parent
_FONT_PATH = _FONT_DIR / FONT_FILE
_FONT_FAMILY = "NotoSans"   # fpdf2 registered family name


def _ensure_font() -> Path:
    """Return path to NotoSansSC-Regular.otf, downloading it if needed.

    Raises RuntimeError if the font cannot be obtained.
    """
    if _FONT_PATH.exists() and _FONT_PATH.stat().st_size > 1_000_000:
        print(f"[PDF] Font OK: {_FONT_PATH.name} ({_FONT_PATH.stat().st_size // 1024} KB)",
              file=sys.stderr)
        return _FONT_PATH

    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _FONT_PATH.with_suffix(".tmp")
    for url in FONT_URLS:
        try:
            print(f"[PDF] Downloading font: {url}", file=sys.stderr)
            urllib.request.urlretrieve(url, str(tmp))
            if tmp.exists() and tmp.stat().st_size > 1_000_000:
                tmp.rename(_FONT_PATH)
                print(f"[PDF] Font saved: {_FONT_PATH.name} "
                      f"({_FONT_PATH.stat().st_size // 1024} KB)", file=sys.stderr)
                return _FONT_PATH
            if tmp.exists():
                tmp.unlink()
        except Exception as exc:
            print(f"[PDF] Download failed ({url}): {exc}", file=sys.stderr)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    raise RuntimeError(
        f"无法获取字体文件 {FONT_FILE}。\n\n"
        "• 请将 NotoSansSC-Regular.otf（约 8 MB）放到项目根目录，或\n"
        "• 确保网络畅通以自动下载。\n\n"
        f"Cannot obtain font {FONT_FILE}. Place the file (~8 MB) in the project root "
        "or ensure internet access for auto-download."
    )


def create_pdf_instance():
    """Create an FPDF instance with NotoSans registered and set as default font.

    This is the single place where add_font is called.
    All subsequent set_font calls use _FONT_FAMILY constant.
    """
    try:
        from fpdf import FPDF
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            str(exc) + "\n\nInstall with: pip install fpdf2"
        ) from exc

    font_path = _ensure_font()

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(left=18, top=15, right=18)

    try:
        pdf.add_font(_FONT_FAMILY, style="",  fname=str(font_path))
        pdf.add_font(_FONT_FAMILY, style="B", fname=str(font_path))
    except Exception as exc:
        raise RuntimeError(
            f"字体文件加载失败 ({font_path.name}): {exc}\n"
            "Font failed to load — verify the file is a valid OTF/TTF."
        ) from exc

    pdf.set_font(_FONT_FAMILY, size=10)
    return pdf


# ── PDF report builder ────────────────────────────────────────────────────────

def generate_audit_pdf(
    results: List[DppResult],
    language: str = "zh",
    report_no: str = "",
    client_name: str = "",
    project_code: str = "",
) -> bytes:
    """Build a full-featured audit PDF and return raw bytes.

    Parameters
    ----------
    results      : audit results from dpp_engine.validate_record()
    language     : "zh" (default) or "en"
    report_no    : printed on cover page
    client_name  : printed on cover page
    project_code : printed on cover page
    """
    from fpdf.enums import XPos, YPos

    language     = language     or "zh"
    report_no    = report_no    or ""
    client_name  = client_name  or ""
    project_code = project_code or ""

    L: Dict[str, str] = PDF_LABELS_ZH if language == "zh" else PDF_LABELS_EN

    # ── Compliance grade ──────────────────────────────────────────────────────
    total_cnt = len(results) or 1
    non_cnt   = sum(1 for r in results if r.status == "NON_COMPLIANT")
    flag_cnt  = sum(
        1 for r in results
        if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or []))
    )
    if non_cnt / total_cnt > 0.35 or flag_cnt > max(1, total_cnt // 3):
        grade = "C"
    elif non_cnt / total_cnt > 0.10 or flag_cnt > 0:
        grade = "B"
    else:
        grade = "A"

    pdf = create_pdf_instance()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _watermark() -> None:
        pdf.set_text_color(210, 210, 210)
        pdf.set_font(_FONT_FAMILY, "", 18)
        with pdf.rotation(32, x=105, y=148):
            pdf.text(15, 148, L["watermark"])
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(_FONT_FAMILY, "", 10)

    def _cell(w: float, h: float, txt: str, **kw) -> None:
        pdf.cell(w, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT, **kw)

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    pdf.ln(18)
    pdf.set_font(_FONT_FAMILY, "B", 20)
    pdf.set_text_color(11, 61, 145)
    pdf.multi_cell(0, 11, L["title"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(3)
    pdf.set_font(_FONT_FAMILY, "", 11)
    pdf.multi_cell(0, 7, L["sub"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

    pdf.ln(8)
    pdf.set_draw_color(11, 61, 145)
    pdf.set_line_width(0.8)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(8)

    grade_color = {"A": (27, 94, 32), "B": (230, 126, 34), "C": (176, 0, 32)}.get(grade, (0, 0, 0))
    pdf.set_font(_FONT_FAMILY, "B", 28)
    pdf.set_text_color(*grade_color)
    pdf.multi_cell(0, 14, f"{L['grade']}: {grade}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    now_str   = datetime.now().strftime("%Y-%m-%d  %H:%M")
    meta_rows = [(L["time"], now_str)]
    if client_name:  meta_rows.insert(0, (L["client"], client_name))
    if project_code: meta_rows.insert(1, (L["proj"],   project_code))
    if report_no:    meta_rows.insert(2, (L["rptno"],  report_no))

    for label, val in meta_rows:
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.cell(42, 7, f"{label}:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font(_FONT_FAMILY, "", 10)
        _cell(0, 7, val)

    pdf.ln(6)
    pdf.set_font(_FONT_FAMILY, "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 5, L["scope"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 2+ — AUDIT RESULTS TABLE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    pdf.set_font(_FONT_FAMILY, "B", 13)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["summary"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)

    def _status_label(status: str) -> str:
        return L.get(
            {"COMPLIANT": "compliant", "NON_COMPLIANT": "non_compliant"}.get(status, "not_required"),
            status,
        )

    # Build rows: one bullet per issue line
    rows_data = []
    for r in results:
        items: list = list(r.missing_fields) if r.missing_fields else list(r.issues or [])
        if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or [])):
            items.append(f"[{L['manual']}]: {', '.join(r.fraud_flags)}")
        issue_txt = "\n".join(f"• {x}" for x in items) if items else "-"
        rows_data.append([str(r.model)[:60], _status_label(r.status), str(r.risk_level), issue_txt])

    # Column widths
    page_w   = 210 - 18 - 18
    min_issue = 68
    w0, w1, w2 = 34, 30, 20
    for i, (base_w, col_idx) in enumerate([(w0, 0), (w1, 1), (w2, 2)]):
        max_len = max((len(rows_data[j][col_idx]) for j in range(min(len(rows_data), 20))), default=0) if rows_data else 0
        computed = min(base_w + 10, 4 + max_len * 1.8)
        if i == 0:   w0 = max(base_w, computed)
        elif i == 1: w1 = max(base_w, computed)
        else:        w2 = max(base_w, computed)
    base_sum = w0 + w1 + w2
    if base_sum > page_w - min_issue:
        scale = (page_w - min_issue) / base_sum
        w0 = max(24, w0 * scale); w1 = max(22, w1 * scale); w2 = max(16, w2 * scale)
    w3 = max(min_issue, page_w - w0 - w1 - w2)
    col_widths = [w0, w1, w2, w3]
    headers    = [L["model"], L["status"], L["risk"], L["issues"]]

    def _draw_header() -> None:
        pdf.set_font(_FONT_FAMILY, "B", 9)
        pdf.set_fill_color(11, 61, 145)
        pdf.set_text_color(255, 255, 255)
        for h, cw in zip(headers, col_widths):
            pdf.cell(cw, 8, h[:40], border=1, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(8)
        pdf.set_text_color(0, 0, 0)

    _draw_header()

    LINE_H = 4.2

    def _count_lines(text: str, col_w: float, font_size: int = 8) -> int:
        char_w = font_size * 0.45
        chars_per_line = max(1, int(col_w / char_w))
        return sum(max(1, -(-len(para) // chars_per_line)) for para in text.split("\n"))

    def _draw_row(ri: int, row: list, result: DppResult) -> None:
        issue_text = str(row[3])
        n_lines = max(
            _count_lines(str(row[0]), w0), _count_lines(str(row[1]), w1),
            _count_lines(str(row[2]), w2), _count_lines(issue_text, w3),
        )
        row_h = max(7.0, min(40.0, n_lines * LINE_H + 2))

        if pdf.get_y() + row_h > 283:
            pdf.add_page()
            _watermark()
            _draw_header()

        x0, y0 = pdf.l_margin, pdf.get_y()
        fill_rgb = (243, 244, 246) if ri % 2 == 0 else (255, 255, 255)
        pad = 1.0

        pdf.set_draw_color(180, 180, 180)
        pdf.set_line_width(0.2)
        x = x0
        for cw in col_widths:
            pdf.set_fill_color(*fill_rgb)
            pdf.rect(x, y0, cw, row_h, style="FD")
            x += cw

        pdf.set_font(_FONT_FAMILY, "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(x0 + pad, y0 + 1)
        pdf.multi_cell(w0 - pad, LINE_H, str(row[0])[:60], border=0, fill=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        if result.status == "COMPLIANT":
            pdf.set_text_color(27, 94, 32);  pdf.set_font(_FONT_FAMILY, "B", 8)
        elif result.status == "NON_COMPLIANT":
            pdf.set_text_color(176, 0, 32);  pdf.set_font(_FONT_FAMILY, "B", 8)
        else:
            pdf.set_text_color(80, 80, 80);  pdf.set_font(_FONT_FAMILY, "", 8)
        pdf.set_xy(x0 + w0 + pad, y0 + 1)
        pdf.multi_cell(w1 - pad, LINE_H, str(row[1])[:40], border=0, fill=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_text_color(0, 0, 0); pdf.set_font(_FONT_FAMILY, "", 8)
        pdf.set_xy(x0 + w0 + w1 + pad, y0 + 1)
        pdf.multi_cell(w2 - pad, LINE_H, str(row[2])[:20], border=0, fill=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_text_color(60, 60, 60); pdf.set_font(_FONT_FAMILY, "", 7.5)
        pdf.set_xy(x0 + w0 + w1 + w2 + pad, y0 + 1)
        try:
            pdf.multi_cell(w3 - pad, LINE_H, issue_text, border=0, fill=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pdf.multi_cell(w3 - pad, LINE_H, issue_text[:300], border=0, fill=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(x0, y0 + row_h)

    for ri, row in enumerate(rows_data):
        _draw_row(ri, row, results[ri])

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE — RADAR + GAP LIST + RECOMMENDATIONS
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    pdf.set_font(_FONT_FAMILY, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["radar"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)

    dim_keys = {
        "Safety":       ["extinguishing_agent", "thermal_runaway_prevention", "explosion_proof_declaration"],
        "Environmental":["carbon_footprint_total_kg_co2e", "carbon_physical_plausibility"],
        "Traceability": ["unique_identifier", "manufacturer_id", "mine_coordinates"],
        "Recycled":     ["recycled_lithium_pct", "recycled_cobalt_pct", "recycled_nickel_pct", "recycled_lead_pct"],
        "Performance":  ["rated_capacity_ah", "nominal_voltage_v", "rated_power_w", "expected_lifetime_cycles"],
        "BMS Access":   ["bms_access_permissions"],
    }
    mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
    total_m   = len(mandatory) or 1
    pdf.set_font(_FONT_FAMILY, "", 10)
    for dim, keys in dim_keys.items():
        met   = sum(1 for r in mandatory if all(((r.metrics.get(k, {}) or {}).get("met") is True) for k in keys))
        score = met / total_m
        bar   = "#" * int(round(score * 20)) + "." * (20 - int(round(score * 20)))
        try:
            _cell(0, 6, f"  {dim:<16}  [{bar}]  {score:.0%}  ({met}/{total_m})")
        except Exception:
            _cell(0, 6, f"  {dim}:  {score:.0%}  ({met}/{total_m})")

    pdf.ln(5)

    # Gap Fixing List
    pdf.set_font(_FONT_FAMILY, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["gap"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font(_FONT_FAMILY, "", 10)

    dept_map = [
        ("recycled_",         "Procurement & Sustainability",
         "Collect recycled-material certificates and update recycled-content declarations."),
        ("carbon_footprint",  "LCA / ESG Team",
         "Recalculate lifecycle carbon footprint and provide audited methodology evidence."),
        ("bms_access",        "BMS Firmware & Diagnostics",
         "Publish read/write access policy and technical interface control note."),
        ("extinguishing_agent","EHS & Product Safety",
         "Provide extinguishing-agent specification and hazard response instructions."),
        ("manufacturer_id",   "Master Data Governance",
         "Fix manufacturer identity schema and traceability key integrity."),
        ("hazardous_substances","Compliance Documentation",
         "Complete hazardous-substance declaration linked to BOM/SDS records."),
        ("rated_capacity",    "R&D Validation",
         "Provide validated electrochemical performance measurements."),
    ]
    issue_pool   = [m for r in results for m in (r.missing_fields or [])]
    used_actions: set = set()
    for issue in issue_pool:
        for token, dept, action in dept_map:
            if token in issue and action not in used_actions:
                used_actions.add(action)
                try:
                    pdf.multi_cell(0, 5, f"  [{dept}] {action}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                except Exception:
                    pdf.multi_cell(0, 5, f"  {action}"[:200], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if not used_actions:
        pdf.multi_cell(0, 5, f"  {L['no_gap']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(5)

    # Recommendations + disclaimer
    pdf.set_font(_FONT_FAMILY, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["rec_title"])
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(_FONT_FAMILY, "", 10)
    pdf.ln(1)
    pdf.multi_cell(0, 5, L["rec_body"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(6)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, L["disclaimer"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())
