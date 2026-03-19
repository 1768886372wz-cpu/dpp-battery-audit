import csv
import hashlib
import os
import tempfile
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

from dpp_engine import generate_audit_pdf, validate_record


st.set_page_config(
    page_title="中资出海电池 DPP 合规预审计平台",
    layout="wide",
)


st.markdown(
    """
<style>
body { background: #F7F8FA; }
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

st.markdown('<div class="main-title">中资出海电池 DPP 合规预审计平台</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">上传电池数据表，进行欧盟 2023/1542 电池 DPP 合规预审计并生成报告</div>', unsafe_allow_html=True)


def _parse_csv_bytes(csv_bytes: bytes) -> List[Dict[str, str]]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(text))
    return [row for row in reader]


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


uploaded_file = st.sidebar.file_uploader("上传 CSV 文件", type=["csv"])

if uploaded_file is None:
    st.markdown('<div class="card small">请在左侧上传一个电池数据 CSV 文件。</div>', unsafe_allow_html=True)
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
    st.subheader("上传数据预览（Model 级别输入）")
    st.dataframe(csv_rows, use_container_width=True, height=280)

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
    start_clicked = st.button("开始 AI 审计", type="primary", use_container_width=True)

with help_col:
    st.markdown('<div class="small">将调用本地校验逻辑并生成 PDF。</div>', unsafe_allow_html=True)


if start_clicked:
    with st.spinner("正在审计并生成报告..."):
        try:
            results = [validate_record(row) for row in csv_rows]
        except Exception as e:
            st.error(f"审计失败：{e}")
            st.stop()

        # Generate PDF to a temporary file, then read bytes for download
        pdf_bytes = None
        pdf_filename = "DPP_Audit_Report.pdf"
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
            st.error(f"生成 PDF 失败：{e}")
            st.stop()

        st.session_state["audit_results"] = results
        st.session_state["pdf_bytes"] = pdf_bytes
        st.session_state["pdf_filename"] = pdf_filename


if st.session_state.get("audit_results") is not None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("审计概览 / Audit Overview")

    results = st.session_state["audit_results"]
    compliant = sum(1 for r in results if r.status == "COMPLIANT")
    non_compliant = sum(1 for r in results if r.status == "NON_COMPLIANT")
    required_total = compliant + non_compliant

    if required_total > 0:
        compliance_ratio = compliant / required_total
        st.metric("合规比例（强制执行样本）", f"{compliance_ratio:.1%}", delta=None)
        st.bar_chart(
            {"COMPLIANT / 合规 (%)": [compliance_ratio * 100], "NON_COMPLIANT / 不合规 (%)": [(1 - compliance_ratio) * 100]}
        )
    else:
        st.info("本次上传中没有强制执行 DPP 的样本（例如：工业电池容量 <= 2 kWh）。")

    not_required = sum(1 for r in results if r.status == "NOT_REQUIRED_DPP")
    st.caption(f"不强制执行 DPP 样本数：{not_required}")

    st.divider()
    st.subheader("审计结果（Model 级别）")
    _render_results_table(results)

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    if st.session_state.get("pdf_bytes") is not None:
        st.download_button(
            label="下载 PDF 审计报告",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state.get("pdf_filename") or "DPP_Audit_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    else:
        st.warning("未找到可下载的 PDF。")

    st.markdown("</div>", unsafe_allow_html=True)

