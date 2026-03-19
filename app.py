import csv
import hashlib
import os
import tempfile
import time
from io import StringIO
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from dpp_engine import RECYCLED_MIN_PCT, generate_audit_pdf, validate_record

# Streamlit writes internal files to ~/.streamlit by default.
_PROJECT_HOME = Path(__file__).resolve().parent / ".streamlit_home"
try:
    _ = Path.home() / ".streamlit"
    _marker = _ / ".write_test"
    _marker.parent.mkdir(parents=True, exist_ok=True)
    _marker.write_text("ok", encoding="utf-8")
    _marker.unlink(missing_ok=True)
except Exception:
    _PROJECT_HOME.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(_PROJECT_HOME)


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


TRANSLATIONS = {
    "zh": {
        "lang_select": "语言",
        "lang_zh": "中文",
        "lang_en": "English",
        "title": "中资出海电池 DPP 合规预审计平台",
        "subtitle": "上传数据并执行欧盟 2023/1542 电池法案预审计。",
        "client_name": "客户名称",
        "project_code": "项目编号",
        "report_no": "报告编号",
        "tab_audit": "🛡 AI 审计中心",
        "tab_law": "📚 法规百科",
        "tab_news": "📰 行业动态",
        "tab_case": "🏆 成功案例",
        "upload_csv": "上传 CSV 文件",
        "filter_fraud": "🚨 仅查看疑似造假/高风险样本",
        "anomaly_filter": "异常类型筛选",
        "af_all": "全部异常",
        "af_high": "仅 HIGH_RISK",
        "af_unreal": "仅 DATA_UNREALISTIC",
        "preview": "数据预览",
        "manual_entry": "手动单条填报",
        "run_audit": "开始 AI 审计",
        "running": "正在审计并生成报告...",
        "progress": "AI 正在进行深度法律检索与字段比对...",
        "done": "审计完成",
        "overview": "审计概览",
        "metric_rate": "总合规率",
        "metric_carbon": "平均碳足迹",
        "metric_risk": "风险预警数",
        "chart_mix": "合规结构",
        "chart_gap": "回收比例与法案阈值差距（锂/钴/镍）",
        "result_table": "审计结果",
        "download_pdf": "下载 PDF 审计报告",
        "status_col": "判定结果",
        "risk_col": "风险等级",
        "reason_col": "问题说明",
        "model_col": "型号",
        "law_title": "法规重点摘要",
        "law_body": "Article 7（碳足迹）、Article 8（回收比例）、Article 14（状态健康信息）、Article 77 与 Annex XIII（电池护照信息要求）。",
        "news_title": "2026 年欧盟 DPP 执行进度（模拟高质量摘要）",
        "news_1": "2026Q1：多国市场监管机构发布电池护照数据一致性检查指引，强化供应链可追溯要求。",
        "news_2": "2026Q2：重点行业联盟推动跨平台护照互操作标准，降低 OEM 与 Tier-1 数据交换成本。",
        "news_3": "2026Q3：欧洲买方审计将回收比例与碳足迹声明纳入采购门槛，合规成为核心商业条件。",
        "case_title": "模拟成功案例",
        "case_body": "某中国电池头部企业通过建立 DPP 数据治理中台、碳足迹核算体系与供应商证据链，在欧盟客户年度评审中获得优先采购资格。",
        "manual_submit": "提交单条审计",
        "manual_result": "单条审计结果",
    },
    "en": {
        "lang_select": "Language",
        "lang_zh": "Chinese",
        "lang_en": "English",
        "title": "Battery DPP Compliance Pre-Audit Platform",
        "subtitle": "Upload data and run EU 2023/1542 pre-audit checks.",
        "client_name": "Client Name",
        "project_code": "Project Code",
        "report_no": "Report No.",
        "tab_audit": "🛡 AI Audit Center",
        "tab_law": "📚 Regulation Knowledge",
        "tab_news": "📰 Industry Updates",
        "tab_case": "🏆 Success Story",
        "upload_csv": "Upload CSV File",
        "filter_fraud": "🚨 Show only suspicious/high-risk samples",
        "anomaly_filter": "Anomaly Filter",
        "af_all": "All anomalies",
        "af_high": "Only HIGH_RISK",
        "af_unreal": "Only DATA_UNREALISTIC",
        "preview": "Data Preview",
        "manual_entry": "Manual Single Entry",
        "run_audit": "Start AI Audit",
        "running": "Auditing and generating report...",
        "progress": "AI is performing legal retrieval and field validation...",
        "done": "Audit completed",
        "overview": "Audit Overview",
        "metric_rate": "Overall Compliance Rate",
        "metric_carbon": "Average Carbon Footprint",
        "metric_risk": "Risk Alerts",
        "chart_mix": "Compliance Mix",
        "chart_gap": "Recycled Content Gap vs Legal Threshold (Li/Co/Ni)",
        "result_table": "Audit Results",
        "download_pdf": "Download PDF Audit Report",
        "status_col": "Status",
        "risk_col": "Risk Level",
        "reason_col": "Issues",
        "model_col": "Model",
        "law_title": "Key Regulatory Summary",
        "law_body": "Article 7 (carbon footprint), Article 8 (recycled content), Article 14 (state-of-health information), Article 77 and Annex XIII (battery passport data requirements).",
        "news_title": "EU DPP 2026 Progress (simulated high-quality briefs)",
        "news_1": "Q1 2026: Multiple authorities publish battery-passport data consistency guidance, strengthening supply-chain traceability requirements.",
        "news_2": "Q2 2026: Industry alliances accelerate cross-platform passport interoperability standards to reduce OEM/Tier-1 integration cost.",
        "news_3": "Q3 2026: European buyers include recycled-content and carbon-footprint declarations as procurement gates.",
        "case_title": "Simulated Success Story",
        "case_body": "A leading Chinese battery company built a DPP data governance hub, carbon accounting workflow, and supplier evidence chain, and achieved preferred-supplier status in EU annual review.",
        "manual_submit": "Run Single Audit",
        "manual_result": "Single Audit Result",
    },
}

