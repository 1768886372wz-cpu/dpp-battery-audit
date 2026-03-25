"""
app/main.py — DPP Expert API 服务入口
======================================
启动命令：
    uvicorn app.main:app --reload --port 8000

接口文档（自动生成）：
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auditor import audit_battery_data
from app.utils.pdf_gen import build_pdf


# ── 启动/关闭生命周期 ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"

    print("\n" + "=" * 55)
    print("  DPP Expert API 已启动")
    print(f"  本机访问：http://127.0.0.1:8000")
    print(f"  局域网  ：http://{local_ip}:8000")
    print(f"  接口文档：http://127.0.0.1:8000/docs")
    print(f"  核心接口：POST http://127.0.0.1:8000/audit")
    print("=" * 55 + "\n")
    yield


# ── FastAPI 实例 ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="DPP Expert — 电池数字产品护照合规审计 API",
    description=(
        "基于 Regulation (EU) 2023/1542，对供应商申报的电池数据进行"
        "物理合理性核查（RED_FLAG）和法规符合性核查（COMPLIANCE_GAP）。\n\n"
        "**核心接口**：`POST /audit`\n\n"
        "**输入字段**：`battery_type` / `energy_usage` / `recycled_rate`"
    ),
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 生产环境请改为具体域名
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求模型 ──────────────────────────────────────────────────────────────────
# 合法电池类型枚举（避免乱填触发误判）
_VALID_BATTERY_TYPES = {"LFP", "NCM", "NMC", "NCA", "LCO", "LMO", "SIB"}
# 合法电池应用类别
_VALID_CATEGORIES = {"EV", "LMT", "Industrial", "SLI", "Portable", ""}


class AuditRequest(BaseModel):
    """
    供应商提交的电池申报数据。
    所有字段均为可选，未提交的字段会在结果中给出相应警告。
    """

    battery_type: str = Field(
        default="LFP",
        description=(
            "电化学体系：LFP / NCM / NMC / NCA / SIB 等。\n"
            "不区分大小写，NMC 自动映射为 NCM。\n"
            f"合法值：{sorted(_VALID_BATTERY_TYPES)}"
        ),
        examples=["LFP", "NCM"],
    )
    energy_usage: float | None = Field(
        default=None,
        ge=0,        # 不能为负数
        le=500,      # 物理上限 500 kWh/kWh（防止误填总能耗）
        description=(
            "制造能耗：生产 1 kWh 电池所耗电量（kWh/kWh）。\n"
            "LFP 合理范围 50–85，NCM 合理范围 60–110。\n"
            "低于行业公认最小值将触发 RED_FLAG。\n"
            "取值范围：0–500（超出视为录入错误）。"
        ),
        examples=[65.0],
    )
    recycled_rate: float | None = Field(
        default=None,
        ge=0,    # 百分比不能为负
        le=100,  # 百分比不能超过 100
        description=(
            "回收材料综合比例（%，0–100）。\n"
            "对标欧盟 2031 年法定最低值：锂 ≥ 6%（Article 8(2)(c)）。\n"
            "低于 6% 将触发 COMPLIANCE_GAP。"
        ),
        examples=[7.5],
    )
    carbon_footprint_kg_co2e_per_kwh: float | None = Field(
        default=None,
        ge=0,
        le=2000,
        description=(
            "生命周期碳足迹（kg CO2e / kWh 电池容量）。\n"
            "LFP 合理范围 40–100，NCM 合理范围 55–130。\n"
            "单位：kg CO2e per kWh（Article 7(1)(d) 法定申报单位）。"
        ),
        examples=[58.0],
    )
    battery_category: str = Field(
        default="",
        description=(
            "电池应用类别，影响碳足迹申报义务判断。\n"
            f"合法值：{sorted(_VALID_CATEGORIES - {''})} 或留空。\n"
            "EV：2025-02-18 已强制申报碳足迹；Industrial：2026-02-18。"
        ),
        examples=["EV", "Industrial", "LMT"],
    )
    mineral_origin: str = Field(
        default="",
        description=(
            "原材料主要来源地（国家或地区，自由文本）。\n"
            "如填写新疆、刚果（金）等已知高风险区域，将触发供应链风险警告。\n"
            "示例：'Australia'、'Chile'、'Xinjiang'、'DRC'"
        ),
        examples=["Australia", "Chile", "Xinjiang", "DRC"],
    )
    manufacturing_country: str = Field(
        default="",
        description="电池制造国/地区（自由文本），用于供应链区域风险评估。",
        examples=["China", "South Korea", "Poland"],
    )

    # ── Pydantic 自定义校验器 ────────────────────────────────────────────
    from pydantic import field_validator, model_validator

    @field_validator("battery_type", mode="before")
    @classmethod
    def normalise_battery_type(cls, v: str) -> str:
        """统一大写，NMC 别名映射为 NCM。"""
        v = str(v).upper().strip()
        if v == "NMC":
            v = "NCM"
        return v

    @field_validator("battery_category", mode="before")
    @classmethod
    def normalise_category(cls, v: str) -> str:
        return str(v).strip()

    @model_validator(mode="after")
    def validate_consistency(self) -> "AuditRequest":
        """跨字段一致性校验。"""
        bt = self.battery_type
        if bt not in _VALID_BATTERY_TYPES:
            from fastapi import HTTPException
            raise ValueError(
                f"battery_type '{bt}' 不在支持列表中。"
                f"合法值：{sorted(_VALID_BATTERY_TYPES)}"
            )
        cat = self.battery_category.upper()
        if cat and cat not in {c.upper() for c in _VALID_CATEGORIES}:
            raise ValueError(
                f"battery_category '{self.battery_category}' 无效。"
                f"合法值：{sorted(_VALID_CATEGORIES - {''})}"
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "完整数据 — 全部通过",
                    "value": {
                        "battery_type": "LFP",
                        "battery_category": "Industrial",
                        "energy_usage": 65,
                        "recycled_rate": 7,
                        "carbon_footprint_kg_co2e_per_kwh": 60,
                        "mineral_origin": "Australia",
                        "manufacturing_country": "China",
                    },
                },
                {
                    "summary": "RED_FLAG — 能耗物理不可能",
                    "value": {
                        "battery_type": "LFP",
                        "energy_usage": 10,
                        "recycled_rate": 6,
                    },
                },
                {
                    "summary": "COMPLIANCE_GAP — 回收率不足 + 供应链风险",
                    "value": {
                        "battery_type": "NCM",
                        "battery_category": "EV",
                        "energy_usage": 85,
                        "recycled_rate": 2,
                        "mineral_origin": "Xinjiang",
                    },
                },
            ]
        }
    }


# ── 响应模型 ──────────────────────────────────────────────────────────────────
class FindingOut(BaseModel):
    level:          str = Field(description="RED_FLAG / COMPLIANCE_GAP / WARNING / PASS")
    field:          str = Field(description="被检查的字段名")
    message:        str = Field(description="问题描述")
    legal_ref:      str = Field(description="法规条文引用")
    recommendation: str = Field(description="具体改进建议")


class AuditResponse(BaseModel):
    risk_level:       str              = Field(description="RED_FLAG / COMPLIANCE_GAP / WARNING / PASS")
    summary:          str              = Field(description="一句话审计总结")
    findings:         list[FindingOut] = Field(description="全部核查结果（含 PASS）")
    red_flags:        list[FindingOut] = Field(description="物理不可能的数据，疑似造假")
    compliance_gaps:  list[FindingOut] = Field(description="低于欧盟法定阈值的字段")
    warnings:         list[FindingOut] = Field(description="需补充证明材料的字段")
    passed:           list[FindingOut] = Field(description="通过核查的字段")
    recommendations:  list[str]        = Field(description="汇总改进建议列表")


# ── 接口定义 ──────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"], summary="服务健康检查")
def health_check():
    """确认 API 正常运行。"""
    return {
        "status":  "ok",
        "service": "DPP Expert API",
        "version": "2.1.0",
        "audit_endpoint": "POST /audit",
    }


@app.post(
    "/audit",
    response_model=AuditResponse,
    tags=["Audit"],
    summary="提交电池数据，获取 DPP 合规审计结果",
    response_description="包含风险等级、所有核查结论和改进建议的完整报告",
)
def audit(request: AuditRequest) -> AuditResponse:
    """
    **核心接口** — 提交供应商申报数据，返回：

    | 字段 | 说明 |
    |---|---|
    | `risk_level` | `RED_FLAG` 物理冲突 / `COMPLIANCE_GAP` 合规缺口 / `WARNING` 需证明 / `PASS` 通过 |
    | `red_flags` | 低于物理极限，疑似造假（energy_usage 低于公认最小值） |
    | `compliance_gaps` | 低于欧盟 2031 年法定阈值（recycled_rate < 6%） |
    | `recommendations` | 针对每个问题的具体整改建议 |

    **法规依据**：Regulation (EU) 2023/1542, OJ L 191, 28.7.2023
    """
    try:
        result = audit_battery_data(request.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"服务器配置错误：{e}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"数据处理失败：{e}")

    return AuditResponse(**result)


@app.post(
    "/audit-pdf",
    tags=["Audit"],
    summary="提交电池数据，直接下载 PDF 审计报告",
    response_description="PDF 文件（application/pdf），可直接在浏览器打开或保存",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF 审计报告"},
        500: {"description": "PDF 生成失败（字体缺失或渲染错误）"},
    },
)
def audit_pdf(request: AuditRequest) -> Response:
    """
    **一键生成 PDF 报告** — 完成核查后立即返回可下载的 PDF 文件。

    - 报告风格：专业咨询报告（TÜV / 麦肯锡排版风格）
    - 颜色编码：RED_FLAG 红色封面 / COMPLIANCE_GAP 橙色 / PASS 绿色
    - 内容：审计结论、关键指标对比、详细 Findings 表格、整改建议清单、法规声明
    - 中文支持：通过 @font-face 硬嵌入 NotoSansSC 字体，浏览器/打印机不乱码

    **法规依据**：Regulation (EU) 2023/1542, OJ L 191, 28.7.2023
    """
    # Step 1: 执行审计逻辑
    try:
        audit_result = audit_battery_data(request.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"服务器配置错误：{e}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"审计数据处理失败：{e}")

    # Step 2: 渲染 PDF
    try:
        pdf_bytes = build_pdf(audit_result, request.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 生成失败：{e}")

    # Step 3: 返回可下载的 PDF
    risk   = audit_result.get("risk_level", "REPORT")
    btype  = str(request.battery_type).upper()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="DPP_Audit_{btype}_{risk}.pdf"'
            )
        },
    )


@app.get(
    "/benchmarks/summary",
    tags=["Reference"],
    summary="查看当前行业基准阈值",
)
def benchmarks_summary():
    """返回 benchmarks.json 中的关键阈值，方便前端展示参考范围。"""
    from app.auditor import _load_benchmarks
    bench = _load_benchmarks()

    bt = bench.get("battery_types", {})
    rc = bench.get("recycled_content", {})

    return {
        "regulation":   bench["_metadata"]["regulation"],
        "last_updated": bench["_metadata"]["last_updated"],
        "input_fields": {
            "battery_type":   "LFP / NCM / NMC",
            "energy_usage":   "kWh/kWh — 制造能耗",
            "recycled_rate":  "% — 综合回收材料比例",
        },
        "energy_usage_ranges": {
            chem: {
                "min": bt[chem]["energy_per_kwh"]["min"],
                "max": bt[chem]["energy_per_kwh"]["max"],
                "avg": bt[chem]["energy_per_kwh"]["avg"],
            }
            for chem in bt if not chem.startswith("_")
        },
        "recycled_rate_mandatory_minimum": {
            "effective_date": rc["phase_2_mandatory_minimums"]["effective_date"],
            "legal_basis":    "Article 8(2)(c) — Regulation (EU) 2023/1542",
            "min_pct":        rc["phase_2_mandatory_minimums"]["thresholds"]["lithium"]["min_pct"],
            "note":           "recycled_rate 使用锂回收最低比例（6%）作为单一参考基准",
        },
    }
