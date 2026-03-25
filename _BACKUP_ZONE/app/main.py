"""app/main.py — FastAPI entry point for DPP Expert API server.

Start with:
    uvicorn app.main:app --reload --port 8000

Endpoints
---------
GET  /                     Health check
POST /api/v1/audit         Audit a single battery record (JSON)
POST /api/v1/audit/batch   Audit multiple records from a CSV upload
GET  /api/v1/report/{id}   Download a generated PDF report by report_id
GET  /api/v1/benchmarks    Return the bundled battery benchmark database
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

# Internal modules (resolved relative to project root, so run from project root)
from app.engine.auditor import AuditRequest, AuditResult, BatchAuditResponse, run_audit, run_batch_audit
from app.utils.report import build_pdf_report

# ── App instance ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="DPP Expert API",
    description=(
        "EU 2023/1542 Battery Regulation — Digital Product Passport Pre-Audit Engine. "
        "Validates battery data fields against Annex XIII requirements and generates "
        "PDF compliance reports."
    ),
    version="3.1.0",
    contact={"name": "DPP Expert Support", "email": "support@dpp-expert.eu"},
    license_info={"name": "Proprietary — Pre-Audit Use Only"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory report cache: {report_id: pdf_bytes}
_REPORT_CACHE: Dict[str, bytes] = {}

# ── Models ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "3.1.0"
    regulation: str = "EU 2023/1542"


class AuditResponse(BaseModel):
    report_id: str
    model: str
    status: str
    risk_level: str
    missing_fields: List[str]
    fraud_flags: List[str]
    issues: List[str]
    pdf_available: bool
    pdf_url: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_model=HealthResponse, tags=["Health"])
def health_check() -> HealthResponse:
    """Ping the service and confirm regulation version."""
    return HealthResponse()


@app.post("/api/v1/audit", response_model=AuditResponse, tags=["Audit"])
def audit_single(request: AuditRequest) -> AuditResponse:
    """Audit a single battery record supplied as a JSON body.

    Returns compliance status, risk level, missing fields, fraud flags,
    and a report_id you can use to download the PDF.
    """
    result: AuditResult = run_audit(request)

    pdf_bytes = build_pdf_report([result], language=request.language or "zh")
    report_id = str(uuid.uuid4())
    _REPORT_CACHE[report_id] = pdf_bytes

    return AuditResponse(
        report_id=report_id,
        model=result.model,
        status=result.status,
        risk_level=result.risk_level,
        missing_fields=result.missing_fields,
        fraud_flags=result.fraud_flags,
        issues=result.issues,
        pdf_available=True,
        pdf_url=f"/api/v1/report/{report_id}",
    )


@app.post("/api/v1/audit/batch", tags=["Audit"])
async def audit_batch(
    file: UploadFile = File(..., description="CSV file with battery records"),
    language: str = "zh",
    client_name: str = "API Client",
    project_code: str = "BATCH-AUDIT",
) -> JSONResponse:
    """Upload a CSV file and audit all battery records in one call.

    Returns a JSON summary and a report_id for PDF download.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    raw = await file.read()
    response: BatchAuditResponse = run_batch_audit(raw, language=language)

    pdf_bytes = build_pdf_report(
        response.results,
        language=language,
        report_no=response.report_no,
        client_name=client_name,
        project_code=project_code,
    )
    report_id = str(uuid.uuid4())
    _REPORT_CACHE[report_id] = pdf_bytes

    return JSONResponse({
        "report_id":       report_id,
        "pdf_url":         f"/api/v1/report/{report_id}",
        "total":           response.total,
        "compliant":       response.compliant,
        "non_compliant":   response.non_compliant,
        "not_required":    response.not_required,
        "high_risk_count": response.high_risk_count,
        "compliance_rate": response.compliance_rate,
        "results": [
            {
                "model":         r.model,
                "status":        r.status,
                "risk_level":    r.risk_level,
                "fraud_flags":   r.fraud_flags,
                "missing_count": len(r.missing_fields),
            }
            for r in response.results
        ],
    })


@app.get("/api/v1/report/{report_id}", tags=["Reports"])
def download_report(report_id: str) -> Response:
    """Download a previously generated PDF audit report by its report_id."""
    pdf_bytes = _REPORT_CACHE.get(report_id)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=404,
            detail=f"Report '{report_id}' not found. Reports expire when the server restarts.",
        )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="DPP_Report_{report_id[:8]}.pdf"'},
    )


@app.get("/api/v1/benchmarks", tags=["Reference Data"])
def get_benchmarks() -> JSONResponse:
    """Return the bundled battery production benchmark database."""
    bench_path = Path(__file__).resolve().parent.parent / "data" / "benchmarks.json"
    if not bench_path.exists():
        raise HTTPException(status_code=503, detail="Benchmark database not found.")
    data: Any = json.loads(bench_path.read_text(encoding="utf-8"))
    return JSONResponse(data)
