"""DPP-Expert 3.0 — Enterprise EU Battery Compliance Portal
Requires:  streamlit pandas plotly reportlab pypdf
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import time
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from dpp_engine import RECYCLED_MIN_PCT, generate_audit_pdf, validate_record

# ── Home-dir redirect so Streamlit can write its config ──────────────────────
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
    return [row for row in csv.DictReader(StringIO(text))]


# ── Translations ──────────────────────────────────────────────────────────────
TRANSLATIONS: Dict[str, Dict[str, Any]] = {
    "zh": {
        # sidebar
        "lang_select": "语言 / Language",
        "lang_zh": "中文界面",
        "lang_en": "English Interface",
        "client_name": "客户名称",
        "project_code": "项目编号",
        "report_no": "报告编号",
        "upload_csv": "📂 上传 CSV 文件",
        "filter_fraud": "🚨 仅高风险/疑似造假",
        "anomaly_filter": "异常类型筛选",
        "af_all": "全部异常",
        "af_high": "仅 HIGH_RISK",
        "af_unreal": "仅 DATA_UNREALISTIC",
        # tabs
        "tab_dash": "📊 战略仪表盘",
        "tab_audit": "🛡 合规审计中心",
        "tab_map": "🌍 供应链溯源地图",
        "tab_law": "📚 法规知识库",
        "tab_about": "🏢 关于与支持",
        # dashboard
        "dash_welcome": "欢迎来到中资出海电池 DPP 合规管理门户",
        "dash_sub": "EU 2023/1542 · Digital Product Passport · Pre-Audit Intelligence",
        "dash_kpi1": "当前批次合规率",
        "dash_kpi2": "平均碳强度 (kg CO₂e)",
        "dash_kpi3": "高风险矿点预警",
        "dash_kpi4": "供应链透明度得分",
        "dash_radar_title": "合规六维雷达图",
        "dash_no_data": "请先在「合规审计中心」上传并运行审计，仪表盘将自动刷新。",
        # auditor
        "preview": "📋 数据预览",
        "manual_entry": "✏️ 单条快速审计",
        "run_audit": "🚀 开始 AI 深度审计",
        "running": "AI 正在执行深度法律检索与字段比对...",
        "progress_steps": [
            "正在解析字段映射与法规数据库...",
            "正在比对回收材料比例阈值...",
            "正在执行碳足迹物理合理性校验...",
            "正在运行坐标溯源风险扫描...",
            "正在生成合规风险等级评定...",
            "正在渲染 PDF 审计报告...",
        ],
        "done": "✅ 审计完成",
        "metric_rate": "总合规率",
        "metric_carbon": "平均碳足迹",
        "metric_risk": "风险预警数",
        "chart_mix": "合规结构分布",
        "chart_gap": "回收比例 vs 法案阈值（锂/钴/镍）",
        "result_table": "📑 审计结果详情",
        "expand_legal": "查看法条原文引用",
        "download_pdf": "⬇️ 下载 PDF 审计报告",
        "status_col": "判定结果",
        "risk_col": "风险等级",
        "reason_col": "问题摘要",
        "model_col": "型号",
        "manual_submit": "▶ 提交单条审计",
        "manual_result": "单条审计结果",
        "upload_hint": "请在左侧边栏上传 CSV 文件后点击审计按钮。",
        # map
        "map_title": "全球矿山坐标溯源地图",
        "map_sub": "绿色 = 已知矿区  •  红色 = 高风险 / 坐标异常",
        "map_no_data": "请先运行审计以加载矿山坐标数据。",
        # law
        "law_title": "EU 2023/1542 核心条文解读",
        "law_official_link": "🔗 跳转欧盟官方法规原文",
        "law_articles": {
            "Article 7 — 碳足迹声明": {
                "en_title": "Article 7 — Carbon Footprint",
                "zh": (
                    "**核心要求：** 电动汽车电池、LMT 电池及容量 > 2 kWh 的工业电池，须附有碳足迹声明（Carbon Footprint Declaration），"
                    "涵盖生命周期各阶段（原材料获取、制造、运输、回收）的 CO₂ 当量排放总量。\n\n"
                    "**关键节点：** 碳足迹性能等级（Performance Class）标签要求从 2026 年起生效，"
                    "最大碳足迹阈值（Maximum Threshold）由欧盟委员会通过授权法案另行规定。\n\n"
                    "**审计意义：** 缺少 carbon_footprint_total_kg_co2e 字段或数值低于同类化学体系物理下限，"
                    "将触发 DATA_UNREALISTIC 或 NON_COMPLIANT 判定。"
                ),
                "en": (
                    "**Core Requirement:** EV batteries, LMT batteries, and industrial batteries > 2 kWh must carry a Carbon Footprint Declaration "
                    "covering CO₂-equivalent emissions across all lifecycle stages (raw material extraction, manufacturing, transport, end-of-life).\n\n"
                    "**Key Milestones:** Carbon footprint performance-class labels apply from 2026; maximum threshold values will be set by delegated acts.\n\n"
                    "**Audit Relevance:** Missing carbon_footprint_total_kg_co2e or values below the chemistry-specific physical floor "
                    "trigger DATA_UNREALISTIC or NON_COMPLIANT findings."
                ),
                "quote": (
                    '"The carbon footprint of an EV battery shall be calculated in accordance with the methodology set out in Annex II '
                    'and shall cover the life cycle stages listed in Annex II, Part A." — Art. 7(1)'
                ),
            },
            "Article 8 — 回收材料比例": {
                "en_title": "Article 8 — Recycled Content",
                "zh": (
                    "**强制阈值（2027 年目标）：**\n"
                    "- 锂 (Lithium) ≥ **6%**\n"
                    "- 钴 (Cobalt) ≥ **16%**\n"
                    "- 镍 (Nickel) ≥ **6%**\n"
                    "- 铅 (Lead) ≥ **85%**\n\n"
                    "**核心要求：** 制造商须证明所使用的回收材料达到上述最低比例，并提供经第三方核验的计算方法与证据链。\n\n"
                    "**审计意义：** 任一金属低于阈值，判定为 NON_COMPLIANT（严重违规），引用 Article 8(2)(a)-(d)。"
                ),
                "en": (
                    "**Mandatory Thresholds (2027 target):**\n"
                    "- Lithium ≥ **6%**\n"
                    "- Cobalt ≥ **16%**\n"
                    "- Nickel ≥ **6%**\n"
                    "- Lead ≥ **85%**\n\n"
                    "**Core Requirement:** Manufacturers must demonstrate that the batteries they place on the market contain "
                    "at least the minimum shares of recycled content for each regulated material.\n\n"
                    "**Audit Relevance:** Any material below threshold → NON_COMPLIANT citing Article 8(2)(a)-(d)."
                ),
                "quote": (
                    '"Economic operators placing batteries on the Union market shall ensure that those batteries contain, '
                    'as of 18 February 2031, a minimum share of cobalt, lead, lithium and nickel recovered from battery waste." — Art. 8(1)'
                ),
            },
            "Article 14 — BMS 访问与健康状态": {
                "en_title": "Article 14 — BMS Access & State of Health",
                "zh": (
                    "**核心要求：** EV 电池须提供对电池管理系统（BMS）读写访问权限的说明，"
                    "使授权运营商（修理商、再制造商、再利用商）能够评估电池的健康状态（SoH）和剩余使用寿命（RUL）。\n\n"
                    "**审计意义：** bms_access_permissions 字段若缺少写访问说明（如仅填 'read only'），"
                    "将触发 NON_COMPLIANT 判定，引用 Article 14。"
                ),
                "en": (
                    "**Core Requirement:** EV batteries must provide disclosure of BMS read/write access permissions, "
                    "enabling authorised operators (repairers, re-manufacturers, re-users) to assess State of Health (SoH) and Remaining Useful Life (RUL).\n\n"
                    "**Audit Relevance:** bms_access_permissions missing write-access disclosure (e.g., 'read only') "
                    "triggers NON_COMPLIANT citing Article 14."
                ),
                "quote": (
                    '"The information referred to in paragraph 1 shall be made available free of charge and in a non-discriminatory manner '
                    'to battery users, independent aggregators, electricity service providers, and operators of recharging points." — Art. 14(3)'
                ),
            },
            "Article 77 — 电池护照系统": {
                "en_title": "Article 77 — Battery Passport",
                "zh": (
                    "**强制时间：** 自 **2027 年 2 月 18 日** 起，EV 电池、LMT 电池及容量 > 2 kWh 的工业电池须具备电池护照。\n\n"
                    "**唯一标识符：** 护照须通过 QR 码链接至唯一标识符，可在线访问所有必填字段（Annex XIII）。\n\n"
                    "**数据准确性：** 经济运营商须确保护照中的信息准确、完整且及时更新（Art. 77(4)）。\n\n"
                    "**审计意义：** unique_identifier 缺失或 manufacturer_id 格式不符，判定为 NON_COMPLIANT。"
                ),
                "en": (
                    "**Mandatory Date:** From **18 February 2027**, EV batteries, LMT batteries, and industrial batteries > 2 kWh must have a battery passport.\n\n"
                    "**Unique Identifier:** Each passport is linked via QR code to a unique identifier giving online access to all Annex XIII fields.\n\n"
                    "**Data Accuracy:** Economic operators must ensure passport data is accurate, complete and up to date (Art. 77(4)).\n\n"
                    "**Audit Relevance:** Missing unique_identifier or non-compliant manufacturer_id format → NON_COMPLIANT."
                ),
                "quote": (
                    '"As of 18 February 2027, EV batteries, light means of transport batteries and industrial batteries with a capacity of more than 2 kWh '
                    'shall have a battery passport." — Art. 77(1)'
                ),
            },
            "Annex XIII — 护照数据要求": {
                "en_title": "Annex XIII — Battery Passport Data Requirements",
                "zh": (
                    "**四大模块：**\n"
                    "1. **公共信息（Part A）：** 制造商、生产地、生产日期、电池类别、唯一标识符、QR 码。\n"
                    "2. **材料与合规（Part B）：** 危险物质声明、关键原材料声明、化学成分、回收比例证明。\n"
                    "3. **性能与耐久性（Part C）：** 额定容量、标称电压、充放电效率、预期寿命、热管理规格。\n"
                    "4. **碳足迹信息（Part D，Article 7）：** 各生命周期阶段的碳排放细分及总量。\n\n"
                    "**审计意义：** 本平台的 DPP_FIELD_MAP 直接映射 Annex XIII 四大模块，逐字段核验。"
                ),
                "en": (
                    "**Four Modules:**\n"
                    "1. **Public Information (Part A):** Manufacturer, manufacturing place/date, category, unique identifier, QR code.\n"
                    "2. **Materials & Compliance (Part B):** Hazardous substance declaration, critical raw materials, chemistry, recycled-content proof.\n"
                    "3. **Performance & Durability (Part C):** Rated capacity, nominal voltage, charge/discharge efficiency, expected lifetime, thermal specs.\n"
                    "4. **Carbon Footprint (Part D, Article 7):** Per-lifecycle-stage breakdown and total CO₂-equivalent emissions.\n\n"
                    "**Audit Relevance:** The DPP_FIELD_MAP in this platform directly mirrors Annex XIII's four modules for field-by-field validation."
                ),
                "quote": (
                    '"A battery passport shall be established for each battery model per manufacturing plant '
                    'and shall include the information listed in this Annex." — Annex XIII, Preamble'
                ),
            },
        },
        # about
        "about_title": "关于本平台 & 出海支持",
        "about_desc": (
            "本平台由**中英低空经济与可持续发展研究小组**支持开发，面向计划进入欧盟市场的中资电池制造商，"
            "提供基于 **EU 2023/1542** 法案的预审计合规分析服务。"
        ),
        "about_refs": "📎 核心参考标准",
        "about_ref_items": [
            "EU 2023/1542 — EU Battery Regulation (Official Journal, 28 Jul 2023)",
            "GBA Battery Passport — Global Battery Alliance Passport Standard v1.0",
            "JRC Technical Report — Carbon Footprint Methodology for EV Batteries",
            "OECD Due Diligence Guidance — Responsible Business Conduct for Minerals",
        ],
        "about_disclaimer_title": "⚠️ 免责声明 / Disclaimer",
        "about_disclaimer": (
            "本工具为**预审计研究工具**，仅供合规分析参考，所有判定结果均基于用户提供的数据字段进行自动化校验。"
            "**最终市场准入以欧盟授权机构的官方认证结论为准。**\n\n"
            "This tool is a **pre-audit research instrument** for compliance analysis reference only. "
            "All findings are based on automated validation of user-supplied data. "
            "**Final market access decisions rest with EU-authorised conformity assessment bodies.**"
        ),
        "about_contact": "📬 联系支持团队",
        "about_contact_body": "如需专业合规咨询或定制化 DPP 数据治理方案，请联系研究小组。",
    },
    "en": {
        "lang_select": "Language / 语言",
        "lang_zh": "中文界面",
        "lang_en": "English Interface",
        "client_name": "Client Name",
        "project_code": "Project Code",
        "report_no": "Report No.",
        "upload_csv": "📂 Upload CSV File",
        "filter_fraud": "🚨 High-risk / Suspicious only",
        "anomaly_filter": "Anomaly Filter",
        "af_all": "All anomalies",
        "af_high": "HIGH_RISK only",
        "af_unreal": "DATA_UNREALISTIC only",
        "tab_dash": "📊 Executive Dashboard",
        "tab_audit": "🛡 Compliance Auditor",
        "tab_map": "🌍 Traceability Map",
        "tab_law": "📚 Regulatory Library",
        "tab_about": "🏢 About & Support",
        "dash_welcome": "Welcome to the Battery DPP Compliance Management Portal",
        "dash_sub": "EU 2023/1542 · Digital Product Passport · Pre-Audit Intelligence",
        "dash_kpi1": "Batch Compliance Rate",
        "dash_kpi2": "Avg Carbon Intensity (kg CO₂e)",
        "dash_kpi3": "High-Risk Mine Alerts",
        "dash_kpi4": "Supply Chain Transparency",
        "dash_radar_title": "6-Dimension Compliance Radar",
        "dash_no_data": "Run an audit in the Compliance Auditor tab — the dashboard will refresh automatically.",
        "preview": "📋 Data Preview",
        "manual_entry": "✏️ Single Record Quick Audit",
        "run_audit": "🚀 Start AI Deep Audit",
        "running": "AI is performing deep legal retrieval and field validation...",
        "progress_steps": [
            "Parsing field mappings and regulatory database...",
            "Comparing recycled-material ratios against thresholds...",
            "Running carbon footprint physical plausibility check...",
            "Scanning mine coordinate sourcing risk...",
            "Generating compliance risk ratings...",
            "Rendering PDF audit report...",
        ],
        "done": "✅ Audit complete",
        "metric_rate": "Overall Compliance Rate",
        "metric_carbon": "Average Carbon Footprint",
        "metric_risk": "Risk Alerts",
        "chart_mix": "Compliance Mix",
        "chart_gap": "Recycled Content Gap vs Legal Threshold (Li/Co/Ni)",
        "result_table": "📑 Audit Results",
        "expand_legal": "View legal citation",
        "download_pdf": "⬇️ Download PDF Audit Report",
        "status_col": "Status",
        "risk_col": "Risk Level",
        "reason_col": "Issue Summary",
        "model_col": "Model",
        "manual_submit": "▶ Run Single Audit",
        "manual_result": "Single Audit Result",
        "upload_hint": "Upload a CSV file in the sidebar and click the audit button.",
        "map_title": "Global Mine Coordinate Traceability Map",
        "map_sub": "Green = known mining zone  •  Red = high-risk / anomalous coordinates",
        "map_no_data": "Run an audit first to load mine coordinate data.",
        "law_title": "EU 2023/1542 Key Article Reference",
        "law_official_link": "🔗 EU Official Journal — Full Text",
        "law_articles": {
            "Article 7 — Carbon Footprint": {
                "en_title": "Article 7 — Carbon Footprint",
                "zh": "",
                "en": (
                    "**Core Requirement:** EV batteries, LMT batteries, and industrial batteries > 2 kWh must carry a Carbon Footprint Declaration "
                    "covering CO₂-equivalent emissions across all lifecycle stages.\n\n"
                    "**Mandatory from 2026:** Performance-class labels; threshold values set by delegated acts.\n\n"
                    "**Audit Relevance:** Missing carbon_footprint_total_kg_co2e or value below physics floor → DATA_UNREALISTIC / NON_COMPLIANT."
                ),
                "quote": '"The carbon footprint of an EV battery shall be calculated in accordance with the methodology set out in Annex II." — Art. 7(1)',
            },
            "Article 8 — Recycled Content": {
                "en_title": "Article 8 — Recycled Content",
                "zh": "",
                "en": (
                    "**Mandatory Thresholds (2027):** Lithium ≥ 6%, Cobalt ≥ 16%, Nickel ≥ 6%, Lead ≥ 85%.\n\n"
                    "**Core Requirement:** Manufacturers must demonstrate minimum recycled shares with auditable evidence.\n\n"
                    "**Audit Relevance:** Below-threshold → NON_COMPLIANT citing Article 8(2)(a)-(d)."
                ),
                "quote": '"Economic operators shall ensure batteries contain minimum shares of recycled cobalt, lead, lithium, and nickel." — Art. 8(1)',
            },
            "Article 14 — BMS Access & State of Health": {
                "en_title": "Article 14 — BMS Access",
                "zh": "",
                "en": (
                    "**Core Requirement:** EV batteries must disclose BMS read/write access for authorised operators assessing SoH and RUL.\n\n"
                    "**Audit Relevance:** Missing write-access in bms_access_permissions → NON_COMPLIANT citing Article 14."
                ),
                "quote": '"The information shall be made available free of charge and in a non-discriminatory manner." — Art. 14(3)',
            },
            "Article 77 — Battery Passport": {
                "en_title": "Article 77 — Battery Passport",
                "zh": "",
                "en": (
                    "**Mandatory:** From 18 February 2027, EV, LMT, and industrial batteries > 2 kWh need a passport.\n\n"
                    "**Unique Identifier:** Accessible via QR code with all Annex XIII fields.\n\n"
                    "**Audit Relevance:** Missing unique_identifier or invalid manufacturer_id → NON_COMPLIANT."
                ),
                "quote": '"As of 18 February 2027, EV batteries, LMT batteries and industrial batteries > 2 kWh shall have a battery passport." — Art. 77(1)',
            },
            "Annex XIII — Passport Data Requirements": {
                "en_title": "Annex XIII — Data Requirements",
                "zh": "",
                "en": (
                    "**Four Modules:** (A) Public info — manufacturer, location, date, ID; "
                    "(B) Materials & compliance — hazardous substances, recycled content; "
                    "(C) Performance — capacity, voltage, efficiency, lifetime; "
                    "(D) Carbon footprint breakdown per lifecycle stage.\n\n"
                    "**Audit Relevance:** DPP_FIELD_MAP mirrors Annex XIII for field-by-field validation."
                ),
                "quote": '"A battery passport shall be established for each battery model per manufacturing plant." — Annex XIII, Preamble',
            },
        },
        "about_title": "About This Platform & Export Support",
        "about_desc": (
            "This platform is supported by the **Sino-British Low-Altitude Economy and Sustainable Development Research Group**, "
            "designed for Chinese battery manufacturers entering the EU market, providing pre-audit compliance analysis "
            "based on **EU 2023/1542**."
        ),
        "about_refs": "📎 Key Reference Standards",
        "about_ref_items": [
            "EU 2023/1542 — EU Battery Regulation (Official Journal, 28 Jul 2023)",
            "GBA Battery Passport — Global Battery Alliance Passport Standard v1.0",
            "JRC Technical Report — Carbon Footprint Methodology for EV Batteries",
            "OECD Due Diligence Guidance — Responsible Business Conduct for Minerals",
        ],
        "about_disclaimer_title": "⚠️ Disclaimer",
        "about_disclaimer": (
            "This tool is a **pre-audit research instrument** for compliance analysis reference only. "
            "All findings are based on automated validation of user-supplied data. "
            "**Final market access decisions rest with EU-authorised conformity assessment bodies.**"
        ),
        "about_contact": "📬 Contact Support",
        "about_contact_body": "For professional compliance consulting or bespoke DPP data-governance solutions, please contact the research group.",
    },
}

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DPP Expert 3.0",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS Theme Injection ───────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* ── Global background & font ── */
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0A192F 0%, #112240 60%, #0D2137 100%);
    color: #CCD6F6;
}
[data-testid="stSidebar"] {
    background: #0D1B2A !important;
    border-right: 1px solid #1E3A5F;
}
[data-testid="stSidebar"] * {
    color: #8892B0 !important;
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label,
[data-testid="stSidebar"] .stFileUploader label {
    color: #64FFDA !important;
    font-weight: 600;
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
/* ── Tab bar ── */
[data-testid="stTabs"] [role="tab"] {
    color: #8892B0;
    font-weight: 600;
    font-size: 0.92rem;
    border-radius: 8px 8px 0 0;
    padding: 0.55rem 1.1rem;
    transition: all 0.25s;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background: #112240;
    color: #64FFDA !important;
    border-bottom: 2px solid #64FFDA;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: #CCD6F6 !important;
    background: #162032;
}
/* ── KPI metric cards ── */
.kpi-card {
    background: #112240;
    border-radius: 14px;
    padding: 1.1rem 1.3rem;
    border: 1px solid #1E3A5F;
    box-shadow: 0 4px 18px rgba(0,0,0,0.35);
    text-align: center;
    transition: transform 0.2s;
}
.kpi-card:hover { transform: translateY(-2px); }
.kpi-label {
    color: #8892B0;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 0.35rem;
}
.kpi-value {
    color: #64FFDA;
    font-size: 2.1rem;
    font-weight: 700;
    line-height: 1.1;
}
.kpi-delta {
    color: #8892B0;
    font-size: 0.77rem;
    margin-top: 0.3rem;
}
/* ── Section headers ── */
.section-header {
    color: #CCD6F6;
    font-size: 1.18rem;
    font-weight: 700;
    border-left: 3px solid #64FFDA;
    padding-left: 0.65rem;
    margin: 1.2rem 0 0.7rem 0;
}
/* ── Welcome banner ── */
.welcome-banner {
    background: linear-gradient(90deg, #112240, #0D2137);
    border-radius: 14px;
    border: 1px solid #1E3A5F;
    padding: 1.6rem 2rem;
    margin-bottom: 1.4rem;
    text-align: center;
}
.welcome-banner h1 {
    color: #64FFDA;
    font-size: 1.75rem;
    font-weight: 800;
    margin: 0 0 0.4rem 0;
}
.welcome-banner p {
    color: #8892B0;
    font-size: 0.88rem;
    margin: 0;
    letter-spacing: 0.04em;
}
/* ── Expander styling ── */
[data-testid="stExpander"] {
    background: #112240;
    border-radius: 10px;
    border: 1px solid #1E3A5F;
    margin-bottom: 0.5rem;
}
[data-testid="stExpander"] summary {
    color: #CCD6F6 !important;
    font-weight: 600;
}
/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
}
/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(90deg, #0A3D62, #1B6CA8);
    color: #CCD6F6;
    border-radius: 10px;
    border: 1px solid #64FFDA44;
    font-weight: 700;
    letter-spacing: 0.04em;
    transition: all 0.25s;
}
.stButton > button:hover {
    background: linear-gradient(90deg, #64FFDA, #43C6AC);
    color: #0A192F;
    border-color: #64FFDA;
}
/* ── Download button ── */
.stDownloadButton > button {
    background: linear-gradient(90deg, #064420, #1B5E20);
    color: #A5D6A7;
    border-radius: 10px;
    border: 1px solid #4CAF5044;
    font-weight: 700;
}
/* ── Law card ── */
.law-card {
    background: #0D1B2A;
    border: 1px solid #1E3A5F;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.7rem;
}
.law-quote {
    background: #0A2040;
    border-left: 3px solid #64FFDA;
    border-radius: 0 8px 8px 0;
    padding: 0.7rem 1rem;
    font-style: italic;
    color: #8892B0;
    font-size: 0.85rem;
    margin-top: 0.8rem;
}
/* ── Disclaimer ── */
.disclaimer-box {
    background: #1A0A0A;
    border: 1px solid #7F1D1D;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    color: #FCA5A5;
    font-size: 0.87rem;
    line-height: 1.65;
}
/* ── Markdown text ── */
.stMarkdown p { color: #CCD6F6; }
</style>
""",
    unsafe_allow_html=True,
)

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
    client_name = (st.text_input(t["client_name"], value="Demo Client") or "Demo Client").strip()
    project_code = (st.text_input(t["project_code"], value="DPP-2026-PRE") or "DPP-2026-PRE").strip()
    report_no = f"{project_code}-{_hash_bytes((client_name + project_code).encode())[:8].upper()}"
    st.caption(f"{t['report_no']}: `{report_no}`")

    st.divider()
    uploaded_file = st.file_uploader(t["upload_csv"], type=["csv"])
    only_suspicious = st.toggle(t["filter_fraud"], value=False)
    fraud_filter = st.selectbox(t["anomaly_filter"], [t["af_all"], t["af_high"], t["af_unreal"]], index=0)

