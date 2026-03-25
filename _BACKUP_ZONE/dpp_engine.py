#!/usr/bin/env python3
"""dpp_engine.py — Core audit logic for EU 2023/1542 Battery DPP compliance.

Single responsibility: validate battery records and return DppResult objects.
No PDF generation, no fonts, no Streamlit — those live in pdf_generator.py and app.py.

Key legal references
--------------------
- Art. 77(1): DPP mandatory from 18 Feb 2027 for LMT, industrial > 2 kWh, and EV batteries.
- Art. 77(3): passport linked via QR code to a unique identifier.
- Art. 8(2)(a)-(d): minimum recycled content for Co/Li/Ni/Pb.
- Art. 7 + Annex XIII(1)(c): carbon footprint reporting.
- Art. 14: BMS read/write access disclosure.
- Annex XIII: complete list of battery passport data fields.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config import (
    ALLOWED_CATEGORIES,
    CARBON_FOOTPRINT_MIN_BY_CHEMISTRY,
    DPP_FIELD_MAP,
    KNOWN_LITHIUM_COBALT_MINING_ZONES,
    RECYCLED_MIN_PCT,
)


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _parse_float(value: Any) -> Optional[float]:
    s = _norm(value)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_yyyy_mm(value: Any) -> Optional[str]:
    """Accept YYYY-MM only — Annex VI Part A(4) specifies month+year."""
    s = _norm(value)
    if not s or not re.fullmatch(r"\d{4}-\d{2}", s):
        return None
    try:
        datetime.strptime(s, "%Y-%m")
        return s
    except ValueError:
        return None


def _parse_listish(value: Any) -> List[str]:
    """Accept JSON list or comma/semicolon-separated string."""
    s = _norm(value)
    if not s:
        return []
    if s.startswith("["):
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x).strip()]
        except Exception:
            pass
    return [p.strip() for p in re.split(r"[;,]", s) if p.strip()]


def _parse_percent_to_pct(value: Any) -> Optional[float]:
    """Accept percent (e.g. 6.0) or ratio (e.g. 0.06) — normalises to percent."""
    f = _parse_float(value)
    if f is None:
        return None
    if 0.0 <= f <= 1.0:
        f *= 100.0
    return f if 0 <= f <= 100 else None


def _present_nonempty(value: Any) -> bool:
    return _norm(value) != ""


def _get_field(rec: Dict[str, Any], module: str, key: str) -> Any:
    for alias in DPP_FIELD_MAP[module][key]["aliases"]:
        if alias in rec and _norm(rec.get(alias)) != "":
            return rec.get(alias)
    return None


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class DppResult:
    model:          str
    status:         str            # COMPLIANT | NON_COMPLIANT | NOT_REQUIRED_DPP
    risk_level:     str            # low | medium | high | N/A
    issues:         List[str]      # human-readable findings with legal refs
    missing_fields: List[str]      # required fields that are absent or invalid
    metrics:        Dict[str, Any] # per-field metric data (for radar chart)
    fraud_flags:    List[str]      # HIGH_RISK | DATA_UNREALISTIC

    def to_text(self) -> str:
        lines = [f"Model: {self.model}", f"Status: {self.status}", f"Risk: {self.risk_level}"]
        if self.missing_fields:
            lines.append("Missing fields: " + ", ".join(self.missing_fields))
        if self.issues:
            lines.append("Findings:")
            lines.extend(f"- {i}" for i in self.issues)
        if self.fraud_flags:
            lines.append("Fraud Flags: " + ", ".join(self.fraud_flags))
        return "\n".join(lines)


# ── Applicability ─────────────────────────────────────────────────────────────

def dpp_applicability(category: str, capacity_kwh: Optional[float]) -> Tuple[bool, str]:
    """Return (required, note) per Art. 77(1)."""
    cat = _norm(category).upper()
    if cat not in ALLOWED_CATEGORIES:
        return False, "Invalid battery category (expected EV/LMT/Industrial)."
    if cat == "INDUSTRIAL":
        if capacity_kwh is None:
            return True, "Industrial battery: capacity_kwh missing; cannot confirm Art. 77(1) exemption."
        if capacity_kwh <= 2.0:
            return False, "Industrial battery ≤ 2 kWh: DPP not mandatory (Art. 77(1) exemption)."
        return True, "Industrial battery > 2 kWh: DPP mandatory (Art. 77(1))."
    return True, f"{cat} battery: DPP mandatory from 18 February 2027 (Art. 77(1))."


# ── Anti-fraud heuristics ─────────────────────────────────────────────────────

def validate_coordinates(lat: Optional[float], lon: Optional[float]) -> Tuple[bool, str]:
    """Flag mine coordinates outside known Li/Co mining zones as HIGH_RISK."""
    if lat is None or lon is None:
        return False, "Missing mine coordinates; cannot validate sourcing geolocation."
    in_zone = any(
        la_min <= lat <= la_max and lo_min <= lon <= lo_max
        for la_min, la_max, lo_min, lo_max in KNOWN_LITHIUM_COBALT_MINING_ZONES
    )
    if in_zone:
        return True, "Mine coordinates are within known lithium/cobalt mining regions."
    return False, "Mine coordinates are outside known lithium/cobalt mining regions (High Risk)."


def validate_physical_carbon_floor(chemistry: str, cf_total: Optional[float]) -> Tuple[bool, str]:
    """Flag implausibly low carbon footprint values as DATA_UNREALISTIC."""
    c = _norm(chemistry).upper()
    if cf_total is None:
        return False, "Carbon footprint missing; plausibility check skipped."
    if c not in CARBON_FOOTPRINT_MIN_BY_CHEMISTRY:
        return True, f"No floor configured for {c}; check skipped."
    floor = CARBON_FOOTPRINT_MIN_BY_CHEMISTRY[c]
    if cf_total < floor:
        return False, f"Data Unrealistic: {cf_total} < {c} physical floor {floor}."
    return True, f"Carbon footprint above {c} physical floor ({floor})."


def validate_manufacturer_id(mid: str) -> Tuple[bool, str]:
    """Check manufacturer ID format: MFG-XXXXXX (≥ 6 uppercase alphanumeric)."""
    s = _norm(mid)
    if not s:
        return False, "manufacturer_id missing."
    if re.fullmatch(r"MFG-[A-Z0-9]{6,}", s):
        return True, "manufacturer_id format is valid."
    return False, f"manufacturer_id '{s}' failed format validation."


# ── Main record validator ─────────────────────────────────────────────────────

def validate_record(rec: Dict[str, Any]) -> DppResult:  # noqa: C901
    model = _norm(rec.get("model") or rec.get("battery_model") or rec.get("型号") or rec.get("Model"))
    if not model:
        model = "<unknown>"

    category    = _norm(_get_field(rec, "public_information", "category"))
    capacity_kwh = _parse_float(
        rec.get("capacity_kwh") or rec.get("capacity_kWh") or rec.get("capacity") or rec.get("容量_kwh")
    )
    dpp_required, applicability_note = dpp_applicability(category, capacity_kwh)

    # Public information
    unique_id       = _norm(_get_field(rec, "public_information", "unique_identifier"))
    battery_id      = _norm(_get_field(rec, "public_information", "battery_id"))
    manufacturer_id = _norm(_get_field(rec, "public_information", "manufacturer_id"))
    manufacturer    = _norm(_get_field(rec, "public_information", "manufacturer"))
    mfr_place       = _norm(_get_field(rec, "public_information", "manufacture_place"))
    mfr_date        = _parse_yyyy_mm(_get_field(rec, "public_information", "manufacture_date"))

    # Materials
    li_pct       = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lithium_pct"))
    co_pct       = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_cobalt_pct"))
    ni_pct       = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_nickel_pct"))
    pb_pct       = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lead_pct"))
    hazardous    = _norm(_get_field(rec, "materials_and_compliance", "hazardous_substances_declaration"))

    # Performance
    rated_cap_ah = _parse_float(_get_field(rec, "performance_and_durability", "rated_capacity_ah"))
    nominal_v    = _parse_float(_get_field(rec, "performance_and_durability", "nominal_voltage_v"))
    rated_pow_w  = _parse_float(_get_field(rec, "performance_and_durability", "rated_power_w"))
    self_disch   = _parse_float(_get_field(rec, "performance_and_durability", "self_discharge_rate_pct_per_month"))
    lifetime_cyc = _parse_float(_get_field(rec, "performance_and_durability", "expected_lifetime_cycles"))
    efficiency   = _parse_float(_get_field(rec, "performance_and_durability", "charge_discharge_efficiency_percent"))

    # Safety
    thermal_run  = _norm(_get_field(rec, "safety", "thermal_runaway_prevention"))
    ext_agent    = _norm(_get_field(rec, "safety", "extinguishing_agent"))
    explosion    = _norm(_get_field(rec, "safety", "explosion_proof_declaration"))
    bms_access   = _norm(_get_field(rec, "safety", "bms_access_permissions"))

    # Traceability
    chemistry    = _norm(_get_field(rec, "traceability_and_sourcing", "chemistry"))
    mine_lat     = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_latitude"))
    mine_lon     = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_longitude"))
    cf_total     = _parse_float(_get_field(rec, "traceability_and_sourcing", "carbon_footprint_total_kg_co2e"))
    # Carbon intensity: use per-kWh field if available, otherwise use total as proxy
    cf_intensity = _parse_float(
        rec.get("carbon_footprint_kg_co2e_per_kwh") or rec.get("carbon_intensity_kg_per_kwh")
    ) or cf_total

    issues: List[str] = [applicability_note]
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    fraud_flags: List[str] = []

    def _add_metric(key: str, met: Optional[bool], value: Any, target: Any, legal_ref: str) -> None:
        metrics[key] = {"value": value, "target": target, "met": met, "legal_ref": legal_ref}

    # Basic info checks
    basic_ok = True
    if not _present_nonempty(manufacturer):
        basic_ok = False; missing.append("manufacturer (Annex VI Part A(1) via Annex XIII(1)(a))")
    if not _present_nonempty(mfr_place):
        basic_ok = False; missing.append("manufacture_place (Annex VI Part A(3) via Annex XIII(1)(a))")
    if mfr_date is None:
        basic_ok = False; missing.append("manufacture_date (YYYY-MM) (Annex VI Part A(4) via Annex XIII(1)(a))")
    if not _present_nonempty(category) or category.upper() not in ALLOWED_CATEGORIES:
        basic_ok = False; missing.append("battery_category (EV/LMT/Industrial) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(battery_id):
        basic_ok = False; missing.append("battery_id (information identifying the battery) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(unique_id):
        basic_ok = False; missing.append("unique_identifier (QR-linked passport identifier) (Art. 77(3))")
    mid_ok, mid_note = validate_manufacturer_id(manufacturer_id)
    if not mid_ok:
        basic_ok = False; missing.append("manufacturer_id invalid or missing (traceability identity control)")

    # Technical checks
    tech_ok = True
    if not (rated_cap_ah and rated_cap_ah > 0):
        tech_ok = False; missing.append("rated_capacity_ah (Annex XIII(1)(a)(g))")
    if not (nominal_v and nominal_v > 0):
        tech_ok = False; missing.append("nominal_voltage_v (Annex XIII(1)(a)(h))")
    if not (efficiency and 0 < efficiency <= 100):
        tech_ok = False; missing.append("charge_discharge_efficiency_percent (Annex XIII(1)(a)(n): energy efficiency)")
    if not (lifetime_cyc and lifetime_cyc > 0):
        tech_ok = False; missing.append("expected_lifetime_cycles (Annex XIII(1)(a)(j))")
    if not (rated_pow_w and rated_pow_w > 0):
        tech_ok = False; missing.append("rated_power_w (Annex XIII(1)(a)(i))")
    if self_disch is None or not (0 <= self_disch <= 100):
        tech_ok = False; missing.append("self_discharge_rate_pct_per_month (Annex VII Part B(4))")

    # Safety checks
    safety_ok = True
    if not _present_nonempty(ext_agent):
        safety_ok = False; missing.append("extinguishing_agent (Annex VI Part A(9) via Annex XIII(1)(a))")
    if not _present_nonempty(thermal_run):
        safety_ok = False; missing.append("thermal_runaway_prevention (Safety info required by Annex XIII safety scope)")
    if not _present_nonempty(explosion):
        safety_ok = False; missing.append("explosion_proof_declaration (Safety info required by Annex XIII safety scope)")

    # BMS access (Article 14)
    bms_ok  = True
    bms_low = bms_access.lower()
    if not bms_low or ("read" not in bms_low and "r" not in bms_low):
        bms_ok = False; missing.append("bms_access_permissions missing read permission disclosure (Article 14)")
    if not bms_low or ("write" not in bms_low and "w" not in bms_low):
        bms_ok = False; missing.append("bms_access_permissions missing write permission disclosure (Article 14)")

    # Carbon footprint
    carbon_ok = bool(cf_total and cf_total > 0)
    if not carbon_ok:
        missing.append("carbon_footprint_total_kg_co2e (Annex XIII(1)(c) / Article 7)")

    # Hazardous substances
    materials_ok = _present_nonempty(hazardous)
    if not materials_ok:
        missing.append("hazardous_substances_declaration (Annex XIII(1)(b))")

    # Recycled content (Article 8) — only enforced when DPP is mandatory
    recycled_ok = True
    severe_violation = False
    thresholds = RECYCLED_MIN_PCT
    metal_checks = [
        ("li", li_pct,  thresholds["Lithium"], "recycled_lithium_pct",  "Article 8(2)(c)"),
        ("co", co_pct,  thresholds["Cobalt"],  "recycled_cobalt_pct",   "Article 8(2)(a)"),
        ("ni", ni_pct,  thresholds["Nickel"],  "recycled_nickel_pct",   "Article 8(2)(d)"),
        ("pb", pb_pct,  thresholds["Lead"],    "recycled_lead_pct",     "Article 8(2)(b)"),
    ]
    for _, val, thr, field_name, ref in metal_checks:
        metric_key = field_name
        if dpp_required:
            if val is None:
                recycled_ok = False
                missing.append(f"{field_name} (minimum recycled share) ({ref})")
            elif val < thr:
                recycled_ok = False
                severe_violation = True
                missing.append(f"{field_name} severe violation: {val}% < {thr}% ({ref})")
        _add_metric(metric_key, (val is not None and val >= thr), val, thr, ref)

    # Non-recycled metrics
    _add_metric("rated_capacity_ah",                   bool(rated_cap_ah and rated_cap_ah > 0),           rated_cap_ah,  None,               "Annex XIII(1)(a)(g)")
    _add_metric("nominal_voltage_v",                   bool(nominal_v and nominal_v > 0),                 nominal_v,     None,               "Annex XIII(1)(a)(h)")
    _add_metric("rated_power_w",                       bool(rated_pow_w and rated_pow_w > 0),             rated_pow_w,   None,               "Annex XIII(1)(a)(i)")
    _add_metric("self_discharge_rate_pct_per_month",   (self_disch is not None and 0 <= self_disch <= 100), self_disch,  None,               "Annex VII Part B(4)")
    _add_metric("charge_discharge_efficiency_percent", bool(efficiency and 0 < efficiency <= 100),        efficiency,    None,               "Annex XIII(1)(a)(n)")
    _add_metric("expected_lifetime_cycles",            bool(lifetime_cyc and lifetime_cyc > 0),           lifetime_cyc,  None,               "Annex XIII(1)(a)(j)")
    _add_metric("extinguishing_agent",                 _present_nonempty(ext_agent),                      ext_agent,     None,               "Annex VI Part A(9)")
    _add_metric("thermal_runaway_prevention",          _present_nonempty(thermal_run),                    thermal_run,   None,               "Annex XIII safety scope")
    _add_metric("explosion_proof_declaration",         _present_nonempty(explosion),                      explosion,     None,               "Annex XIII safety scope")
    _add_metric("hazardous_substances_declaration",    _present_nonempty(hazardous),                      hazardous,     None,               "Annex XIII(1)(b)")
    _add_metric("bms_access_permissions",              bms_ok,                                            bms_access,    "read+write",       "Article 14")
    _add_metric("carbon_footprint_total_kg_co2e",      carbon_ok,                                         cf_total,      None,               "Annex XIII(1)(c) / Article 7")
    _add_metric("unique_identifier",                   _present_nonempty(unique_id),                      unique_id,     None,               "Article 77(3)")
    _add_metric("manufacturer_id",                     mid_ok,                                            manufacturer_id, "MFG-[A-Z0-9]{6,}", "Heuristic anti-fraud check")

    # Anti-fraud: coordinates
    coords_ok, coords_note = validate_coordinates(mine_lat, mine_lon)
    _add_metric("mine_coordinates", coords_ok, f"{mine_lat},{mine_lon}", "known mining zones", "Heuristic sourcing-risk check")
    if not coords_ok:
        issues.append(f"Anti-fraud geolocation: {coords_note}")
        fraud_flags.append("HIGH_RISK")

    # Anti-fraud: carbon floor
    phys_ok, phys_note = validate_physical_carbon_floor(chemistry, cf_intensity)
    _add_metric("carbon_physical_plausibility", phys_ok, cf_intensity, f"{chemistry} floor", "Heuristic physical plausibility")
    if not phys_ok:
        issues.append(f"Anti-fraud carbon plausibility: {phys_note}")
        missing.append("carbon_footprint flagged as Data Unrealistic (below chemistry theoretical floor)")
        fraud_flags.append("DATA_UNREALISTIC")

    if not mid_ok:
        issues.append(f"Anti-fraud manufacturer-id: {mid_note}")
        fraud_flags.append("HIGH_RISK")

    # Not mandatory → analysis only
    if not dpp_required:
        issues.extend(f"Analysis (not mandatory): {x}" for x in missing)
        return DppResult(
            model=model, status="NOT_REQUIRED_DPP",
            risk_level="high" if fraud_flags else "N/A",
            issues=issues, missing_fields=[],
            metrics=metrics, fraud_flags=sorted(set(fraud_flags)),
        )

    if missing:
        risk_level = "high" if (severe_violation or len(missing) >= 2 or not coords_ok or not phys_ok) else "medium"
        return DppResult(
            model=model, status="NON_COMPLIANT", risk_level=risk_level,
            issues=issues, missing_fields=missing,
            metrics=metrics, fraud_flags=sorted(set(fraud_flags)),
        )

    return DppResult(
        model=model, status="COMPLIANT",
        risk_level="high" if fraud_flags else "low",
        issues=issues, missing_fields=[],
        metrics=metrics, fraud_flags=sorted(set(fraud_flags)),
    )


# ── CSV loader ────────────────────────────────────────────────────────────────

def iter_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        yield from reader


# ── CLI entry point ───────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="EU 2023/1542 Battery DPP checker.")
    p.add_argument("--csv",  type=str, help="Path to CSV file.")
    p.add_argument("--model",type=str, help="Battery model (single-record mode).")
    p.add_argument("--data", type=str, help="JSON object (single-record mode).")
    p.add_argument("--json", action="store_true", help="Output as JSON lines.")
    p.add_argument("--pdf",  type=str, default="DPP_Audit_Report.pdf",
                   help="PDF output path (use 'none' to disable).")
    args = p.parse_args(argv)

    results: List[DppResult] = []
    csv_path: Optional[Path] = None

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"CSV not found: {csv_path}", file=sys.stderr); return 2
        for row in iter_csv(csv_path):
            results.append(validate_record(row))
    else:
        if not args.model or not args.data:
            print("Provide --csv, or both --model and --data JSON.", file=sys.stderr); return 2
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"--data must be valid JSON: {e}", file=sys.stderr); return 2
        data["model"] = args.model
        results.append(validate_record(data))

    if args.json:
        for r in results:
            print(json.dumps({
                "model": r.model, "status": r.status, "risk_level": r.risk_level,
                "missing_fields": r.missing_fields, "issues": r.issues,
                "metrics": r.metrics, "fraud_flags": r.fraud_flags,
            }, ensure_ascii=False))
    else:
        for i, r in enumerate(results):
            if i: print("\n" + "-" * 60 + "\n")
            print(r.to_text())

    if csv_path is not None and _norm(args.pdf).lower() not in {"", "none", "off", "false", "0"}:
        out_pdf = Path(args.pdf)
        try:
            from pdf_generator import generate_audit_pdf
            out_pdf.write_bytes(generate_audit_pdf(results))
            if not args.json:
                print(f"\n{'='*60}\nPDF report written: {out_pdf.resolve()}")
        except Exception as e:
            print(f"Failed to write PDF: {e}", file=sys.stderr); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
