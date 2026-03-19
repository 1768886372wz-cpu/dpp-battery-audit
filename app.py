import csv
import hashlib
import os
import tempfile
import time
from io import StringIO
from pathlib import Path
from typing import Dict, List

# Streamlit writes internal files to ~/.streamlit by default.
# In some sandboxed/restricted environments, ~/ is not writable, which can
# crash the Streamlit session (disconnect in browser).
# We redirect HOME to a writable folder inside the project.
_PROJECT_HOME = Path(__file__).resolve().parent / ".streamlit_home"
try:
    _ = Path.home() / ".streamlit"
    # If Path.home() is not writable, attempt to create a marker.
    _marker = _ / ".write_test"
    _marker.parent.mkdir(parents=True, exist_ok=True)
    _marker.write_text("ok", encoding="utf-8")
    _marker.unlink(missing_ok=True)
except Exception:
    _PROJECT_HOME.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(_PROJECT_HOME)

import streamlit as st
import pandas as pd

from dpp_engine import RECYCLED_MIN_PCT, generate_audit_pdf, validate_record


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


st.set_page_config(
    page_title="中资出海电池 DPP 合规预审计平台",
    layout="wide",
)


st.markdown(
    """
<style>
body { background: #F7F8FA; }
.brand-shell { background: linear-gradient(120deg,#0B3D91,#1C5AC3); border-radius: 14px; padding: 14px 18px; color: #fff; margin-bottom: 14px; }
.brand-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.brand-left { display:flex; align-items:center; gap:12px; }
.brand-logo { width:38px; height:38px; border-radius:10px; background:#fff; color:#0B3D91; font-weight:800; display:flex; align-items:center; justify-content:center; }
.brand-name { font-size:18px; font-weight:800; }
.brand-tag { font-size:12px; opacity:0.95; }
.main-title { font-size: 28px; font-weight: 800; letter-spacing: 0.2px; margin-bottom: 6px; }
.subtitle { color: #555; margin-bottom: 18px; }
.card { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
.status-green { color: #1B5E20; font-weight: 800; }
.status-red { color: #B00020; font-weight: 800; }
.status-grey { color: #444; font-weight: 800; }
.small { color: #666; font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

lang = st.sidebar.selectbox("Language / 语言", ["中文界面", "English Interface"], index=0)
is_cn = lang == "中文界面"

UI = {
    "title": "中资出海电池 DPP 合规预审计平台" if is_cn else "Battery DPP Compliance Pre-Audit Platform",
    "subtitle": "上传电池数据表，进行欧盟 2023/1542 电池 DPP 合规预审计并生成报告"
    if is_cn
    else "Upload battery data and run EU 2023/1542 DPP pre-audit with report generation.",
    "upload": "上传 CSV 文件" if is_cn else "Upload CSV File",
    "toggle_suspicious": "🚨 仅查看疑似造假/高风险样本" if is_cn else "🚨 Show only suspicious/high-risk samples",
    "fraud_filter": "异常类型筛选" if is_cn else "Anomaly Type Filter",
    "preview_title": "上传数据预览（Model 级别输入）" if is_cn else "Uploaded Data Preview (Model-level input)",
    "audit_btn": "开始 AI 审计" if is_cn else "Start AI Audit",
    "audit_hint": "将调用本地校验逻辑并生成 PDF。" if is_cn else "Runs local rules and generates PDF report.",
    "overview": "审计概览 / Audit Overview",
    "result_title": "审计结果（Model 级别）" if is_cn else "Audit Results (Model-level)",
    "download_pdf": "下载 PDF 审计报告" if is_cn else "Download PDF Audit Report",
    "client_name": "客户名称" if is_cn else "Client Name",
    "project_code": "项目编号" if is_cn else "Project Code",
    "report_no": "报告编号" if is_cn else "Report No.",
}

client_name = (st.sidebar.text_input(UI["client_name"], value="Demo Client") or "Demo Client").strip()
project_code = (st.sidebar.text_input(UI["project_code"], value="DPP-2026-PRE") or "DPP-2026-PRE").strip()

report_no = f"{project_code}-{_hash_bytes((client_name + project_code).encode())[:8].upper()}"

st.markdown(
    f"""
<div class="brand-shell">
  <div class="brand-row">
    <div class="brand-left">
      <div class="brand-logo">DPP</div>
      <div>
        <div class="brand-name">AI Compliance Engine</div>
        <div class="brand-tag">EU Battery Passport Pre-Audit SaaS</div>
      </div>
    </div>
    <div style="text-align:right; font-size:12px;">
      <div><b>{UI["report_no"]}:</b> {report_no}</div>
      <div><b>{UI["client_name"]}:</b> {client_name}</div>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.markdown(f'<div class="main-title">{UI["title"]}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="subtitle">{UI["subtitle"]}</div>', unsafe_allow_html=True)


def _parse_csv_bytes(csv_bytes: bytes) -> List[Dict[str, str]]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(text))
    return [row for row in reader]