# ── Tab Layout ────────────────────────────────────────────────────────────────
tab_dash, tab_audit, tab_map, tab_law, tab_about = st.tabs(
    [t["tab_dash"], t["tab_audit"], t["tab_map"], t["tab_law"], t["tab_about"]]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown(
        f"<div class='welcome-banner'>"
        f"<h1>{t['dash_welcome']}</h1>"
        f"<p>{t['dash_sub']}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    results_cached = st.session_state.get("audit_results")

    # ── KPI Cards ──
    if results_cached:
        import plotly.graph_objects as go

        results = results_cached
        compliant = sum(1 for r in results if r.status == "COMPLIANT")
        non = sum(1 for r in results if r.status == "NON_COMPLIANT")
        total_req = compliant + non
        compliance_rate = compliant / total_req if total_req else 0

        carbon_vals = [
            (r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value")
            for r in results
        ]
        carbon_vals = [v for v in carbon_vals if isinstance(v, (int, float))]
        avg_carbon = sum(carbon_vals) / len(carbon_vals) if carbon_vals else 0.0

        high_risk_count = sum(
            1 for r in results if "HIGH_RISK" in (r.fraud_flags or [])
        )

        # Transparency score: fraction of records with uid + mine coords + chemistry
        def _has_field(r, key: str) -> bool:
            return (r.metrics.get(key, {}) or {}).get("met") is True

        transparency_scores = [
            sum(
                1
                for k in ["unique_identifier", "carbon_footprint_total_kg_co2e", "mine_coordinates"]
                if _has_field(r, k)
            )
            / 3
            for r in results
            if r.status in {"COMPLIANT", "NON_COMPLIANT"}
        ]
        transparency = sum(transparency_scores) / len(transparency_scores) if transparency_scores else 0

        c1, c2, c3, c4 = st.columns(4)
        kpi_data = [
            (c1, t["dash_kpi1"], f"{compliance_rate:.1%}", "vs EU 2027 mandatory threshold"),
            (c2, t["dash_kpi2"], f"{avg_carbon:.0f}", "EU benchmark ≈ 100 kg CO₂e/kWh"),
            (c3, t["dash_kpi3"], str(high_risk_count), "OECD Due Diligence zone check"),
            (c4, t["dash_kpi4"], f"{transparency:.0%}", "UID + Carbon + Coordinates coverage"),
        ]
        for col, label, value, delta in kpi_data:
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

        # ── Compliance Radar ──
        st.markdown(f"<div class='section-header'>{t['dash_radar_title']}</div>", unsafe_allow_html=True)

        def _dim_score(metric_keys: List[str]) -> float:
            mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
            if not mandatory:
                return 0.0
            met = sum(
                1
                for r in mandatory
                if all((r.metrics.get(k, {}) or {}).get("met") is True for k in metric_keys)
            )
            return met / len(mandatory)

        dims = ["Safety", "Environmental", "Traceability", "Recycled Mat.", "Performance", "BMS Access"]
        scores = [
            _dim_score(["extinguishing_agent", "thermal_runaway_prevention", "explosion_proof_declaration"]),
            _dim_score(["carbon_footprint_total_kg_co2e", "carbon_physical_plausibility"]),
            _dim_score(["unique_identifier", "manufacturer_id", "mine_coordinates"]),
            _dim_score(["recycled_lithium_pct", "recycled_cobalt_pct", "recycled_nickel_pct", "recycled_lead_pct"]),
            _dim_score(["rated_capacity_ah", "nominal_voltage_v", "rated_power_w", "expected_lifetime_cycles"]),
            _dim_score(["bms_access_permissions"]),
        ]

        fig_radar = go.Figure()
        fig_radar.add_trace(
            go.Scatterpolar(
                r=scores + [scores[0]],
                theta=dims + [dims[0]],
                fill="toself",
                fillcolor="rgba(100,255,218,0.18)",
                line=dict(color="#64FFDA", width=2),
                name="Compliance Score",
            )
        )
        fig_radar.update_layout(
            polar=dict(
                bgcolor="#0D1B2A",
                radialaxis=dict(visible=True, range=[0, 1], color="#8892B0", gridcolor="#1E3A5F", tickfont=dict(color="#8892B0")),
                angularaxis=dict(color="#CCD6F6", gridcolor="#1E3A5F"),
            ),
            paper_bgcolor="#112240",
            plot_bgcolor="#112240",
            font=dict(color="#CCD6F6"),
            showlegend=False,
            margin=dict(t=30, b=30, l=60, r=60),
            height=380,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    else:
        st.info(t["dash_no_data"])

        # Show placeholder KPI cards
        c1, c2, c3, c4 = st.columns(4)
        placeholders = [
            (c1, t["dash_kpi1"], "—", "Upload data to compute"),
            (c2, t["dash_kpi2"], "—", "EU benchmark ≈ 100 kg CO₂e/kWh"),
            (c3, t["dash_kpi3"], "—", "OECD zone check"),
            (c4, t["dash_kpi4"], "—", "UID + Carbon + Coordinates"),
        ]
        for col, label, value, delta in placeholders:
            with col:
                st.markdown(
                    f"<div class='kpi-card'>"
                    f"<div class='kpi-label'>{label}</div>"
                    f"<div class='kpi-value'>{value}</div>"
                    f"<div class='kpi-delta'>{delta}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPLIANCE AUDITOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_audit:

    # ── CSV preview ──
    csv_rows: List[Dict[str, str]] = []
    if uploaded_file is not None:
        csv_bytes = uploaded_file.getvalue()
        csv_hash = _hash_bytes(csv_bytes)
        if st.session_state.get("csv_hash") != csv_hash:
            st.session_state["csv_hash"] = csv_hash
            st.session_state["csv_rows"] = _parse_csv_bytes(csv_bytes)
            st.session_state["audit_results"] = None
            st.session_state["pdf_bytes"] = None
            st.session_state["pdf_filename"] = None
        csv_rows = st.session_state["csv_rows"]
        st.markdown(f"<div class='section-header'>{t['preview']}</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(csv_rows), use_container_width=True, height=220)

    # ── Manual Single Entry Form ──
    st.markdown(f"<div class='section-header'>{t['manual_entry']}</div>", unsafe_allow_html=True)
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
            li = st.number_input("recycled_lithium_pct (%)", min_value=0.0, max_value=100.0, value=8.0)
            co = st.number_input("recycled_cobalt_pct (%)", min_value=0.0, max_value=100.0, value=16.0)
            ni = st.number_input("recycled_nickel_pct (%)", min_value=0.0, max_value=100.0, value=6.0)
            pb = st.number_input("recycled_lead_pct (%)", min_value=0.0, max_value=100.0, value=85.0)
            carbon = st.number_input("carbon_footprint_total_kg_co2e", min_value=0.0, value=120.0)
        submitted = st.form_submit_button(t["manual_submit"], use_container_width=True)

    if submitted:
        single_rec: Dict[str, Any] = {
            "model": model, "category": category, "capacity_kwh": capacity_kwh,
            "manufacturer": manufacturer, "manufacturer_id": manufacturer_id,
            "unique_identifier": unique_identifier, "battery_id": battery_id,
            "manufacture_place": manufacture_place, "manufacture_date": manufacture_date,
            "chemistry": chemistry,
            "recycled_lithium_pct": li, "recycled_cobalt_pct": co,
            "recycled_nickel_pct": ni, "recycled_lead_pct": pb,
            "hazardous_substances_declaration": "declared",
            "rated_capacity_ah": 180, "nominal_voltage_v": 3.7, "rated_power_w": 600,
            "self_discharge_rate_pct_per_month": 2.0,
            "charge_discharge_efficiency_percent": 92, "expected_lifetime_cycles": 1400,
            "thermal_runaway_prevention": "yes", "extinguishing_agent": "CO2",
            "explosion_proof_declaration": "yes", "bms_access_permissions": "read+write",
            "mine_latitude": -11.68, "mine_longitude": 27.5,
            "carbon_footprint_total_kg_co2e": carbon,
        }
        r = validate_record(single_rec)
        st.markdown(f"<div class='section-header'>{t['manual_result']}</div>", unsafe_allow_html=True)
        status_color = "#64FFDA" if r.status == "COMPLIANT" else ("#FF6B6B" if r.status == "NON_COMPLIANT" else "#8892B0")
        st.markdown(
            f"<div class='kpi-card' style='text-align:left;'>"
            f"<span style='color:{status_color};font-weight:700;font-size:1.1rem;'>{r.status}</span> &nbsp;|&nbsp; "
            f"Risk: <b>{r.risk_level}</b><br/>"
            f"<span style='color:#8892B0;font-size:0.82rem;'>"
            + (" | ".join(r.issues[:3]) if r.issues else "No issues") +
            f"</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Audit Button ──
    if st.button(t["run_audit"], type="primary", use_container_width=True, disabled=uploaded_file is None):
        if uploaded_file is None:
            st.warning(t["upload_hint"])
        else:
            progress_bar = st.progress(0)
            steps = t["progress_steps"]
            for i, step in enumerate(steps):
                progress_bar.progress(int((i + 1) / len(steps) * 90), text=step)
                time.sleep(0.12)

            results = [validate_record(row) for row in csv_rows]
            st.session_state["audit_results"] = results

            safe_client = "".join(c for c in client_name if c.isalnum() or c in "-_").strip() or "Client"
            safe_proj = "".join(c for c in project_code if c.isalnum() or c in "-_").strip() or "Project"
            pdf_filename = f"DPP_Audit_Report_{safe_client}_{safe_proj}.pdf"

            progress_bar.progress(95, text=steps[-1])
            pdf_bytes = generate_audit_pdf(
                results,
                lang,
                report_no,
                client_name,
                project_code,
            )
            st.session_state["pdf_bytes"] = pdf_bytes
            st.session_state["pdf_filename"] = pdf_filename

            progress_bar.progress(100, text=t["done"])
            time.sleep(0.3)
            progress_bar.empty()
            st.success(t["done"])

    # ── Results ──
    if st.session_state.get("audit_results"):
        results = st.session_state["audit_results"]

        def _passes_fraud_filter(flags: List[str]) -> bool:
            fset = set(flags or [])
            if fraud_filter == t["af_high"]:
                return "HIGH_RISK" in fset
            if fraud_filter == t["af_unreal"]:
                return "DATA_UNREALISTIC" in fset
            return bool(fset & {"HIGH_RISK", "DATA_UNREALISTIC"})

        suspicious = [r for r in results if _passes_fraud_filter(r.fraud_flags or [])]
        display = suspicious if only_suspicious else results

        compliant = sum(1 for r in results if r.status == "COMPLIANT")
        non = sum(1 for r in results if r.status == "NON_COMPLIANT")
        ratio = compliant / (compliant + non) if (compliant + non) else 0
        c_vals = [(r.metrics.get("carbon_footprint_total_kg_co2e", {}) or {}).get("value") for r in results]
        c_vals = [v for v in c_vals if isinstance(v, (int, float))]
        avg_cf = sum(c_vals) / len(c_vals) if c_vals else 0.0

        col1, col2, col3 = st.columns(3)
        for col, label, val in [
            (col1, t["metric_rate"], f"{ratio:.1%}"),
            (col2, t["metric_carbon"], f"{avg_cf:.1f}"),
            (col3, t["metric_risk"], str(len(suspicious))),
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
                    "Count": [
                        sum(1 for r in results if r.status == "COMPLIANT"),
                        sum(1 for r in results if r.status == "NON_COMPLIANT"),
                        sum(1 for r in results if r.status == "NOT_REQUIRED_DPP"),
                    ],
                })
                fig1 = px.pie(
                    mix[mix["Count"] > 0],
                    names="Status",
                    values="Count",
                    hole=0.55,
                    title=t["chart_mix"],
                    color="Status",
                    color_discrete_map={
                        "COMPLIANT": "#64FFDA",
                        "NON_COMPLIANT": "#FF6B6B",
                        "NOT_REQUIRED_DPP": "#8892B0",
                    },
                )
                fig1.update_layout(
                    paper_bgcolor="#112240",
                    plot_bgcolor="#112240",
                    font=dict(color="#CCD6F6"),
                    legend=dict(font=dict(color="#CCD6F6")),
                    height=320,
                    margin=dict(t=40, b=10),
                )
                st.plotly_chart(fig1, use_container_width=True)

            with col_b:
                gap_rows = []
                for r in results:
                    for mat, k, thr in [
                        ("Lithium", "recycled_lithium_pct", RECYCLED_MIN_PCT["Lithium"]),
                        ("Cobalt", "recycled_cobalt_pct", RECYCLED_MIN_PCT["Cobalt"]),
                        ("Nickel", "recycled_nickel_pct", RECYCLED_MIN_PCT["Nickel"]),
                    ]:
                        val = ((r.metrics.get(k, {}) or {}).get("value"))
                        if isinstance(val, (int, float)):
                            gap_rows.append({"Model": r.model, "Material": mat, "Gap vs Threshold (pp)": val - thr})
                if gap_rows:
                    fig2 = px.bar(
                        pd.DataFrame(gap_rows),
                        x="Model",
                        y="Gap vs Threshold (pp)",
                        color="Material",
                        barmode="group",
                        title=t["chart_gap"],
                        color_discrete_map={"Lithium": "#64FFDA", "Cobalt": "#A78BFA", "Nickel": "#FB923C"},
                    )
                    fig2.add_hline(y=0, line_dash="dash", line_color="#FF6B6B", annotation_text="Threshold")
                    fig2.update_layout(
                        paper_bgcolor="#112240",
                        plot_bgcolor="#112240",
                        font=dict(color="#CCD6F6"),
                        xaxis=dict(color="#8892B0", gridcolor="#1E3A5F"),
                        yaxis=dict(color="#8892B0", gridcolor="#1E3A5F"),
                        legend=dict(font=dict(color="#CCD6F6")),
                        height=320,
                        margin=dict(t=40, b=10),
                    )
                    st.plotly_chart(fig2, use_container_width=True)
        except Exception:
            pass

        # ── Results Table with legal expanders ──
        st.markdown(f"<div class='section-header'>{t['result_table']}</div>", unsafe_allow_html=True)

        LEGAL_CITATIONS = {
            "recycled_lithium": "Article 8(2)(c): batteries shall contain ≥ 6% lithium recovered from battery waste.",
            "recycled_cobalt": "Article 8(2)(a): batteries shall contain ≥ 16% cobalt recovered from battery waste.",
            "recycled_nickel": "Article 8(2)(d): batteries shall contain ≥ 6% nickel recovered from battery waste.",
            "recycled_lead": "Article 8(2)(b): batteries shall contain ≥ 85% lead recovered from battery waste.",
            "carbon_footprint": "Annex XIII(1)(c) + Article 7: carbon footprint information must be declared and physically plausible.",
            "bms_access": "Article 14: BMS read/write access disclosure required for state-of-health assessment.",
            "unique_identifier": "Article 77(3): battery passport accessible via QR-linked unique identifier.",
            "manufacturer_id": "Article 77(4): information in passport shall be accurate, complete and up to date.",
            "extinguishing_agent": "Annex VI Part A(9) via Annex XIII(1)(a): label must include usable extinguishing agent.",
            "hazardous_substances": "Annex XIII(1)(b): battery passport includes hazardous substances declaration.",
            "mine_coordinates": "OECD Due Diligence Guidance: mine sourcing coordinates outside known mining zones flagged as high-risk.",
        }

        for r in display:
            status_icon = "✅" if r.status == "COMPLIANT" else ("⛔" if r.status == "NON_COMPLIANT" else "ℹ️")
            risk_color = {"low": "#64FFDA", "medium": "#FCD34D", "high": "#FF6B6B"}.get(r.risk_level, "#8892B0")
            fraud_badge = (
                f" 🚩 <span style='color:#FF6B6B;font-size:0.78rem;'>{'  '.join(r.fraud_flags)}</span>"
                if r.fraud_flags else ""
            )
            with st.expander(
                f"{status_icon} **{r.model}** — {r.status} | "
                f"Risk: {r.risk_level.upper()}"
            ):
                st.markdown(
                    f"<span style='color:{risk_color};font-weight:600;'>Risk Level: {r.risk_level.upper()}</span>"
                    f"{fraud_badge}",
                    unsafe_allow_html=True,
                )
                if r.issues:
                    st.markdown("**Issues:**")
                    for issue in r.issues:
                        # find matching legal citation
                        citation = next(
                            (v for k, v in LEGAL_CITATIONS.items() if k.replace("_", " ").split()[0] in issue.lower()),
                            None,
                        )
                        st.markdown(f"• {issue}")
                        if citation:
                            st.markdown(
                                f"<div class='law-quote'>📖 {citation}</div>",
                                unsafe_allow_html=True,
                            )
                else:
                    st.markdown("No compliance issues found.")

        if st.session_state.get("pdf_bytes"):
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                t["download_pdf"],
                data=st.session_state["pdf_bytes"],
                file_name=st.session_state.get("pdf_filename", "DPP_Audit_Report.pdf"),
                mime="application/pdf",
                use_container_width=True,
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
                lat = ((r.metrics.get("mine_latitude", {}) or {}).get("value"))
                lon = ((r.metrics.get("mine_longitude", {}) or {}).get("value"))
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    is_risk = "HIGH_RISK" in (r.fraud_flags or [])
                    map_rows.append({
                        "Model": r.model,
                        "Latitude": lat,
                        "Longitude": lon,
                        "Risk": "🔴 High Risk" if is_risk else "🟢 Normal",
                        "Status": r.status,
                        "Color": "#FF6B6B" if is_risk else "#64FFDA",
                        "Size": 16 if is_risk else 10,
                    })

            if map_rows:
                df_map = pd.DataFrame(map_rows)
                fig_map = px.scatter_geo(
                    df_map,
                    lat="Latitude",
                    lon="Longitude",
                    color="Risk",
                    size="Size",
                    hover_name="Model",
                    hover_data={"Status": True, "Latitude": True, "Longitude": True, "Size": False},
                    color_discrete_map={"🔴 High Risk": "#FF6B6B", "🟢 Normal": "#64FFDA"},
                    projection="natural earth",
                    title=t["map_title"],
                )
                fig_map.update_layout(
                    paper_bgcolor="#112240",
                    plot_bgcolor="#112240",
                    font=dict(color="#CCD6F6"),
                    geo=dict(
                        bgcolor="#0A192F",
                        landcolor="#1E3A5F",
                        oceancolor="#0A192F",
                        countrycolor="#1E3A5F",
                        lakecolor="#0A192F",
                        showland=True,
                        showocean=True,
                        showcountries=True,
                        showlakes=True,
                    ),
                    legend=dict(font=dict(color="#CCD6F6"), bgcolor="#112240"),
                    height=520,
                    margin=dict(t=40, b=10, l=0, r=0),
                )
                st.plotly_chart(fig_map, use_container_width=True)
            else:
                st.info("No mine coordinate data found in audit results.")
        except Exception as e:
            st.error(f"Map rendering error: {e}")
    else:
        st.info(t["map_no_data"])
        # Show a demo map with known mining zones
        try:
            import plotly.express as px

            demo_zones = pd.DataFrame([
                {"Zone": "Chile / Argentina (Li)", "Latitude": -22.0, "Longitude": -68.0, "Risk": "🟢 Normal", "Size": 14},
                {"Zone": "DRC Cobalt Belt", "Latitude": -8.0, "Longitude": 25.0, "Risk": "🟢 Normal", "Size": 14},
                {"Zone": "Western Australia (Li)", "Latitude": -26.0, "Longitude": 120.0, "Risk": "🟢 Normal", "Size": 12},
                {"Zone": "Southern Africa (Li)", "Latitude": -22.0, "Longitude": 24.0, "Risk": "🟢 Normal", "Size": 12},
            ])
            fig_demo = px.scatter_geo(
                demo_zones,
                lat="Latitude",
                lon="Longitude",
                hover_name="Zone",
                size="Size",
                color="Risk",
                color_discrete_map={"🟢 Normal": "#64FFDA"},
                projection="natural earth",
                title="Known Global Li/Co Mining Zones (OECD Reference)",
            )
            fig_demo.update_layout(
                paper_bgcolor="#112240",
                font=dict(color="#CCD6F6"),
                geo=dict(
                    bgcolor="#0A192F", landcolor="#1E3A5F", oceancolor="#0A192F",
                    countrycolor="#1E3A5F", showland=True, showocean=True, showcountries=True,
                ),
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

    articles = t["law_articles"]
    for article_key, content in articles.items():
        en_title = content.get("en_title", article_key)
        display_key = article_key if lang == "zh" else en_title
        body = content.get(lang, content.get("en", ""))
        quote = content.get("quote", "")

        with st.expander(f"📋 **{display_key}**", expanded=False):
            st.markdown(body)
            if quote:
                st.markdown(
                    f"<div class='law-quote'>📖 {quote}</div>",
                    unsafe_allow_html=True,
                )
            # Copy-friendly quote box
            if quote:
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

    # Reference PDFs available in project
    st.markdown("**📁 Reference Documents Available Locally**")
    ref_docs = [
        ("EU_Battery_Reg_Full.pdf", "EU 2023/1542 Full Text"),
        ("GBA_Passport_Standard.pdf", "GBA Battery Passport Standard"),
        ("JRC_Carbon_Benchmark.pdf", "JRC Carbon Footprint Methodology"),
        ("OECD_Minerals_Guidance.pdf", "OECD Due Diligence Minerals Guidance"),
    ]
    doc_cols = st.columns(2)
    for i, (fname, label) in enumerate(ref_docs):
        fpath = Path(__file__).parent / fname
        with doc_cols[i % 2]:
            if fpath.exists():
                st.markdown(
                    f"<div class='law-card'>📄 <b>{label}</b><br>"
                    f"<span style='color:#8892B0;font-size:0.8rem;'>{fname}</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div class='law-card' style='opacity:0.5;'>📄 {label}</div>",
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

    # Footer
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;color:#3D5270;font-size:0.78rem;'>"
        "⚡ DPP Expert 3.0 &nbsp;·&nbsp; Powered by EU 2023/1542 Compliance Engine &nbsp;·&nbsp; "
        "Generated by AI Compliance Engine – Verified for EU 2023/1542 Standards"
        "</div>",
        unsafe_allow_html=True,
    )
