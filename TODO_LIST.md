# DPP Expert — 明日行动清单 (Tomorrow's Action List)

> 生成时间：2026-03-24  
> 状态：休眠前保存，明早优先处理以下三个技术难点与商业漏洞

---

## 🔴 优先级 1 — 碳足迹核算引擎（最高商业价值）

**问题**：系统目前只能核查"碳足迹数值是否在合理范围内"，**无法替用户计算碳足迹**。
这是欧盟 Article 7 合规的核心痛点——大多数中小型中国电池制造商没有能力自己做 LCA。

**技术难点**：
- 如何基于用户提供的制造地、电网碳强度、原材料来源，自动估算碳足迹范围？
- 数据来源：国际能源署（IEA）各国电网碳强度数据库 + GREET 材料碳因子

**明天的行动**：
1. 在 `data/` 目录下创建 `grid_carbon_intensity.json`，录入中国各省及主要产电池国家的电网碳强度数据（来源：IEA 2024 World Energy Outlook）
2. 在 `app/auditor.py` 新增 `estimate_carbon_footprint()` 函数，接收 `manufacturing_country` + `energy_usage`，返回估算碳足迹区间
3. 在 `/audit` 接口返回值中增加 `estimated_carbon_range` 字段

**商业价值**：这个功能可以做成付费 SaaS 的核心差异化功能，直接对标 TÜV 的 LCA 咨询服务

---

## 🟠 优先级 2 — CATL / BYD 真实 ESG 数据的获取与集成

**问题**：`data/benchmarks.json` 的 `industry_company_benchmarks_2024` 章节中，CATL 和 BYD 的**具体单位能耗数值（kWh/kWh）均为 null**。本次深夜搜索未能从公开网页直接抓取到数字，因为这些数据通常只在 PDF 报告的深处。

**技术难点**：
- CATL 2024 CSR 报告（PDF）需要手动下载并解析特定表格
- BYD FinDreams Battery 2024 ESG 报告（PDF）同上
- LG Energy Solution 2024 ESG Report 已确认有完整体系，但具体 kWh/kWh 数值藏在附录

**明天的行动**：
1. 手动下载以下三份报告并用 `pypdf` 解析：
   - CATL：`ir.catl.com` → 投资者关系 → CSR 报告
   - BYD FinDreams：已找到 URL：`bydenergy.com/.../FinDreams Battery 2024 Sustainability and ESG Report.pdf`
   - LG Energy Solution：`lgensol.com/upload/file/download/LG_Energy_Solution_2024_ESG_Report_EN.pdf`
2. 提取关键数字后填入 `benchmarks.json` 的 `_specific_kwh_value` 字段
3. 将这些真实数据用于校准 `audit_rule` 的 `WARN_below` / `FAIL_below` 阈值

**商业价值**：有真实大厂数据背书的核查引擎，比纯文献数据的权威性提升一个量级

---

## 🟡 优先级 3 — 前端界面与 PDF 下载体验

**问题**：目前系统只有 FastAPI 后端，没有用户界面。要向客户演示或销售，需要一个最简化的 Web 前端。

**技术难点**：
- 当前 `/audit-pdf` 接口需要通过 `curl` 或 Swagger 调用，非技术用户无法使用
- PDF 报告的中供应链风险章节（`mineral_origin` + `forced_labour_risk`）需要在前端表单中引导用户填写

**明天的行动**：
1. 选择方案 A 或 B：
   - **方案 A（快，2小时）**：用 Streamlit 写一个单页表单，调用本地 FastAPI 接口，直接在浏览器下载 PDF
   - **方案 B（慢，1天）**：用 Vue.js / React 写更专业的前端，部署到 Vercel
2. 如果选方案 A：在项目根目录创建 `streamlit_demo.py`，调用 `http://localhost:8000/audit-pdf`
3. 在表单中增加供应链信息的引导性问题（如下拉选择矿物来源地）

**商业价值**：有了前端演示，可以在 5 分钟内向潜在客户展示完整工作流

---

## 📋 其他待观察事项（不紧急）

| 事项 | 状态 | 备注 |
|---|---|---|
| BMS 读权限核查（Article 14） | 待实现 | `_CHECKS` 列表中已有注释占位 |
| 矿山 GPS 坐标合理性验证 | 待实现 | 需要 GeoPandas 或 Shapely 库 |
| EU CBAM 与电池法案的交叉影响 | 待研究 | CBAM 目前覆盖钢铁/铝，电池暂未纳入 |
| 用户认证与报告历史存储 | 待设计 | 当前每次 PDF 不持久化 |
| 中文版 PDF 报告模板 | 待创建 | 当前模板为中英混排 |

---

## ✅ 今日已完成（休眠前确认）

- [x] `data/benchmarks.json` — 加入 `global_reference` 章节，包含 Nature Energy 2023 同行评审数据、EU 监管时间线、LG/BYD/CATL 企业信息
- [x] `app/auditor.py` — 新增维度 3：供应链区域风险（涵盖碳足迹申报缺口、矿物来源地、强迫劳动预警）
- [x] `app/main.py` — Pydantic 加强：字段范围校验（ge/le）、battery_type 枚举验证、跨字段一致性校验
- [x] `app/templates/report.html` — CSS 优化：page-break-inside、table-layout:fixed、word-break 防止长文本溢出
- [x] 所有端到端测试通过（PDF 生成、审计逻辑、路由注册）

---

*睡个好觉。明天继续。— DPP Expert AI Engine*