st.set_page_config(page_title="DPP Audit", layout="wide")
lang_pick = st.sidebar.selectbox(TRANSLATIONS["en"]["lang_select"], [TRANSLATIONS["zh"]["lang_zh"], TRANSLATIONS["en"]["lang_en"]], index=0)
lang = "zh" if lang_pick == TRANSLATIONS["zh"]["lang_zh"] else "en"
t = TRANSLATIONS[lang]

client_name = (st.sidebar.text_input(t["client_name"], value="Demo Client") or "Demo Client").strip()
project_code = (st.sidebar.text_input(t["project_code"], value="DPP-2026-PRE") or "DPP-2026-PRE").strip()
report_no = f"{project_code}-{_hash_bytes((client_name + project_code).encode())[:8].upper()}"

st.title(t["title"])
st.caption(t["subtitle"])
st.write(f"**{t['report_no']}**: `{report_no}`")


def _parse_csv_bytes(csv_bytes: bytes) -> List[Dict[str, str]]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    return [row for row in csv.DictReader(StringIO(text))]


def _passes_fraud_filter(flags: set[str], fraud_filter: str) -> bool:
    if fraud_filter == t["af_high"]:
        return "HIGH_RISK" in flags
    if fraud_filter == t["af_unreal"]:
        return "DATA_UNREALISTIC" in flags
    return bool(flags.intersection({"HIGH_RISK", "DATA_UNREALISTIC"}))


