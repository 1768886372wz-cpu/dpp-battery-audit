"""translations.py — All bilingual (zh/en) text for DPP Expert 3.0.

Contains:
  TRANSLATIONS  — Streamlit UI labels, used in app.py
  PDF_LABELS_ZH — Chinese label dict for PDF cover/table, used in pdf_generator.py
  PDF_LABELS_EN — English label dict for PDF cover/table, used in pdf_generator.py
"""
from __future__ import annotations

from typing import Any, Dict

# ── Streamlit UI translations ─────────────────────────────────────────────────
TRANSLATIONS: Dict[str, Dict[str, Any]] = {
    "zh": {
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
        "tab_dash": "📊 战略仪表盘",
        "tab_audit": "🛡 合规审计中心",
        "tab_map": "🌍 供应链溯源地图",
        "tab_law": "📚 法规知识库",
        "tab_about": "🏢 关于与支持",
        "dash_welcome": "欢迎来到中资出海电池 DPP 合规管理门户",
        "dash_sub": "EU 2023/1542 · Digital Product Passport · Pre-Audit Intelligence",
        "dash_kpi1": "当前批次合规率",
        "dash_kpi2": "平均碳强度 (kg CO₂e)",
        "dash_kpi3": "高风险矿点预警",
        "dash_kpi4": "供应链透明度得分",
        "dash_radar_title": "合规六维雷达图",
        "dash_no_data": "请先在「合规审计中心」上传并运行审计，仪表盘将自动刷新。",
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
        "map_title": "全球矿山坐标溯源地图",
        "map_sub": "绿色 = 已知矿区  •  红色 = 高风险 / 坐标异常",
        "map_no_data": "请先运行审计以加载矿山坐标数据。",
        "law_title": "EU 2023/1542 核心条文解读",
        "law_official_link": "🔗 跳转欧盟官方法规原文",
        "law_articles": {
            "Article 7 — 碳足迹声明": {
                "en_title": "Article 7 — Carbon Footprint",
                "zh": (
                    "**核心要求：** 电动汽车电池、LMT 电池及容量 > 2 kWh 的工业电池，须附有碳足迹声明，"
                    "涵盖生命周期各阶段的 CO₂ 当量排放总量。\n\n"
                    "**关键节点：** 碳足迹性能等级标签要求从 2026 年起生效。\n\n"
                    "**审计意义：** 缺少 carbon_footprint_total_kg_co2e 或数值低于物理下限，"
                    "将触发 DATA_UNREALISTIC 或 NON_COMPLIANT 判定。"
                ),
                "en": (
                    "**Core Requirement:** EV batteries, LMT batteries, and industrial batteries > 2 kWh must carry a "
                    "Carbon Footprint Declaration covering CO₂-equivalent emissions across all lifecycle stages.\n\n"
                    "**Key Milestones:** Performance-class labels apply from 2026; maximum threshold values set by delegated acts.\n\n"
                    "**Audit Relevance:** Missing carbon_footprint_total_kg_co2e or value below physics floor → "
                    "DATA_UNREALISTIC or NON_COMPLIANT."
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
                    "**核心要求：** 制造商须证明回收材料达到最低比例，并提供经第三方核验的计算方法与证据链。\n\n"
                    "**审计意义：** 任一金属低于阈值，判定为 NON_COMPLIANT（严重违规），引用 Article 8(2)(a)-(d)。"
                ),
                "en": (
                    "**Mandatory Thresholds (2027 target):**\n"
                    "- Lithium ≥ **6%** · Cobalt ≥ **16%** · Nickel ≥ **6%** · Lead ≥ **85%**\n\n"
                    "**Core Requirement:** Manufacturers must demonstrate minimum recycled shares with auditable evidence.\n\n"
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
                    "**核心要求：** EV 电池须提供 BMS 读写访问权限的说明，使授权运营商能够评估健康状态（SoH）和剩余寿命（RUL）。\n\n"
                    "**审计意义：** bms_access_permissions 缺少写访问说明，将触发 NON_COMPLIANT，引用 Article 14。"
                ),
                "en": (
                    "**Core Requirement:** EV batteries must disclose BMS read/write access permissions, enabling authorised "
                    "operators to assess State of Health (SoH) and Remaining Useful Life (RUL).\n\n"
                    "**Audit Relevance:** Missing write-access in bms_access_permissions → NON_COMPLIANT citing Article 14."
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
                    "**唯一标识符：** 护照须通过 QR 码链接至唯一标识符，可在线访问所有 Annex XIII 必填字段。\n\n"
                    "**审计意义：** unique_identifier 缺失或 manufacturer_id 格式不符，判定为 NON_COMPLIANT。"
                ),
                "en": (
                    "**Mandatory Date:** From **18 February 2027**, EV, LMT, and industrial batteries > 2 kWh must have a passport.\n\n"
                    "**Unique Identifier:** Each passport linked via QR code giving online access to all Annex XIII fields.\n\n"
                    "**Audit Relevance:** Missing unique_identifier or invalid manufacturer_id → NON_COMPLIANT."
                ),
                "quote": (
                    '"As of 18 February 2027, EV batteries, light means of transport batteries and industrial batteries with a capacity '
                    'of more than 2 kWh shall have a battery passport." — Art. 77(1)'
                ),
            },
            "Annex XIII — 护照数据要求": {
                "en_title": "Annex XIII — Battery Passport Data Requirements",
                "zh": (
                    "**四大模块：**\n"
                    "1. **公共信息（Part A）：** 制造商、生产地、生产日期、电池类别、唯一标识符、QR 码。\n"
                    "2. **材料与合规（Part B）：** 危险物质声明、关键原材料、化学成分、回收比例证明。\n"
                    "3. **性能与耐久性（Part C）：** 额定容量、标称电压、充放电效率、预期寿命、热管理规格。\n"
                    "4. **碳足迹信息（Part D，Article 7）：** 各生命周期阶段碳排放细分及总量。\n\n"
                    "**审计意义：** 本平台的 DPP_FIELD_MAP 直接映射 Annex XIII 四大模块，逐字段核验。"
                ),
                "en": (
                    "**Four Modules:** (A) Public info — manufacturer, location, date, ID; "
                    "(B) Materials & compliance — hazardous substances, chemistry, recycled content; "
                    "(C) Performance — capacity, voltage, efficiency, lifetime; "
                    "(D) Carbon footprint breakdown per lifecycle stage.\n\n"
                    "**Audit Relevance:** The DPP_FIELD_MAP mirrors Annex XIII for field-by-field validation."
                ),
                "quote": (
                    '"A battery passport shall be established for each battery model per manufacturing plant '
                    'and shall include the information listed in this Annex." — Annex XIII, Preamble'
                ),
            },
        },
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
                    "**Core Requirement:** EV batteries, LMT batteries, and industrial batteries > 2 kWh must carry a "
                    "Carbon Footprint Declaration covering CO₂-equivalent emissions across all lifecycle stages.\n\n"
                    "**Mandatory from 2026:** Performance-class labels; threshold values set by delegated acts.\n\n"
                    "**Audit Relevance:** Missing carbon_footprint_total_kg_co2e or value below physics floor → "
                    "DATA_UNREALISTIC / NON_COMPLIANT."
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

# ── PDF label dictionaries ────────────────────────────────────────────────────
# Used by pdf_generator.py; kept here so all text lives in one place.

PDF_LABELS_ZH: Dict[str, str] = {
    "title":         "欧盟 2023/1542 电池法案合规预审计报告",
    "sub":           "EU 2023/1542 Battery Regulation – Compliance Pre-Audit Report",
    "grade":         "合规等级",
    "time":          "审计时间",
    "client":        "客户",
    "proj":          "项目",
    "rptno":         "报告编号",
    "scope": (
        "适用范围：自 2027-02-18 起，LMT 电池、容量 > 2 kWh 的工业电池"
        " 及电动汽车电池须具备电池护照（Art. 77(1)）。"
    ),
    "summary":       "型号级别审计结果汇总",
    "model":         "型号",
    "status":        "判定结果",
    "risk":          "风险等级",
    "issues":        "问题说明 / 法规引用",
    "compliant":     "COMPLIANT / 合规",
    "non_compliant": "NON_COMPLIANT / 不合规",
    "not_required":  "NOT_REQUIRED_DPP / 不强制执行",
    "manual":        "建议人工复核（潜在欺诈风险）",
    "radar":         "合规六维指标雷达",
    "gap":           "差额修复清单 (Gap Fixing List)",
    "no_gap":        "未检测到关键缺口；请保持定期数据更新与证据留痕。",
    "rec_title":     "专业建议",
    "rec_body": (
        "如出现 NON_COMPLIANT，请优先补齐电池护照强制字段，"
        "对回收材料比例/碳足迹建立可验证的计算与证明文件（Art. 8, Art. 7, Annex XIII）。"
    ),
    "disclaimer": (
        "免责声明：本报告为预审计/一致性检查用途，基于用户提供的数据字段进行自动化校验，"
        "不构成法律意见或公告认证结论。最终准入以欧盟授权机构为准。"
    ),
    "watermark": "CONFIDENTIAL PRE-AUDIT REPORT - BY DPP INSIGHT",
}

PDF_LABELS_EN: Dict[str, str] = {
    "title":         "EU 2023/1542 Battery Regulation Compliance Pre-Audit Report",
    "sub":           "Powered by DPP Expert 3.0 – Sino-British Sustainable Development Research Group",
    "grade":         "Compliance Grade",
    "time":          "Audit Time",
    "client":        "Client",
    "proj":          "Project",
    "rptno":         "Report No.",
    "scope": (
        "Scope: From 18 Feb 2027, LMT batteries, industrial batteries > 2 kWh,"
        " and EV batteries shall have a battery passport (Art. 77(1))."
    ),
    "summary":       "Model-Level Audit Summary",
    "model":         "Model",
    "status":        "Status",
    "risk":          "Risk Level",
    "issues":        "Issues & Legal References",
    "compliant":     "COMPLIANT",
    "non_compliant": "NON_COMPLIANT",
    "not_required":  "NOT_REQUIRED_DPP",
    "manual":        "Manual Review Recommended (Potential Fraud Risk)",
    "radar":         "6-Dimension Compliance Metrics Radar",
    "gap":           "Gap Fixing List",
    "no_gap":        "No critical gaps detected; maintain periodic data-quality monitoring.",
    "rec_title":     "Professional Recommendations",
    "rec_body": (
        "If NON_COMPLIANT is reported, prioritise completing mandatory Battery Passport data "
        "and producing verifiable evidence for recycled content and carbon footprint "
        "(Art. 8, Art. 7, Annex XIII)."
    ),
    "disclaimer": (
        "Disclaimer: This report is for pre-audit / consistency-check purposes only, "
        "based on automated validation of user-supplied data. It does not constitute "
        "legal advice or official certification. Final market access rests with "
        "EU-authorised conformity assessment bodies."
    ),
    "watermark": "CONFIDENTIAL PRE-AUDIT REPORT - BY DPP INSIGHT",
}
