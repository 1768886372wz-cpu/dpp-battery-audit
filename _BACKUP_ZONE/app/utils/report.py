"""app/utils/report.py — PDF report builder helper for the FastAPI backend.

Delegates to pdf_generator.generate_audit_pdf(), adapting AuditResult objects
(Pydantic) back to DppResult dataclasses expected by the generator.
"""
from __future__ import annotations

from typing import List, Union

from app.engine.auditor import AuditResult
from dpp_engine import DppResult
from pdf_generator import generate_audit_pdf


def build_pdf_report(
    results: List[Union[AuditResult, DppResult]],
    language: str = "zh",
    report_no: str = "",
    client_name: str = "API Client",
    project_code: str = "DPP-API",
) -> bytes:
    """Convert AuditResult objects → DppResult and call the PDF generator.

    Both AuditResult (Pydantic) and DppResult (dataclass) are accepted so this
    function can be called from both the API layer and the Streamlit layer.
    """
    dpp_results: List[DppResult] = []
    for r in results:
        if isinstance(r, DppResult):
            dpp_results.append(r)
        else:
            dpp_results.append(DppResult(
                model=r.model,
                status=r.status,
                risk_level=r.risk_level,
                issues=r.issues,
                missing_fields=r.missing_fields,
                metrics=r.metrics,
                fraud_flags=r.fraud_flags,
            ))

    return generate_audit_pdf(
        results=dpp_results,
        language=language,
        report_no=report_no,
        client_name=client_name,
        project_code=project_code,
    )
