"""app.py — Streamlit UI for DPP Expert 3.0.

Single responsibility: page layout and user interaction.
Business logic lives in dpp_engine.py, PDF generation in pdf_generator.py,
constants in config.py, and all text in translations.py.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import os
import time
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from config import APP_CSS, LEGAL_CITATIONS, RECYCLED_MIN_PCT
from dpp_engine import validate_record
from pdf_generator import generate_audit_pdf
from translations import TRANSLATIONS

# ── Home-dir redirect (Streamlit Cloud compatibility) ────────────────────────
_PROJECT_HOME = Path(__file__).resolve().parent / ".streamlit_home"
try:
    _marker = Path.home() / ".streamlit" / ".write_test"
    _marker.parent.mkdir(parents=True, exist_ok=True)
    _marker.write_text("ok", encoding="utf-8")
    _marker.unlink(missing_ok=True)
except Exception:
    _PROJECT_HOME.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(_PROJECT_HOME)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _parse_csv_bytes(csv_bytes: bytes) -> List[Dict[str, str]]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(StringIO(text)))


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DPP Expert 3.0",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(APP_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='text-align:center;padding:0.8rem 0 0.5rem;'>"
        "<span style='color:#64FFDA;font-size:1.5rem;font-weight:800;letter-spacing:0.05em;'>⚡ DPP Expert</span>"
        "<br><span style='color:#8892B0;font-size:0.72rem;'>EU 2023/1542 · v3.0</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    lang_pick = st.selectbox(
        "Language / 语言",
        [TRANSLATIONS["zh"]["lang_zh"], TRANSLATIONS["en"]["lang_en"]],
        index=0,
    )
    lang: str = "zh" if lang_pick == TRANSLATIONS["zh"]["lang_zh"] else "en"
    t: Dict[str, Any] = TRANSLATIONS[lang]

    st.divider()
    client_name  = (st.text_input(t["client_name"],  value="Demo Client")    or "Demo Client").strip()
    project_code = (st.text_input(t["project_code"], value="DPP-2026-PRE")   or "DPP-2026-PRE").strip()
    report_no    = f"{project_code}-{_hash_bytes((client_name + project_code).encode())[:8].upper()}"
    st.caption(f"{t['report_no']}: `{report_no}`")

    st.divider()
    uploaded_file  = st.file_uploader(t["upload_csv"], type=["csv"])
    only_suspicious = st.toggle(t["filter_fraud"], value=False)
    fraud_filter    = st.selectbox(t["anomaly_filter"], [t["af_all"], t["af_high"], t["af_unreal"]], index=0)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_dash, tab_audit, tab_map, tab_law, tab_about = st.tabs(
    [t["tab_dash"], t["tab_audit"], t["tab_map"], t["tab_law"], t["tab_about"]]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown(
        f"<div class='welcome-banner'><h1>{t['dash_welcome']}</h1><p>{t['dash_sub']}</p></div>",
        unsafe_allow_html=True,
    )

    results_cached = st.session_state.get("audit_results")

    if results_cached:
        import plotly.graph_objects as go

        results = results_cached
        compliant    = sum(1 for r in results if r.status == "COMPLIANT")
        non          = sum(1 for r in results if r.status == "NON_COMPLIANT")
        total_req    = compliant + non
        comp_rate    = compliant / total_req if total_req else 0

        carbon_vals  = [
            (r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value")
            for r in results
        ]
        carbon_vals  = [v for v in carbon_vals if isinstance(v, (int, float))]
        avg_carbon   = sum(carbon_vals) / len(carbon_vals) if carbon_vals else 0.0
        high_risk    = sum(1 for r in results if "HIGH_RISK" in (r.fraud_flags or []))

        def _has_field(r, key: str) -> bool:
            return (r.metrics.get(key, {}) or {}).get("met") is True

        trans_scores = [
            sum(1 for k in ["unique_identifier", "carbon_footprint_total_kg_co2e", "mine_coordinates"]
                if _has_field(r, k)) / 3
            for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}
        ]
        transparency = sum(trans_scores) / len(trans_scores) if trans_scores else 0

        c1, c2, c3, c4 = st.columns(4)
        for col, label, value, delta in [
            (c1, t["dash_kpi1"], f"{comp_rate:.1%}",   "vs EU 2027 mandatory threshold"),
            (c2, t["dash_kpi2"], f"{avg_carbon:.0f}",  "EU benchmark ≈ 100 kg CO₂e/kWh"),
            (c3, t["dash_kpi3"], str(high_risk),        "OECD Due Diligence zone check"),
            (c4, t["dash_kpi4"], f"{transparency:.0%}", "UID + Carbon + Coordinates coverage"),
        ]:
            with col:
                st.markdown(
                    f"<div class='kpi-card'>"
                    f"<div class='kpi-label'>{label}</div>"
                    f"<div class='kpi-value'>{value}</div>"
                    f"<div class='kpi-delta'>{delta}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<div class='section-header'>{t['dash_radar_title']}</div>", unsafe_allow_html=True)

        def _dim_score(keys: List[str]) -> float:
            mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
            if not mandatory:
                return 0.0
            met = sum(1 for r in mandatory if all((r.metrics.get(k, {}) or {}).get("met") is True for k in keys))
            return met / len(mandatory)

        dims   = ["Safety", "Environmental", "Traceability", "Recycled Mat.", "Performance", "BMS Access"]
        scores = [
            _dim_score(["extinguishing_agent", "thermal_runaway_prevention", "explosion_proof_declaration"]),
            _dim_score(["carbon_footprint_total_kg_co2e", "carbon_physical_plausibility"]),
            _dim_score(["unique_identifier", "manufacturer_id", "mine_coordinates"]),
            _dim_score(["recycled_lithium_pct", "recycled_cobalt_pct", "recycled_nickel_pct", "recycled_lead_pct"]),
            _dim_score(["rated_capacity_ah", "nominal_voltage_v", "rated_power_w", "expected_lifetime_cycles"]),
            _dim_score(["bms_access_permissions"]),
        ]
        fig_radar = go.Figure(go.Scatterpolar(
            r=scores + [scores[0]], theta=dims + [dims[0]],
            fill="toself", fillcolor="rgba(100,255,218,0.18)",
            line=dict(color="#64FFDA", width=2), name="Compliance Score",
        ))
        fig_radar.update_layout(
            polar=dict(
                bgcolor="#0D1B2A",
                radialaxis=dict(visible=True, range=[0, 1], color="#8892B0", gridcolor="#1E3A5F", tickfont=dict(color="#8892B0")),
                angularaxis=dict(color="#CCD6F6", gridcolor="#1E3A5F"),
            ),
            paper_bgcolor="#112240", plot_bgcolor="#112240",
            font=dict(color="#CCD6F6"), showlegend=False,
            margin=dict(t=30, b=30, l=60, r=60), height=380,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    else:
        st.info(t["dash_no_data"])
        c1, c2, c3, c4 = st.columns(4)
        for col, label, delta in [
            (c1, t["dash_kpi1"], "Upload data to compute"),
            (c2, t["dash_kpi2"], "EU benchmark ≈ 100 kg CO₂e/kWh"),
            (c3, t["dash_kpi3"], "OECD zone check"),
            (c4, t["dash_kpi4"], "UID + Carbon + Coordinates"),
        ]:
            with col:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>{label}</div>"
                    f"<div class='kpi-value'>—</div><div class='kpi-delta'>{delta}</div></div>",
                    unsafe_allow_html=True,
                )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPLIANCE AUDITOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_audit:

    csv_rows: List[Dict[str, str]] = []
    if uploaded_file is not None:
        csv_bytes = uploaded_file.getvalue()
        csv_hash  = _hash_bytes(csv_bytes)
        if st.session_state.get("csv_hash") != csv_hash:
            st.session_state.update({
                "csv_hash": csv_hash,
                "csv_rows": _parse_csv_bytes(csv_bytes),
                "audit_results": None,
                "pdf_bytes": None,
                "pdf_filename": None,
            })
        csv_rows = st.session_state["csv_rows"]
        st.markdown(f"<div class='section-header'>{t['preview']}</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(csv_rows), use_container_width=True, height=220)

    # ── Manual single entry ──
    st.markdown(f"<div class='section-header'>{t['manual_entry']}</div>", unsafe_allow_html=True)
    with st.form("manual_single_entry"):
        col1, col2, col3 = st.columns(3)
        with col1:
            model           = st.text_input("model", "MANUAL-EV-001")
            category        = st.selectbox("category", ["EV", "LMT", "INDUSTRIAL"], index=0)
            capacity_kwh    = st.number_input("capacity_kwh", min_value=0.0, value=60.0)
            manufacturer    = st.text_input("manufacturer", "Demo Manufacturer")
            manufacturer_id = st.text_input("manufacturer_id", "MFG-DEMO01")
        with col2:
            unique_identifier = st.text_input("unique_identifier", "EU-UID-MANUAL-001")
            battery_id        = st.text_input("battery_id", "SN-MANUAL-001")
            manufacture_place = st.text_input("manufacture_place", "DE, Berlin")
            manufacture_date  = st.text_input("manufacture_date", "2026-12")
            chemistry         = st.selectbox("chemistry", ["NMC", "LFP"], index=0)
        with col3:
            li     = st.number_input("recycled_lithium_pct (%)", min_value=0.0, max_value=100.0, value=8.0)
            co     = st.number_input("recycled_cobalt_pct (%)",  min_value=0.0, max_value=100.0, value=16.0)
            ni     = st.number_input("recycled_nickel_pct (%)",  min_value=0.0, max_value=100.0, value=6.0)
            pb     = st.number_input("recycled_lead_pct (%)",    min_value=0.0, max_value=100.0, value=85.0)
            carbon = st.number_input("carbon_footprint_total_kg_co2e", min_value=0.0, value=120.0)
        submitted = st.form_submit_button(t["manual_submit"], use_container_width=True)

    if submitted:
        r = validate_record({
            "model": model, "category": category, "capacity_kwh": capacity_kwh,
            "manufacturer": manufacturer, "manufacturer_id": manufacturer_id,
            "unique_identifier": unique_identifier, "battery_id": battery_id,
            "manufacture_place": manufacture_place, "manufacture_date": manufacture_date,
            "chemistry": chemistry,
            "recycled_lithium_pct": li, "recycled_cobalt_pct": co,
            "recycled_nickel_pct": ni,  "recycled_lead_pct": pb,
            "hazardous_substances_declaration": "declared",
            "rated_capacity_ah": 180, "nominal_voltage_v": 3.7, "rated_power_w": 600,
            "self_discharge_rate_pct_per_month": 2.0,
            "charge_discharge_efficiency_percent": 92, "expected_lifetime_cycles": 1400,
            "thermal_runaway_prevention": "yes", "extinguishing_agent": "CO2",
            "explosion_proof_declaration": "yes", "bms_access_permissions": "read+write",
            "mine_latitude": -11.68, "mine_longitude": 27.5,
            "carbon_footprint_total_kg_co2e": carbon,
        })
        st.markdown(f"<div class='section-header'>{t['manual_result']}</div>", unsafe_allow_html=True)
        status_color = "#64FFDA" if r.status == "COMPLIANT" else ("#FF6B6B" if r.status == "NON_COMPLIANT" else "#8892B0")
        st.markdown(
            f"<div class='kpi-card' style='text-align:left;'>"
            f"<span style='color:{status_color};font-weight:700;font-size:1.1rem;'>{r.status}</span> &nbsp;|&nbsp; "
            f"Risk: <b>{r.risk_level}</b><br/>"
            f"<span style='color:#8892B0;font-size:0.82rem;'>"
            + (" | ".join(r.issues[:3]) if r.issues else "No issues") +
            "</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Audit button ──
    if st.button(t["run_audit"], type="primary", use_container_width=True, disabled=uploaded_file is None):
        if uploaded_file is None:
            st.warning(t["upload_hint"])
        else:
            progress_bar = st.progress(0)
            for i, step in enumerate(t["progress_steps"]):
                progress_bar.progress(int((i + 1) / len(t["progress_steps"]) * 90), text=step)
                time.sleep(0.12)

            results = [validate_record(row) for row in csv_rows]
            st.session_state["audit_results"] = results

            safe_client = "".join(c for c in client_name  if c.isalnum() or c in "-_").strip() or "Client"
            safe_proj   = "".join(c for c in project_code if c.isalnum() or c in "-_").strip() or "Project"
            pdf_filename = f"DPP_Audit_Report_{safe_client}_{safe_proj}.pdf"

            progress_bar.progress(95, text=t["progress_steps"][-1])
            try:
                pdf_bytes = generate_audit_pdf(results, lang, report_no, client_name, project_code)
                st.session_state["pdf_bytes"]    = pdf_bytes
                st.session_state["pdf_filename"] = pdf_filename
            except RuntimeError as err:
                st.session_state["pdf_bytes"] = None
                progress_bar.empty()
                st.error(
                    f"**PDF 生成失败 / PDF generation failed**\n\n{err}\n\n"
                    "**Fix:** Ensure `NotoSansSC-Regular.otf` (~8 MB) is in the project root, "
                    "or allow internet access for auto-download."
                )
                st.stop()

            progress_bar.progress(100, text=t["done"])
            time.sleep(0.3)
            progress_bar.empty()
            st.success(t["done"])

    # ── Results display ──
    if st.session_state.get("audit_results"):
        results = st.session_state["audit_results"]

        def _passes_fraud_filter(flags: List[str]) -> bool:
            fset = set(flags or [])
            if fraud_filter == t["af_high"]:   return "HIGH_RISK" in fset
            if fraud_filter == t["af_unreal"]: return "DATA_UNREALISTIC" in fset
            return bool(fset & {"HIGH_RISK", "DATA_UNREALISTIC"})

        suspicious = [r for r in results if _passes_fraud_filter(r.fraud_flags or [])]
        display    = suspicious if only_suspicious else results

        compliant = sum(1 for r in results if r.status == "COMPLIANT")
        non       = sum(1 for r in results if r.status == "NON_COMPLIANT")
        ratio     = compliant / (compliant + non) if (compliant + non) else 0
        c_vals    = [(r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value") for r in results]
        c_vals    = [v for v in c_vals if isinstance(v, (int, float))]
        avg_cf    = sum(c_vals) / len(c_vals) if c_vals else 0.0

        col1, col2, col3 = st.columns(3)
        for col, label, val in [
            (col1, t["metric_rate"],   f"{ratio:.1%}"),
            (col2, t["metric_carbon"], f"{avg_cf:.1f}"),
            (col3, t["metric_risk"],   str(len(suspicious))),
        ]:
            with col:
                st.markdown(
                    f"<div class='kpi-card'><div class='kpi-label'>{label}</div>"
                    f"<div class='kpi-value'>{val}</div></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("<br>", unsafe_allow_html=True)

        try:
            import plotly.express as px

            col_a, col_b = st.columns(2)
            with col_a:
                mix = pd.DataFrame({
                    "Status": ["COMPLIANT", "NON_COMPLIANT", "NOT_REQUIRED_DPP"],
                    "Count":  [
                        sum(1 for r in results if r.status == "COMPLIANT"),
                        sum(1 for r in results if r.status == "NON_COMPLIANT"),
                        sum(1 for r in results if r.status == "NOT_REQUIRED_DPP"),
                    ],
                })
                fig1 = px.pie(
                    mix[mix["Count"] > 0], names="Status", values="Count", hole=0.55,
                    title=t["chart_mix"], color="Status",
                    color_discrete_map={"COMPLIANT": "#64FFDA", "NON_COMPLIANT": "#FF6B6B", "NOT_REQUIRED_DPP": "#8892B0"},
                )
                fig1.update_layout(
                    paper_bgcolor="#112240", plot_bgcolor="#112240",
                    font=dict(color="#CCD6F6"), legend=dict(font=dict(color="#CCD6F6")),
                    height=320, margin=dict(t=40, b=10),
                )
                st.plotly_chart(fig1, use_container_width=True)

            with col_b:
                gap_rows = []
                for r in results:
                    for mat, k, thr in [
                        ("Lithium", "recycled_lithium_pct", RECYCLED_MIN_PCT["Lithium"]),
                        ("Cobalt",  "recycled_cobalt_pct",  RECYCLED_MIN_PCT["Cobalt"]),
                        ("Nickel",  "recycled_nickel_pct",  RECYCLED_MIN_PCT["Nickel"]),
                    ]:
                        val = (r.metrics.get(k, {}) or {}).get("value")
                        if isinstance(val, (int, float)):
                            gap_rows.append({"Model": r.model, "Material": mat, "Gap vs Threshold (pp)": val - thr})
                if gap_rows:
                    fig2 = px.bar(
                        pd.DataFrame(gap_rows), x="Model", y="Gap vs Threshold (pp)",
                        color="Material", barmode="group", title=t["chart_gap"],
                        color_discrete_map={"Lithium": "#64FFDA", "Cobalt": "#A78BFA", "Nickel": "#FB923C"},
                    )
                    fig2.add_hline(y=0, line_dash="dash", line_color="#FF6B6B", annotation_text="Threshold")
                    fig2.update_layout(
                        paper_bgcolor="#112240", plot_bgcolor="#112240",
                        font=dict(color="#CCD6F6"),
                        xaxis=dict(color="#8892B0", gridcolor="#1E3A5F"),
                        yaxis=dict(color="#8892B0", gridcolor="#1E3A5F"),
                        legend=dict(font=dict(color="#CCD6F6")),
                        height=320, margin=dict(t=40, b=10),
                    )
                    st.plotly_chart(fig2, use_container_width=True)
        except Exception:
            pass

        # Results table with legal expanders
        st.markdown(f"<div class='section-header'>{t['result_table']}</div>", unsafe_allow_html=True)

        for r in display:
            icon        = "✅" if r.status == "COMPLIANT" else ("⛔" if r.status == "NON_COMPLIANT" else "ℹ️")
            risk_color  = {"low": "#64FFDA", "medium": "#FCD34D", "high": "#FF6B6B"}.get(r.risk_level, "#8892B0")
            fraud_badge = (
                f" 🚩 <span style='color:#FF6B6B;font-size:0.78rem;'>{'  '.join(r.fraud_flags)}</span>"
                if r.fraud_flags else ""
            )
            with st.expander(f"{icon} **{r.model}** — {r.status} | Risk: {r.risk_level.upper()}"):
                st.markdown(
                    f"<span style='color:{risk_color};font-weight:600;'>Risk Level: {r.risk_level.upper()}</span>"
                    f"{fraud_badge}", unsafe_allow_html=True,
                )
                if r.issues:
                    st.markdown("**Issues:**")
                    for issue in r.issues:
                        citation = next(
                            (v for k, v in LEGAL_CITATIONS.items() if k.replace("_", " ").split()[0] in issue.lower()),
                            None,
                        )
                        st.markdown(f"• {issue}")
                        if citation:
                            st.markdown(f"<div class='law-quote'>📖 {citation}</div>", unsafe_allow_html=True)
                else:
                    st.markdown("No compliance issues found.")

        # Download + inline preview
        if st.session_state.get("pdf_bytes"):
            st.markdown("<br>", unsafe_allow_html=True)
            col_dl, _ = st.columns([1, 2])
            with col_dl:
                st.download_button(
                    t["download_pdf"],
                    data=st.session_state["pdf_bytes"],
                    file_name=st.session_state.get("pdf_filename", "DPP_Audit_Report.pdf"),
                    mime="application/pdf",
                    use_container_width=True,
                )

            b64_pdf     = base64.b64encode(st.session_state["pdf_bytes"]).decode()
            preview_lbl = "📄 报告预览" if lang == "zh" else "📄 Report Preview"
            st.markdown(f"**{preview_lbl}**")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="820" '
                f'style="border:1px solid #334155;border-radius:8px;margin-top:6px;" '
                f'type="application/pdf">'
                f'<p style="color:#94a3b8">浏览器不支持内嵌 PDF 预览，请点击上方按钮下载后查看。</p>'
                f'</iframe>',
                unsafe_allow_html=True,
            )

    elif uploaded_file is None:
        st.info(t["upload_hint"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — TRACEABILITY MAP
# ═══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.markdown(f"<div class='section-header'>{t['map_title']}</div>", unsafe_allow_html=True)
    st.caption(t["map_sub"])

    results_cached = st.session_state.get("audit_results")

    if results_cached:
        try:
            import plotly.express as px

            map_rows = []
            for r in results_cached:
                lat = (r.metrics.get("mine_latitude",  {}) or {}).get("value")
                lon = (r.metrics.get("mine_longitude", {}) or {}).get("value")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    is_risk = "HIGH_RISK" in (r.fraud_flags or [])
                    map_rows.append({
                        "Model": r.model, "Latitude": lat, "Longitude": lon,
                        "Risk": "🔴 High Risk" if is_risk else "🟢 Normal",
                        "Status": r.status, "Color": "#FF6B6B" if is_risk else "#64FFDA",
                        "Size": 16 if is_risk else 10,
                    })

            if map_rows:
                df_map  = pd.DataFrame(map_rows)
                fig_map = px.scatter_geo(
                    df_map, lat="Latitude", lon="Longitude", color="Risk", size="Size",
                    hover_name="Model", hover_data={"Status": True, "Latitude": True, "Longitude": True, "Size": False},
                    color_discrete_map={"🔴 High Risk": "#FF6B6B", "🟢 Normal": "#64FFDA"},
                    projection="natural earth", title=t["map_title"],
                )
                fig_map.update_layout(
                    paper_bgcolor="#112240", font=dict(color="#CCD6F6"),
                    geo=dict(bgcolor="#0A192F", landcolor="#1E3A5F", oceancolor="#0A192F",
                             countrycolor="#1E3A5F", showland=True, showocean=True, showcountries=True),
                    legend=dict(font=dict(color="#CCD6F6"), bgcolor="#112240"),
                    height=520, margin=dict(t=40, b=10, l=0, r=0),
                )
                st.plotly_chart(fig_map, use_container_width=True)
            else:
                st.info("No mine coordinate data found in audit results.")
        except Exception as e:
            st.error(f"Map rendering error: {e}")
    else:
        st.info(t["map_no_data"])
        try:
            import plotly.express as px

            demo = pd.DataFrame([
                {"Zone": "Chile / Argentina (Li)", "Latitude": -22.0, "Longitude": -68.0, "Risk": "🟢 Normal", "Size": 14},
                {"Zone": "DRC Cobalt Belt",         "Latitude":  -8.0, "Longitude":  25.0, "Risk": "🟢 Normal", "Size": 14},
                {"Zone": "Western Australia (Li)",  "Latitude": -26.0, "Longitude": 120.0, "Risk": "🟢 Normal", "Size": 12},
                {"Zone": "Southern Africa (Li)",    "Latitude": -22.0, "Longitude":  24.0, "Risk": "🟢 Normal", "Size": 12},
            ])
            fig_demo = px.scatter_geo(
                demo, lat="Latitude", lon="Longitude", hover_name="Zone", size="Size", color="Risk",
                color_discrete_map={"🟢 Normal": "#64FFDA"},
                projection="natural earth", title="Known Global Li/Co Mining Zones (OECD Reference)",
            )
            fig_demo.update_layout(
                paper_bgcolor="#112240", font=dict(color="#CCD6F6"),
                geo=dict(bgcolor="#0A192F", landcolor="#1E3A5F", oceancolor="#0A192F",
                         countrycolor="#1E3A5F", showland=True, showocean=True, showcountries=True),
                height=480, margin=dict(t=40, b=10, l=0, r=0),
            )
            st.plotly_chart(fig_demo, use_container_width=True)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — REGULATORY LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_law:
    st.markdown(f"<div class='section-header'>{t['law_title']}</div>", unsafe_allow_html=True)

    col_link, _ = st.columns([1, 3])
    with col_link:
        st.link_button(
            t["law_official_link"],
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32023R1542",
        )

    st.markdown("<br>", unsafe_allow_html=True)

    for article_key, content in t["law_articles"].items():
        display_key = article_key if lang == "zh" else content.get("en_title", article_key)
        body  = content.get(lang, content.get("en", ""))
        quote = content.get("quote", "")
        with st.expander(f"📋 **{display_key}**", expanded=False):
            st.markdown(body)
            if quote:
                st.markdown(f"<div class='law-quote'>📖 {quote}</div>", unsafe_allow_html=True)
                st.code(quote, language=None)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — ABOUT & SUPPORT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_about:
    st.markdown(f"<div class='section-header'>{t['about_title']}</div>", unsafe_allow_html=True)
    st.markdown(t["about_desc"])

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"**{t['about_refs']}**")
    for item in t["about_ref_items"]:
        st.markdown(f"• {item}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**📁 Reference Documents Available Locally**")
    ref_docs = [
        ("EU_Battery_Reg_Full.pdf",      "EU 2023/1542 Full Text"),
        ("GBA_Passport_Standard.pdf",    "GBA Battery Passport Standard"),
        ("JRC_Carbon_Benchmark.pdf",     "JRC Carbon Footprint Methodology"),
        ("OECD_Minerals_Guidance.pdf",   "OECD Due Diligence Minerals Guidance"),
    ]
    doc_cols = st.columns(2)
    for i, (fname, label) in enumerate(ref_docs):
        fpath = Path(__file__).parent / fname
        with doc_cols[i % 2]:
            opacity = "1" if fpath.exists() else "0.5"
            st.markdown(
                f"<div class='law-card' style='opacity:{opacity};'>📄 <b>{label}</b><br>"
                f"<span style='color:#8892B0;font-size:0.8rem;'>{fname}</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"**{t['about_contact']}**")
    st.info(t["about_contact_body"])

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"**{t['about_disclaimer_title']}**")
    st.markdown(
        f"<div class='disclaimer-box'>{t['about_disclaimer'].replace(chr(10), '<br>')}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;color:#3D5270;font-size:0.78rem;'>"
        "⚡ DPP Expert 3.0 &nbsp;·&nbsp; Powered by EU 2023/1542 Compliance Engine &nbsp;·&nbsp; "
        "Generated by AI Compliance Engine – Verified for EU 2023/1542 Standards"
        "</div>",
        unsafe_allow_html=True,
    )