uploaded_file = st.sidebar.file_uploader(UI["upload"], type=["csv"])
only_suspicious = st.sidebar.toggle(UI["toggle_suspicious"], value=False)
fraud_filter = st.sidebar.selectbox(
    UI["fraud_filter"],
    ["全部异常", "仅 HIGH_RISK", "仅 DATA_UNREALISTIC"] if is_cn else ["All Anomalies", "Only HIGH_RISK", "Only DATA_UNREALISTIC"],
    index=0,
)

if uploaded_file is None:
    st.markdown(
        '<div class="card small">请在左侧上传一个电池数据 CSV 文件。</div>' if is_cn else '<div class="card small">Please upload a battery CSV file in the sidebar.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

csv_bytes = uploaded_file.getvalue()
csv_hash = _hash_bytes(csv_bytes)

if "csv_hash" not in st.session_state or st.session_state.get("csv_hash") != csv_hash:
    st.session_state["csv_hash"] = csv_hash
    st.session_state["csv_rows"] = _parse_csv_bytes(csv_bytes)
    st.session_state["audit_results"] = None
    st.session_state["pdf_bytes"] = None
    st.session_state["pdf_filename"] = None

csv_rows: List[Dict[str, str]] = st.session_state["csv_rows"]

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader(UI["preview_title"])
    preview_rows = csv_rows
    if only_suspicious and st.session_state.get("audit_results") is not None:
        def _passes_fraud_filter(flags: set[str]) -> bool:
            if fraud_filter in {"仅 HIGH_RISK", "Only HIGH_RISK"}:
                return "HIGH_RISK" in flags
            if fraud_filter in {"仅 DATA_UNREALISTIC", "Only DATA_UNREALISTIC"}:
                return "DATA_UNREALISTIC" in flags
            return bool(flags.intersection({"HIGH_RISK", "DATA_UNREALISTIC"}))

        flagged_models = {
            r.model
            for r in st.session_state["audit_results"]
            if _passes_fraud_filter(set(getattr(r, "fraud_flags", []) or []))
        }
        preview_rows = [row for row in csv_rows if str(row.get("model", "")).strip() in flagged_models]
    st.dataframe(preview_rows, use_container_width=True, height=280)

    st.markdown("</div>", unsafe_allow_html=True)


def _render_results_table(audit_results):
    # audit_results: List[DppResult]
    header = (
        "<tr>"
        "<th style='text-align:left'>型号 / Model</th>"
        "<th style='text-align:left'>判定 / Status</th>"
        "<th style='text-align:left'>合规风险等级 / Risk</th>"
        "<th style='text-align:left'>不合规原因与条文引用</th>"
        "</tr>"
    )

    def status_html(status: str) -> str:
        if status == "COMPLIANT":
            return "<span class='status-green'>COMPLIANT / 合规</span>"
        if status == "NON_COMPLIANT":
            return "<span class='status-red'>NON_COMPLIANT / 不合规</span>"
        if status == "NOT_REQUIRED_DPP":
            return "<span class='status-grey'>NOT_REQUIRED_DPP / 不强制执行 DPP</span>"
        return "<span class='status-grey'>" + status + "</span>"

    def risk_html(risk: str) -> str:
        if risk == "low":
            return "<span class='status-green'><b>低 / Low</b></span>"
        if risk == "medium":
            return "<span style='color:#B26A00; font-weight:800'><b>中 / Medium</b></span>"
        if risk == "high":
            return "<span class='status-red'><b>高 / High</b></span>"
        return "<span class='status-grey'><b>N/A</b></span>"

    rows_html = []
    for r in audit_results:
        missing = getattr(r, "missing_fields", []) or []
        issues = getattr(r, "issues", []) or []
        if r.status == "NON_COMPLIANT":
            reasons = "<br/>".join([f"• {x}" for x in missing]) if missing else "• （未提供原因）"
            reasons_html = reasons
        elif r.status == "NOT_REQUIRED_DPP":
            analysis = [x for x in issues if str(x).startswith("Analysis (not mandatory):")]
            if analysis:
                reasons_html = "<br/>".join([f"• {x}" for x in analysis[:6]])
            else:
                # Fallback: show applicability note (Art. 77(1) exemption).
                reasons_html = f"• {issues[0]}" if issues else "—"
        else:
            reasons_html = "—"

        rows_html.append(
            "<tr>"
            f"<td>{r.model}</td>"
            f"<td>{status_html(r.status)}</td>"
            f"<td>{risk_html(getattr(r, 'risk_level', 'N/A'))}</td>"
            f"<td>{reasons_html}</td>"
            "</tr>"
        )

    table_html = (
        "<table style='width:100%; border-collapse:collapse; background:#fff'>"
        "<thead>"
        f"{header}"
        "</thead>"
        "<tbody>"
        + "".join(rows_html)
        + "</tbody>"
        "</table>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


start_col, help_col = st.columns([3, 1])
with start_col:
    start_clicked = st.button(UI["audit_btn"], type="primary", use_container_width=True)

with help_col:
    st.markdown(f'<div class="small">{UI["audit_hint"]}</div>', unsafe_allow_html=True)


if start_clicked:
    with st.spinner("正在审计并生成报告..." if is_cn else "Auditing and generating report..."):
        progress = st.progress(0, text="AI 正在检索法条并比对字段..." if is_cn else "AI is validating legal clauses and data fields...")
        for p in (15, 35, 55, 75, 90):
            time.sleep(0.08)
            progress.progress(p)
        try:
            results = [validate_record(row) for row in csv_rows]
        except Exception as e:
            st.error(f"审计失败：{e}" if is_cn else f"Audit failed: {e}")
            st.stop()

        # Generate PDF to a temporary file, then read bytes for download
        pdf_bytes = None
        safe_client = "".join(ch for ch in client_name if ch.isalnum() or ch in ("-", "_")).strip() or "Client"
        safe_project = "".join(ch for ch in project_code if ch.isalnum() or ch in ("-", "_")).strip() or "Project"
        pdf_filename = f"DPP_Audit_Report_{safe_client}_{safe_project}.pdf"
        try:
            with tempfile.TemporaryDirectory() as td:
                out_pdf_path = Path(td) / pdf_filename
                # generate_audit_pdf only uses source_csv.name for display
                generate_audit_pdf(
                    results=results,
                    source_csv=Path(uploaded_file.name),
                    output_pdf=out_pdf_path,
                )
                pdf_bytes = out_pdf_path.read_bytes()
        except ModuleNotFoundError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            st.error(f"生成 PDF 失败：{e}" if is_cn else f"Failed to generate PDF: {e}")
            st.stop()
        progress.progress(100, text="审计完成" if is_cn else "Audit completed")

        st.session_state["audit_results"] = results
        st.session_state["pdf_bytes"] = pdf_bytes
        st.session_state["pdf_filename"] = pdf_filename


if st.session_state.get("audit_results") is not None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader(UI["overview"])

    results = st.session_state["audit_results"]
    def _passes_fraud_filter(flags: set[str]) -> bool:
        if fraud_filter in {"仅 HIGH_RISK", "Only HIGH_RISK"}:
            return "HIGH_RISK" in flags
        if fraud_filter in {"仅 DATA_UNREALISTIC", "Only DATA_UNREALISTIC"}:
            return "DATA_UNREALISTIC" in flags
        return bool(flags.intersection({"HIGH_RISK", "DATA_UNREALISTIC"}))

    suspicious = [r for r in results if _passes_fraud_filter(set(getattr(r, "fraud_flags", []) or []))]
    high_risk_geo = [r for r in results if "HIGH_RISK" in (getattr(r, "fraud_flags", []) or [])]

    compliant = sum(1 for r in results if r.status == "COMPLIANT")
    non_compliant = sum(1 for r in results if r.status == "NON_COMPLIANT")
    required_total = compliant + non_compliant
    compliance_ratio = (compliant / required_total) if required_total > 0 else 0.0
    carbon_values = [
        (r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value")
        for r in results
    ]
    carbon_values = [v for v in carbon_values if isinstance(v, (int, float))]
    avg_carbon = sum(carbon_values) / len(carbon_values) if carbon_values else 0.0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("总合规率" if is_cn else "Overall Compliance Rate", f"{compliance_ratio:.1%}")
    with c2:
        st.metric("平均碳足迹" if is_cn else "Average Carbon Footprint", f"{avg_carbon:.2f}")
    with c3:
        st.metric("风险预警数" if is_cn else "Risk Alerts", len(suspicious))

    # Commercial charts
    try:
        import plotly.express as px
        status_counts = {
            "COMPLIANT": compliant,
            "NON_COMPLIANT": non_compliant,
            "NOT_REQUIRED_DPP": sum(1 for r in results if r.status == "NOT_REQUIRED_DPP"),
        }
        pie_df = pd.DataFrame(
            [{"status": k, "count": v} for k, v in status_counts.items() if v > 0]
        )
        if not pie_df.empty:
            fig_pie = px.pie(
                pie_df,
                values="count",
                names="status",
                hole=0.58,
                title="审计结果结构 / Compliance Mix" if is_cn else "Compliance Mix",
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        compare_rows = []
        for r in results:
            li = (r.metrics.get("recycled_lithium_pct", {}) or {}).get("value")
            co = (r.metrics.get("recycled_cobalt_pct", {}) or {}).get("value")
            ni = (r.metrics.get("recycled_nickel_pct", {}) or {}).get("value")
            for mat, val, threshold in [
                ("Lithium", li, RECYCLED_MIN_PCT["Lithium"]),
                ("Cobalt", co, RECYCLED_MIN_PCT["Cobalt"]),
                ("Nickel", ni, RECYCLED_MIN_PCT["Nickel"]),
            ]:
                if isinstance(val, (int, float)):
                    compare_rows.append(
                        {
                            "model": r.model,
                            "material": mat,
                            "gap_vs_threshold": float(val) - float(threshold),
                        }
                    )
        if compare_rows:
            cmp_df = pd.DataFrame(compare_rows)
            fig_bar = px.bar(
                cmp_df,
                x="model",
                y="gap_vs_threshold",
                color="material",
                barmode="group",
                title="回收比例与法案阈值差距（Li/Co/Ni）" if is_cn else "Recycled Content Gap vs Legal Threshold (Li/Co/Ni)",
                labels={"gap_vs_threshold": "当前值-阈值 (%)" if is_cn else "Current - Threshold (%)", "model": "型号" if is_cn else "Model"},
            )
            fig_bar.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig_bar, use_container_width=True)
    except Exception:
        st.info("Plotly 图表暂不可用，已回退基础展示。" if is_cn else "Plotly chart unavailable; using basic view.")

    # Horizontal chart for suspicious models.
    st.markdown("#### 风险侦测图 / Fraud-Risk Focus" if is_cn else "#### Fraud-Risk Focus")
    suspicious_rows = []
    for r in suspicious:
        flags = set(getattr(r, "fraud_flags", []) or [])
        score = 0
        if "HIGH_RISK" in flags:
            score += 1
        if "DATA_UNREALISTIC" in flags:
            score += 1
        suspicious_rows.append({"model": r.model, "risk_score": score, "flags": ", ".join(sorted(flags))})

    if suspicious_rows:
        try:
            import plotly.express as px

            df = pd.DataFrame(suspicious_rows).sort_values("risk_score", ascending=True)
            fig = px.bar(
                df,
                x="risk_score",
                y="model",
                orientation="h",
                color="flags",
                title="High Risk / Data Unrealistic by Model",
                labels={"risk_score": "异常标签数量", "model": "型号"},
            )
            fig.update_layout(height=320, margin=dict(l=20, r=20, t=45, b=20))
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            # Fallback when Plotly is unavailable.
            st.bar_chart(pd.DataFrame(suspicious_rows).set_index("model")["risk_score"])
    else:
        st.info("当前批次未发现疑似造假或高风险样本。")

    st.divider()
    st.subheader(UI["result_title"])
    display_results = results
    if only_suspicious:
        display_results = suspicious
    _render_results_table(display_results)

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    if st.session_state.get("pdf_bytes") is not None:
        st.download_button(
            label=UI["download_pdf"],
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state.get("pdf_filename") or "DPP_Audit_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    else:
        st.warning("未找到可下载的 PDF。" if is_cn else "No downloadable PDF found.")

    st.markdown("</div>", unsafe_allow_html=True)