def _render_results_table(results):
    rows = []
    for r in results:
        rows.append(
            {
                t["model_col"]: r.model,
                t["status_col"]: r.status,
                t["risk_col"]: r.risk_level,
                t["reason_col"]: " | ".join(r.missing_fields or r.issues[:2]),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


tab_audit, tab_law, tab_news, tab_case = st.tabs([t["tab_audit"], t["tab_law"], t["tab_news"], t["tab_case"]])

with tab_audit:
    uploaded_file = st.sidebar.file_uploader(t["upload_csv"], type=["csv"])
    only_suspicious = st.sidebar.toggle(t["filter_fraud"], value=False)
    fraud_filter = st.sidebar.selectbox(t["anomaly_filter"], [t["af_all"], t["af_high"], t["af_unreal"]], index=0)

    csv_rows: List[Dict[str, str]] = []
    if uploaded_file is not None:
        csv_bytes = uploaded_file.getvalue()
        csv_hash = _hash_bytes(csv_bytes)
        if "csv_hash" not in st.session_state or st.session_state.get("csv_hash") != csv_hash:
            st.session_state["csv_hash"] = csv_hash
            st.session_state["csv_rows"] = _parse_csv_bytes(csv_bytes)
            st.session_state["audit_results"] = None
            st.session_state["pdf_bytes"] = None
            st.session_state["pdf_filename"] = None
        csv_rows = st.session_state["csv_rows"]
        st.subheader(t["preview"])
        st.dataframe(csv_rows, use_container_width=True, height=260)

    st.subheader(t["manual_entry"])
    with st.form("manual_single_entry"):
        col1, col2, col3 = st.columns(3)
        with col1:
            model = st.text_input("model", "MANUAL-EV-001")
            category = st.selectbox("category", ["EV", "LMT", "INDUSTRIAL"], index=0)
            capacity_kwh = st.number_input("capacity_kwh", min_value=0.0, value=60.0)
            manufacturer = st.text_input("manufacturer", "Demo Manufacturer")
            manufacturer_id = st.text_input("manufacturer_id", "MFG-DEMO01")
        with col2:
            unique_identifier = st.text_input("unique_identifier", "EU-UID-MANUAL-001")
            battery_id = st.text_input("battery_id", "SN-MANUAL-001")
            manufacture_place = st.text_input("manufacture_place", "DE, Berlin")
            manufacture_date = st.text_input("manufacture_date", "2026-12")
            chemistry = st.selectbox("chemistry", ["NMC", "LFP"], index=0)
        with col3:
            li = st.number_input("recycled_lithium_pct", min_value=0.0, value=8.0)
            co = st.number_input("recycled_cobalt_pct", min_value=0.0, value=16.0)
            ni = st.number_input("recycled_nickel_pct", min_value=0.0, value=6.0)
            pb = st.number_input("recycled_lead_pct", min_value=0.0, value=85.0)
            carbon = st.number_input("carbon_footprint_total_kg_co2e", min_value=0.0, value=120.0)
        submitted = st.form_submit_button(t["manual_submit"], use_container_width=True)
    if submitted:
        single = {
            "model": model,
            "category": category,
            "capacity_kwh": capacity_kwh,
            "manufacturer": manufacturer,
            "manufacturer_id": manufacturer_id,
            "unique_identifier": unique_identifier,
            "battery_id": battery_id,
            "manufacture_place": manufacture_place,
            "manufacture_date": manufacture_date,
            "chemistry": chemistry,
            "recycled_lithium_pct": li,
            "recycled_cobalt_pct": co,
            "recycled_nickel_pct": ni,
            "recycled_lead_pct": pb,
            "hazardous_substances_declaration": "declared",
            "rated_capacity_ah": 180,
            "nominal_voltage_v": 3.7,
            "rated_power_w": 600,
            "self_discharge_rate_pct_per_month": 2.0,
            "charge_discharge_efficiency_percent": 92,
            "expected_lifetime_cycles": 1400,
            "thermal_runaway_prevention": "yes",
            "extinguishing_agent": "CO2",
            "explosion_proof_declaration": "yes",
            "bms_access_permissions": "read+write",
            "mine_latitude": -11.68,
            "mine_longitude": 27.5,
        }
        r = validate_record(single)
        st.subheader(t["manual_result"])
        st.json({"model": r.model, "status": r.status, "risk_level": r.risk_level, "issues": r.issues, "missing_fields": r.missing_fields})

    if st.button(t["run_audit"], type="primary", use_container_width=True, disabled=uploaded_file is None):
        with st.spinner(t["running"]):
            progress = st.progress(0, text=t["progress"])
            for p in (20, 40, 60, 80, 100):
                time.sleep(0.08)
                progress.progress(p)

            results = [validate_record(row) for row in csv_rows]
            st.session_state["audit_results"] = results

            safe_client = "".join(ch for ch in client_name if ch.isalnum() or ch in ("-", "_")).strip() or "Client"
            safe_project = "".join(ch for ch in project_code if ch.isalnum() or ch in ("-", "_")).strip() or "Project"
            pdf_filename = f"DPP_Audit_Report_{safe_client}_{safe_project}.pdf"
            with tempfile.TemporaryDirectory() as td:
                out_pdf_path = Path(td) / pdf_filename
                generate_audit_pdf(results=results, source_csv=Path(uploaded_file.name), output_pdf=out_pdf_path, language=lang)
                st.session_state["pdf_bytes"] = out_pdf_path.read_bytes()
                st.session_state["pdf_filename"] = pdf_filename
            progress.empty()

    if st.session_state.get("audit_results") is not None:
        results = st.session_state["audit_results"]
        suspicious = [r for r in results if _passes_fraud_filter(set(getattr(r, "fraud_flags", []) or []), fraud_filter)]
        display = suspicious if only_suspicious else results

        compliant = sum(1 for r in results if r.status == "COMPLIANT")
        non = sum(1 for r in results if r.status == "NON_COMPLIANT")
        ratio = compliant / (compliant + non) if (compliant + non) else 0
        carbon_values = [(r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value") for r in results]
        carbon_values = [v for v in carbon_values if isinstance(v, (int, float))]
        avg_cf = sum(carbon_values) / len(carbon_values) if carbon_values else 0.0
        c1, c2, c3 = st.columns(3)
        c1.metric(t["metric_rate"], f"{ratio:.1%}")
        c2.metric(t["metric_carbon"], f"{avg_cf:.2f}")
        c3.metric(t["metric_risk"], len(suspicious))

        try:
            import plotly.express as px
            mix = pd.DataFrame(
                {
                    "status": ["COMPLIANT", "NON_COMPLIANT", "NOT_REQUIRED_DPP"],
                    "count": [compliant, non, sum(1 for r in results if r.status == "NOT_REQUIRED_DPP")],
                }
            )
            fig1 = px.pie(mix[mix["count"] > 0], names="status", values="count", hole=0.55, title=t["chart_mix"])
            st.plotly_chart(fig1, use_container_width=True)

            gap_rows = []
            for r in results:
                for mat, k, thr in [
                    ("Lithium", "recycled_lithium_pct", RECYCLED_MIN_PCT["Lithium"]),
                    ("Cobalt", "recycled_cobalt_pct", RECYCLED_MIN_PCT["Cobalt"]),
                    ("Nickel", "recycled_nickel_pct", RECYCLED_MIN_PCT["Nickel"]),
                ]:
                    val = ((r.metrics.get(k, {}) or {}).get("value"))
                    if isinstance(val, (int, float)):
                        gap_rows.append({"model": r.model, "material": mat, "gap": val - thr})
            if gap_rows:
                fig2 = px.bar(pd.DataFrame(gap_rows), x="model", y="gap", color="material", barmode="group", title=t["chart_gap"])
                fig2.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig2, use_container_width=True)
        except Exception:
            pass

        st.subheader(t["result_table"])
        _render_results_table(display)
        if st.session_state.get("pdf_bytes"):
            st.download_button(
                t["download_pdf"],
                data=st.session_state["pdf_bytes"],
                file_name=st.session_state.get("pdf_filename", "DPP_Audit_Report.pdf"),
                mime="application/pdf",
                use_container_width=True,
            )

with tab_law:
    st.subheader(t["law_title"])
    st.write(t["law_body"])

with tab_news:
    st.subheader(t["news_title"])
    st.write(f"1) {t['news_1']}")
    st.write(f"2) {t['news_2']}")
    st.write(f"3) {t['news_3']}")

with tab_case:
    st.subheader(t["case_title"])
    st.write(t["case_body"])

