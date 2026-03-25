"""app/engine/auditor.py — Core audit logic framework for the FastAPI backend.

This module wraps the existing dpp_engine.validate_record() function and exposes
Pydantic-typed request/response models suitable for a REST API.

Design principles
-----------------
- AuditRequest  : typed input model, accepts all Annex XIII fields
- AuditResult   : typed output model, mirrors DppResult
- run_audit()   : single-record entry point
- run_batch_audit(): multi-record entry point from raw CSV bytes
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from io import StringIO
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Re-use the validated audit logic from the existing engine
from dpp_engine import DppResult, validate_record


# ── Request model ──────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    """All fields map to DPP_FIELD_MAP aliases in dpp_engine.py.

    Only `model` and `category` are strictly required; the engine itself
    determines which additional fields are mandatory based on category/capacity.
    """

    # Identity
    model:              str  = Field(...,    description="Battery model identifier")
    category:           str  = Field(...,    description="EV | LMT | INDUSTRIAL")
    language:           Optional[str] = Field("zh", description="Report language: zh | en")

    # Public information (Annex VI Part A)
    unique_identifier:  Optional[str]   = Field(None, description="QR-linked passport UID (Art. 77(3))")
    battery_id:         Optional[str]   = Field(None, description="Battery serial / model ID")
    manufacturer_id:    Optional[str]   = Field(None, description="Manufacturer ID: MFG-XXXXXX")
    manufacturer:       Optional[str]   = Field(None, description="Manufacturer name")
    manufacture_place:  Optional[str]   = Field(None, description="Country/city of manufacture")
    manufacture_date:   Optional[str]   = Field(None, description="YYYY-MM format (Annex VI Part A(4))")
    capacity_kwh:       Optional[float] = Field(None, description="Battery capacity in kWh")

    # Materials & compliance (Article 8)
    recycled_lithium_pct: Optional[float] = Field(None, ge=0, le=100, description="Recycled Li share % (≥6%)")
    recycled_cobalt_pct:  Optional[float] = Field(None, ge=0, le=100, description="Recycled Co share % (≥16%)")
    recycled_nickel_pct:  Optional[float] = Field(None, ge=0, le=100, description="Recycled Ni share % (≥6%)")
    recycled_lead_pct:    Optional[float] = Field(None, ge=0, le=100, description="Recycled Pb share % (≥85%)")
    hazardous_substances_declaration: Optional[str] = Field(None, description="Hazardous substances disclosure (Annex XIII(1)(b))")

    # Performance & durability (Annex XIII Part C)
    rated_capacity_ah:                   Optional[float] = Field(None, gt=0, description="Rated capacity in Ah")
    nominal_voltage_v:                   Optional[float] = Field(None, gt=0, description="Nominal voltage in V")
    rated_power_w:                       Optional[float] = Field(None, gt=0, description="Rated power in W")
    self_discharge_rate_pct_per_month:   Optional[float] = Field(None, ge=0, description="Self-discharge rate %/month")
    expected_lifetime_cycles:            Optional[float] = Field(None, gt=0, description="Expected cycle life")
    charge_discharge_efficiency_percent: Optional[float] = Field(None, gt=0, le=100, description="Round-trip efficiency %")

    # Safety
    thermal_runaway_prevention: Optional[str]   = Field(None, description="Thermal runaway control description")
    extinguishing_agent:        Optional[str]   = Field(None, description="Usable extinguishing agent (Annex VI Part A(9))")
    explosion_proof_declaration:Optional[str]   = Field(None, description="Explosion-proof declaration")
    bms_access_permissions:     Optional[str]   = Field(None, description="BMS read/write access info (Art. 14)")

    # Traceability & carbon (Article 7, Annex XIII Part D)
    chemistry:                      Optional[str]   = Field(None, description="Electrochemical system: NMC | LFP | ...")
    mine_latitude:                  Optional[float] = Field(None, ge=-90,  le=90,  description="Source mine latitude")
    mine_longitude:                 Optional[float] = Field(None, ge=-180, le=180, description="Source mine longitude")
    carbon_footprint_total_kg_co2e: Optional[float] = Field(None, ge=0, description="Lifecycle CO₂e total (kg)")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a flat dict compatible with dpp_engine.validate_record()."""
        return {k: v for k, v in self.model_dump().items() if v is not None and k != "language"}


# ── Result model ───────────────────────────────────────────────────────────────

class AuditResult(BaseModel):
    """Structured output of a single battery audit."""
    model:          str
    status:         str            # COMPLIANT | NON_COMPLIANT | NOT_REQUIRED_DPP
    risk_level:     str            # low | medium | high | N/A
    issues:         List[str]
    missing_fields: List[str]
    fraud_flags:    List[str]
    metrics:        Dict[str, Any] = Field(default_factory=dict)
    audited_at:     str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    @classmethod
    def from_dpp_result(cls, r: DppResult) -> "AuditResult":
        return cls(
            model=r.model,
            status=r.status,
            risk_level=r.risk_level,
            issues=r.issues,
            missing_fields=r.missing_fields,
            fraud_flags=r.fraud_flags,
            metrics=r.metrics,
        )


# ── Batch response model ───────────────────────────────────────────────────────

class BatchAuditResponse(BaseModel):
    report_no:        str
    total:            int
    compliant:        int
    non_compliant:    int
    not_required:     int
    high_risk_count:  int
    compliance_rate:  float
    results:          List[AuditResult]


# ── Entry points ───────────────────────────────────────────────────────────────

def run_audit(request: AuditRequest) -> AuditResult:
    """Validate a single AuditRequest and return a typed AuditResult."""
    raw: Dict[str, Any] = request.to_dict()
    dpp: DppResult = validate_record(raw)
    return AuditResult.from_dpp_result(dpp)


def run_batch_audit(csv_bytes: bytes, language: str = "zh") -> BatchAuditResponse:
    """Parse raw CSV bytes and audit every row.

    Parameters
    ----------
    csv_bytes : raw bytes from an uploaded CSV file
    language  : "zh" | "en" — passed through to report generation

    Returns
    -------
    BatchAuditResponse with summary statistics and per-record results
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(text))
    rows: List[Dict[str, Any]] = list(reader) if reader.fieldnames else []

    results: List[AuditResult] = []
    for row in rows:
        dpp = validate_record(dict(row))
        results.append(AuditResult.from_dpp_result(dpp))

    compliant     = sum(1 for r in results if r.status == "COMPLIANT")
    non_compliant = sum(1 for r in results if r.status == "NON_COMPLIANT")
    not_required  = sum(1 for r in results if r.status == "NOT_REQUIRED_DPP")
    high_risk     = sum(1 for r in results if "HIGH_RISK" in r.fraud_flags)
    mandatory     = compliant + non_compliant
    comp_rate     = compliant / mandatory if mandatory else 0.0

    # Deterministic report number from CSV content hash
    report_no = "RPT-" + hashlib.sha256(csv_bytes).hexdigest()[:10].upper()

    return BatchAuditResponse(
        report_no=report_no,
        total=len(results),
        compliant=compliant,
        non_compliant=non_compliant,
        not_required=not_required,
        high_risk_count=high_risk,
        compliance_rate=round(comp_rate, 4),
        results=results,
    )
