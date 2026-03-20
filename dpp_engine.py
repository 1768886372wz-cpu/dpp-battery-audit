#!/usr/bin/env python3
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


# Core DPP obligations extracted from Regulation (EU) 2023/1542:
# - Art. 77(1): from 18 Feb 2027, DPP applies to LMT; industrial > 2 kWh; EV batteries.
# - Art. 77(3): passport accessible via QR code linking to a unique identifier.
# - Annex XIII(1)(a)-(c): publicly accessible battery-model info includes Annex VI Part A label info,
#   material composition (incl chemistry, hazardous substances, critical raw materials), and carbon footprint info.
# - Annex XIII + Annex VI Part A are the source for fields like manufacturer/labeling/extinguishing agent.
# - Art. 8 sets minimum recycled content targets (cobalt/lithium/nickel/lead) and is referenced by Annex XIII recycled content info.
# - Art. 7 + Annex XIII(1)(c) covers carbon footprint reporting information.


ALLOWED_CATEGORIES = {"LMT", "INDUSTRIAL", "EV"}

# Recycled content minimum shares requested for pre-audit checks (severe violation if below).
# Legal basis: Article 8(2)(a)-(d).
RECYCLED_MIN_PCT = {
    "Lithium": 6.0,
    "Cobalt": 16.0,
    "Nickel": 6.0,
    "Lead": 85.0,
}
RECYCLED_LEGAL_REF = "Article 8(2)(a)-(d)"

# Full Annex XIII-oriented field map for backend normalization and audit tracing.
# This structure is the single source of truth for the engine's expected inputs.
DPP_FIELD_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    "public_information": {
        "unique_identifier": {"aliases": ["unique_identifier", "battery_passport_id", "uid", "唯一标识"], "legal_ref": "Article 77(3)"},
        "battery_id": {"aliases": ["battery_id", "battery_identifier", "serial", "battery_model_id", "电池识别码"], "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
        "manufacturer_id": {"aliases": ["manufacturer_id", "mfg_id", "制造商ID"], "legal_ref": "Heuristic anti-fraud identity check (not an explicit statutory field in Annex XIII list)"},
        "manufacturer": {"aliases": ["manufacturer", "manufacturer_name", "制造商"], "legal_ref": "Annex VI Part A(1) via Annex XIII(1)(a)"},
        "manufacture_place": {"aliases": ["manufacture_place", "place_of_manufacture", "生产地"], "legal_ref": "Annex VI Part A(3) via Annex XIII(1)(a)"},
        "manufacture_date": {"aliases": ["manufacture_date", "date_of_manufacture", "生产日期"], "legal_ref": "Annex VI Part A(4) via Annex XIII(1)(a)"},
        "category": {"aliases": ["category", "battery_category", "类别"], "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
    },
    "materials_and_compliance": {
        "recycled_lithium_pct": {"aliases": ["recycled_lithium_pct", "lithium_pct"], "legal_ref": "Article 8(2)(c)", "min": 6.0},
        "recycled_cobalt_pct": {"aliases": ["recycled_cobalt_pct", "cobalt_pct"], "legal_ref": "Article 8(2)(a)", "min": 16.0},
        "recycled_nickel_pct": {"aliases": ["recycled_nickel_pct", "nickel_pct"], "legal_ref": "Article 8(2)(d)", "min": 6.0},
        "recycled_lead_pct": {"aliases": ["recycled_lead_pct", "lead_pct"], "legal_ref": "Article 8(2)(b)", "min": 85.0},
        "hazardous_substances_declaration": {"aliases": ["hazardous_substances_declaration", "hazardous_substances", "hazardous", "危险物质声明"], "legal_ref": "Annex XIII(1)(b)"},
    },
    "performance_and_durability": {
        "rated_capacity_ah": {"aliases": ["rated_capacity_ah", "rated_capacity", "额定容量"], "legal_ref": "Annex XIII(1)(a)(g)"},
        "nominal_voltage_v": {"aliases": ["nominal_voltage_v", "nominal_voltage", "标称电压"], "legal_ref": "Annex XIII(1)(a)(h)"},
        "rated_power_w": {"aliases": ["rated_power_w", "power_w", "额定功率"], "legal_ref": "Annex XIII(1)(a)(i)"},
        "self_discharge_rate_pct_per_month": {"aliases": ["self_discharge_rate_pct_per_month", "self_discharge_rate", "自放电率"], "legal_ref": "Annex VII Part B(4)"},
        "expected_lifetime_cycles": {"aliases": ["expected_lifetime_cycles", "cycles", "预期寿命_cycles"], "legal_ref": "Annex XIII(1)(a)(j)"},
        "charge_discharge_efficiency_percent": {"aliases": ["charge_discharge_efficiency_percent", "efficiency_percent", "充放电效率_percent", "充放电效率"], "legal_ref": "Annex XIII(1)(a)(n)"},
    },
    "safety": {
        "thermal_runaway_prevention": {"aliases": ["thermal_runaway_prevention", "thermal_runaway_control", "热失控预防"], "legal_ref": "Heuristic safety-control data check (industry best practice)"},
        "extinguishing_agent": {"aliases": ["extinguishing_agent", "Extinguishing Agent", "灭火剂类型"], "legal_ref": "Annex VI Part A(9) via Annex XIII(1)(a)"},
        "explosion_proof_declaration": {"aliases": ["explosion_proof_declaration", "explosion_proof", "防爆声明"], "legal_ref": "Heuristic safety-control data check (industry best practice)"},
        "bms_access_permissions": {"aliases": ["bms_access_permissions", "bms_access", "bms_rw_permissions", "BMS访问权限"], "legal_ref": "Article 14"},
    },
    "traceability_and_sourcing": {
        "mine_latitude": {"aliases": ["mine_latitude", "source_mine_lat", "矿山纬度"], "legal_ref": "Heuristic sourcing-risk check (due diligence context)"},
        "mine_longitude": {"aliases": ["mine_longitude", "source_mine_lon", "矿山经度"], "legal_ref": "Heuristic sourcing-risk check (due diligence context)"},
        "chemistry": {"aliases": ["chemistry", "电化学体系"], "legal_ref": "Annex XIII(1)(b)"},
        "carbon_footprint_total_kg_co2e": {"aliases": ["carbon_footprint_total_kg_co2e", "carbon_footprint_total", "carbon_footprint_kg_co2e_total", "生命周期碳排放总量", "碳足迹_总量_kgco2e"], "legal_ref": "Annex XIII(1)(c) / Article 7"},
    },
}

# Approximate benchmark lower bounds for plausibility checks, not legal thresholds.
# Used only for anti-fraud "Data Unrealistic" flag.
CARBON_FOOTPRINT_MIN_BY_CHEMISTRY = {
    # theoretical floor in kg CO2e per kWh
    "LFP": 30.0,
    "NMC": 40.0,
}

# Simplified mining-area bounding boxes for anti-fraud coordinate checks.
# (lat_min, lat_max, lon_min, lon_max)
KNOWN_LITHIUM_COBALT_MINING_ZONES: List[Tuple[float, float, float, float]] = [
    (-30.0, -15.0, -72.0, -65.0),   # Chile/Argentina lithium triangle (coarse)
    (-25.0, -18.0, 16.0, 30.0),     # Southern Africa lithium belt (coarse)
    (-15.0, 5.0, 12.0, 33.0),       # DRC cobalt region (coarse)
    (-33.0, -20.0, 114.0, 122.0),   # Western Australia lithium region (coarse)
]


def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _parse_float(value: Any) -> Optional[float]:
    s = _norm(value)
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_yyyy_mm(value: Any) -> Optional[str]:
    s = _norm(value)
    if s == "":
        return None
    # Accept YYYY-MM only (month+year is explicitly mentioned for manufacture date in Annex VI Part A(4)).
    if not re.fullmatch(r"\d{4}-\d{2}", s):
        return None
    try:
        datetime.strptime(s, "%Y-%m")
        return s
    except ValueError:
        return None


def _parse_listish(value: Any) -> List[str]:
    """
    Accepts either:
    - JSON list: ["Ni","Co"]
    - or comma/semicolon separated string: "Ni, Co; Li"
    """
    s = _norm(value)
    if s == "":
        return []
    if s.startswith("["):
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x).strip()]
        except Exception:
            pass
    parts = re.split(r"[;,]", s)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class DppResult:
    model: str
    status: str  # COMPLIANT / NON_COMPLIANT / NOT_REQUIRED_DPP
    risk_level: str  # low / medium / high / N/A
    issues: List[str]  # human-readable, must include legal references
    missing_fields: List[str]  # subset of issues focused on "missing/invalid required fields"
    metrics: Dict[str, Any]  # for radar text summary
    fraud_flags: List[str]  # e.g. HIGH_RISK, DATA_UNREALISTIC

    def to_text(self) -> str:
        lines = [
            f"Model: {self.model}",
            f"Status: {self.status}",
            f"Risk: {self.risk_level}",
        ]
        if self.missing_fields:
            lines.append("Missing fields: " + ", ".join(self.missing_fields))
        if self.issues:
            lines.append("Findings:")
            for i in self.issues:
                lines.append(f"- {i}")
        if self.fraud_flags:
            lines.append("Fraud Flags: " + ", ".join(self.fraud_flags))
        return "\n".join(lines)


def _install_hint() -> str:
    return (
        "PDF generation requires 'reportlab'. Install it with:\n"
        "  source .venv/bin/activate && pip install reportlab\n"
        "or (if you don't use the venv):\n"
        "  python3 -m venv .venv && source .venv/bin/activate && pip install reportlab\n"
    )


def dpp_applicability(category: str, capacity_kwh: Optional[float]) -> Tuple[bool, str]:
    """
    Returns:
      - required: whether battery DPP is mandatory (Art. 77(1))
      - note: human-readable applicability note (must include legal ref)
    """
    cat = _norm(category).upper()
    if cat not in ALLOWED_CATEGORIES:
        return False, f"Invalid battery category (expected EV/LMT/Industrial)."

    if cat == "INDUSTRIAL":
        if capacity_kwh is None:
            # Cannot determine whether it is <=2 kWh or >2 kWh.
            return True, "Industrial battery: capacity_kwh missing; cannot confirm Art. 77(1) exemption (capacity > 2 kWh)."
        if capacity_kwh <= 2.0:
            return False, "Industrial battery with capacity <= 2 kWh: DPP not mandatory (Art. 77(1) exemption for capacity > 2 kWh)."
        return True, "Industrial battery: DPP mandatory only if capacity_kwh > 2 kWh (Art. 77(1))."

    # LMT and EV batteries
    return True, f"{cat} battery: DPP mandatory from 18 February 2027 (Art. 77(1))."


def _parse_percent_to_pct(value: Any) -> Optional[float]:
    """
    Accepts either:
    - already in percent (e.g. 6, 16, 85)
    - ratio (e.g. 0.06, 0.16, 0.85)
    """
    f = _parse_float(value)
    if f is None:
        return None
    # If it's a ratio, convert to percent.
    if 0.0 <= f <= 1.0:
        f = f * 100.0
    # Basic sanity bounds.
    if f < 0 or f > 100:
        return None
    return f


def _present_nonempty(value: Any) -> bool:
    return _norm(value) != ""


def _get_field(rec: Dict[str, Any], module: str, key: str) -> Any:
    info = DPP_FIELD_MAP[module][key]
    for alias in info["aliases"]:
        if alias in rec and _norm(rec.get(alias)) != "":
            return rec.get(alias)
    return None


def validate_coordinates(latitude: Optional[float], longitude: Optional[float]) -> Tuple[bool, str]:
    """
    Anti-fraud geolocation heuristic check:
    If declared mine coordinates are outside known lithium/cobalt mining areas,
    return High Risk.
    """
    if latitude is None or longitude is None:
        return False, "Missing mine coordinates; cannot validate sourcing geolocation."

    in_known_zone = any(
        lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max
        for lat_min, lat_max, lon_min, lon_max in KNOWN_LITHIUM_COBALT_MINING_ZONES
    )
    if in_known_zone:
        return True, "Mine coordinates are within known lithium/cobalt mining regions."
    return False, "Mine coordinates are outside known lithium/cobalt mining regions (High Risk)."


def validate_physical_carbon_floor(chemistry: str, carbon_footprint_total: Optional[float]) -> Tuple[bool, str]:
    """
    Anti-fraud plausibility heuristic:
    If reported carbon footprint is below chemistry-specific physical floor,
    flag as Data Unrealistic.
    """
    c = _norm(chemistry).upper()
    if carbon_footprint_total is None:
        return False, "Carbon footprint missing; cannot run physical plausibility check."
    if c not in CARBON_FOOTPRINT_MIN_BY_CHEMISTRY:
        return True, f"No chemistry floor configured for {c}; plausibility check skipped."

    floor = CARBON_FOOTPRINT_MIN_BY_CHEMISTRY[c]
    if carbon_footprint_total < floor:
        return False, f"Data Unrealistic: carbon footprint {carbon_footprint_total} is below {c} physical floor {floor}."
    return True, f"Carbon footprint is above {c} physical floor ({floor})."


def validate_manufacturer_id(manufacturer_id: str) -> Tuple[bool, str]:
    """
    Simple structural heuristic validation for manufacturer IDs.
    Expected format: MFG-XXXXXX (at least 6 uppercase alnum chars after prefix).
    """
    mid = _norm(manufacturer_id)
    if not mid:
        return False, "manufacturer_id missing."
    if re.fullmatch(r"MFG-[A-Z0-9]{6,}", mid):
        return True, "manufacturer_id format is valid."
    return False, f"manufacturer_id '{mid}' failed format validation."


def _compute_carbon_intensity_kg_per_kwh(
    rec: Dict[str, Any],
    carbon_footprint_total: Optional[float],
    capacity_kwh: Optional[float],
) -> Optional[float]:
    direct = _parse_float(rec.get("carbon_footprint_kg_co2e_per_kwh") or rec.get("carbon_intensity_kg_per_kwh"))
    if direct is not None:
        return direct
    # Fallback assumption for heterogeneous client datasets:
    # many feeds already provide a carbon-intensity-like value in this column.
    if carbon_footprint_total is not None:
        return carbon_footprint_total
    return None


def validate_record(rec: Dict[str, Any]) -> DppResult:
    model = _norm(rec.get("model") or rec.get("battery_model") or rec.get("型号") or rec.get("Model"))
    if not model:
        model = "<unknown>"

    category = _norm(_get_field(rec, "public_information", "category"))
    capacity_kwh = _parse_float(rec.get("capacity_kwh") or rec.get("capacity_kWh") or rec.get("capacity") or rec.get("容量_kwh"))

    dpp_required, applicability_note = dpp_applicability(category, capacity_kwh)

    # Public information
    unique_identifier = _norm(_get_field(rec, "public_information", "unique_identifier"))
    battery_id = _norm(_get_field(rec, "public_information", "battery_id"))
    manufacturer_id = _norm(_get_field(rec, "public_information", "manufacturer_id"))
    manufacturer = _norm(_get_field(rec, "public_information", "manufacturer"))
    manufacture_place = _norm(_get_field(rec, "public_information", "manufacture_place"))
    manufacture_date = _parse_yyyy_mm(_get_field(rec, "public_information", "manufacture_date"))

    # Materials and compliance
    li_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lithium_pct"))
    co_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_cobalt_pct"))
    ni_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_nickel_pct"))
    pb_pct = _parse_percent_to_pct(_get_field(rec, "materials_and_compliance", "recycled_lead_pct"))
    hazardous_decl = _norm(_get_field(rec, "materials_and_compliance", "hazardous_substances_declaration"))

    # Performance and durability
    rated_capacity_ah = _parse_float(_get_field(rec, "performance_and_durability", "rated_capacity_ah"))
    nominal_voltage_v = _parse_float(_get_field(rec, "performance_and_durability", "nominal_voltage_v"))
    rated_power_w = _parse_float(_get_field(rec, "performance_and_durability", "rated_power_w"))
    self_discharge = _parse_float(_get_field(rec, "performance_and_durability", "self_discharge_rate_pct_per_month"))
    expected_lifetime_cycles = _parse_float(_get_field(rec, "performance_and_durability", "expected_lifetime_cycles"))
    efficiency_pct = _parse_float(_get_field(rec, "performance_and_durability", "charge_discharge_efficiency_percent"))

    # Safety
    thermal_runaway = _norm(_get_field(rec, "safety", "thermal_runaway_prevention"))
    extinguishing_agent = _norm(_get_field(rec, "safety", "extinguishing_agent"))
    explosion_decl = _norm(_get_field(rec, "safety", "explosion_proof_declaration"))
    bms_access = _norm(_get_field(rec, "safety", "bms_access_permissions"))

    # Traceability + carbon
    chemistry = _norm(_get_field(rec, "traceability_and_sourcing", "chemistry"))
    mine_lat = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_latitude"))
    mine_lon = _parse_float(_get_field(rec, "traceability_and_sourcing", "mine_longitude"))
    carbon_footprint_total = _parse_float(_get_field(rec, "traceability_and_sourcing", "carbon_footprint_total_kg_co2e"))
    carbon_intensity_kg_per_kwh = _compute_carbon_intensity_kg_per_kwh(rec, carbon_footprint_total, capacity_kwh)

    issues: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    fraud_flags: List[str] = []

    # Applicability
    issues.append(applicability_note)

    # For radar metrics, we still compute whether thresholds are met.
    # Recycled metric checks only apply when DPP is mandatory.
    def _add_metric(key: str, met: Optional[bool], value: Any, target: Any, legal_ref: str) -> None:
        metrics[key] = {
            "value": value,
            "target": target,
            "met": met,
            "legal_ref": legal_ref,
        }

    # Validate mandatory/basic info
    basic_ok = True

    if not _present_nonempty(manufacturer):
        basic_ok = False
        missing.append("manufacturer (Annex VI Part A(1) via Annex XIII(1)(a))")
    if not _present_nonempty(manufacture_place):
        basic_ok = False
        missing.append("manufacture_place (Annex VI Part A(3) via Annex XIII(1)(a))")
    if manufacture_date is None:
        basic_ok = False
        missing.append("manufacture_date (YYYY-MM) (Annex VI Part A(4) via Annex XIII(1)(a))")
    if not _present_nonempty(category) or category.upper() not in ALLOWED_CATEGORIES:
        basic_ok = False
        missing.append("battery_category (EV/LMT/Industrial) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(battery_id):
        basic_ok = False
        missing.append("battery_id (information identifying the battery) (Annex VI Part A(2) via Annex XIII(1)(a))")
    if not _present_nonempty(unique_identifier):
        basic_ok = False
        missing.append("unique_identifier (QR-linked passport identifier) (Art. 77(3))")
    manufacturer_id_ok, manufacturer_id_note = validate_manufacturer_id(manufacturer_id)
    if not manufacturer_id_ok:
        basic_ok = False
        missing.append("manufacturer_id invalid or missing (traceability identity control)")

    # Technical checks
    tech_ok = True
    if rated_capacity_ah is None or rated_capacity_ah <= 0:
        tech_ok = False
        missing.append("rated_capacity_ah (Annex XIII(1)(a)(g))")
    if nominal_voltage_v is None or nominal_voltage_v <= 0:
        tech_ok = False
        missing.append("nominal_voltage_v (Annex XIII(1)(a)(h))")
    if efficiency_pct is None or efficiency_pct <= 0 or efficiency_pct > 100:
        tech_ok = False
        missing.append("charge_discharge_efficiency_percent (Annex XIII(1)(a)(n): energy efficiency)")
    if expected_lifetime_cycles is None or expected_lifetime_cycles <= 0:
        tech_ok = False
        missing.append("expected_lifetime_cycles (Annex XIII(1)(a)(j))")
    if rated_power_w is None or rated_power_w <= 0:
        tech_ok = False
        missing.append("rated_power_w (Annex XIII(1)(a)(i))")
    if self_discharge is None or self_discharge < 0 or self_discharge > 100:
        tech_ok = False
        missing.append("self_discharge_rate_pct_per_month (Annex VII Part B(4))")

    # Safety
    safety_ok = True
    if not _present_nonempty(extinguishing_agent):
        safety_ok = False
        missing.append("extinguishing_agent (Annex VI Part A(9) via Annex XIII(1)(a))")
    if not _present_nonempty(thermal_runaway):
        safety_ok = False
        missing.append("thermal_runaway_prevention (Safety info required by Annex XIII safety scope)")
    if not _present_nonempty(explosion_decl):
        safety_ok = False
        missing.append("explosion_proof_declaration (Safety info required by Annex XIII safety scope)")

    # BMS access permissions check (Article 14)
    bms_ok = True
    bms_lower = bms_access.lower()
    if not bms_lower or ("read" not in bms_lower and "r" not in bms_lower):
        bms_ok = False
        missing.append("bms_access_permissions missing read permission disclosure (Article 14)")
    if not bms_lower or ("write" not in bms_lower and "w" not in bms_lower):
        bms_ok = False
        missing.append("bms_access_permissions missing write permission disclosure (Article 14)")

    # Carbon
    carbon_ok = True
    if carbon_footprint_total is None or carbon_footprint_total <= 0:
        carbon_ok = False
        missing.append("carbon_footprint_total_kg_co2e (Annex XIII(1)(c) / Article 7)")

    # Materials declaration
    materials_ok = True
    if not _present_nonempty(hazardous_decl):
        materials_ok = False
        missing.append("hazardous_substances_declaration (Annex XIII(1)(b))")

    # Recycled content checks + severe violation rule
    recycled_ok = True
    severe_recycled_violation = False
    if dpp_required:
        thresholds = RECYCLED_MIN_PCT

        for label, target in thresholds.items():
            pass

        # Lithium
        if li_pct is None or li_pct < thresholds["Lithium"]:
            recycled_ok = False
            if li_pct is None:
                missing.append("recycled_lithium_pct (minimum recycled lithium share) (Article 8(2)(c))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_lithium_pct severe violation: {li_pct}% < {thresholds['Lithium']}% (Article 8(2)(c))"
                )
        # Cobalt
        if co_pct is None or co_pct < thresholds["Cobalt"]:
            recycled_ok = False
            if co_pct is None:
                missing.append("recycled_cobalt_pct (minimum recycled cobalt share) (Article 8(2)(a))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_cobalt_pct severe violation: {co_pct}% < {thresholds['Cobalt']}% (Article 8(2)(a))"
                )
        # Nickel
        if ni_pct is None or ni_pct < thresholds["Nickel"]:
            recycled_ok = False
            if ni_pct is None:
                missing.append("recycled_nickel_pct (minimum recycled nickel share) (Article 8(2)(d))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_nickel_pct severe violation: {ni_pct}% < {thresholds['Nickel']}% (Article 8(2)(d))"
                )
        # Lead
        if pb_pct is None or pb_pct < thresholds["Lead"]:
            recycled_ok = False
            if pb_pct is None:
                missing.append("recycled_lead_pct (minimum recycled lead share) (Article 8(2)(b))")
            else:
                severe_recycled_violation = True
                missing.append(
                    f"recycled_lead_pct severe violation: {pb_pct}% < {thresholds['Lead']}% (Article 8(2)(b))"
                )

        _add_metric("recycled_lithium_pct", (li_pct is not None and li_pct >= thresholds["Lithium"]), li_pct, thresholds["Lithium"], "Article 8(2)(c)")
        _add_metric("recycled_cobalt_pct", (co_pct is not None and co_pct >= thresholds["Cobalt"]), co_pct, thresholds["Cobalt"], "Article 8(2)(a)")
        _add_metric("recycled_nickel_pct", (ni_pct is not None and ni_pct >= thresholds["Nickel"]), ni_pct, thresholds["Nickel"], "Article 8(2)(d)")
        _add_metric("recycled_lead_pct", (pb_pct is not None and pb_pct >= thresholds["Lead"]), pb_pct, thresholds["Lead"], "Article 8(2)(b)")
    else:
        # DPP not mandatory: we still compute metrics but don't enforce.
        _add_metric("recycled_lithium_pct", (li_pct is not None and li_pct >= RECYCLED_MIN_PCT["Lithium"]), li_pct, RECYCLED_MIN_PCT["Lithium"], "Article 8(2)(c)")
        _add_metric("recycled_cobalt_pct", (co_pct is not None and co_pct >= RECYCLED_MIN_PCT["Cobalt"]), co_pct, RECYCLED_MIN_PCT["Cobalt"], "Article 8(2)(a)")
        _add_metric("recycled_nickel_pct", (ni_pct is not None and ni_pct >= RECYCLED_MIN_PCT["Nickel"]), ni_pct, RECYCLED_MIN_PCT["Nickel"], "Article 8(2)(d)")
        _add_metric("recycled_lead_pct", (pb_pct is not None and pb_pct >= RECYCLED_MIN_PCT["Lead"]), pb_pct, RECYCLED_MIN_PCT["Lead"], "Article 8(2)(b)")

    _add_metric("rated_capacity_ah", (rated_capacity_ah is not None and rated_capacity_ah > 0), rated_capacity_ah, None, "Annex XIII(1)(a)(g)")
    _add_metric("unique_identifier", (_present_nonempty(unique_identifier)), unique_identifier, None, "Article 77(3)")
    _add_metric("nominal_voltage_v", (nominal_voltage_v is not None and nominal_voltage_v > 0), nominal_voltage_v, None, "Annex XIII(1)(a)(h)")
    _add_metric("rated_power_w", (rated_power_w is not None and rated_power_w > 0), rated_power_w, None, "Annex XIII(1)(a)(i)")
    _add_metric("self_discharge_rate_pct_per_month", (self_discharge is not None and 0 <= self_discharge <= 100), self_discharge, None, "Annex VII Part B(4)")
    _add_metric("charge_discharge_efficiency_percent", (efficiency_pct is not None and 0 < efficiency_pct <= 100), efficiency_pct, None, "Annex XIII(1)(a)(n)")
    _add_metric("expected_lifetime_cycles", (expected_lifetime_cycles is not None and expected_lifetime_cycles > 0), expected_lifetime_cycles, None, "Annex XIII(1)(a)(j)")
    _add_metric("extinguishing_agent", (_present_nonempty(extinguishing_agent)), extinguishing_agent, None, "Annex VI Part A(9) via Annex XIII(1)(1)(a)")
    _add_metric("thermal_runaway_prevention", (_present_nonempty(thermal_runaway)), thermal_runaway, None, "Annex XIII safety scope")
    _add_metric("explosion_proof_declaration", (_present_nonempty(explosion_decl)), explosion_decl, None, "Annex XIII safety scope")
    _add_metric("hazardous_substances_declaration", (_present_nonempty(hazardous_decl)), hazardous_decl, None, "Annex XIII(1)(b)")
    _add_metric("bms_access_permissions", bms_ok, bms_access, "read+write disclosure", "Article 14")
    _add_metric("carbon_footprint_total_kg_co2e", (carbon_footprint_total is not None and carbon_footprint_total > 0), carbon_footprint_total, None, "Annex XIII(1)(c) / Article 7")
    _add_metric("manufacturer_id", manufacturer_id_ok, manufacturer_id, "MFG-[A-Z0-9]{6,}", "Heuristic anti-fraud check")

    # Anti-fraud checks
    coords_ok, coords_note = validate_coordinates(mine_lat, mine_lon)
    _add_metric("mine_coordinates", coords_ok, f"{mine_lat},{mine_lon}", "major mining countries/zones", "Heuristic sourcing-risk check")
    if not coords_ok:
        issues.append(f"Anti-fraud geolocation heuristic: {coords_note}")
        fraud_flags.append("HIGH_RISK")

    physical_ok, physical_note = validate_physical_carbon_floor(chemistry, carbon_intensity_kg_per_kwh)
    _add_metric("carbon_physical_plausibility", physical_ok, carbon_intensity_kg_per_kwh, f"{chemistry} floor (kgCO2e/kWh)", "Heuristic physical plausibility check")
    if not physical_ok:
        issues.append(f"Anti-fraud physical plausibility heuristic: {physical_note}")
        # Treat physically impossible declaration as an audit failure.
        missing.append("carbon_footprint flagged as Data Unrealistic (below chemistry theoretical floor, heuristic)")
        fraud_flags.append("DATA_UNREALISTIC")

    if not manufacturer_id_ok:
        issues.append(f"Anti-fraud manufacturer-id heuristic: {manufacturer_id_note}")
        fraud_flags.append("HIGH_RISK")

    # If DPP is NOT mandatory, we only show analysis.
    if not dpp_required:
        issues.extend([f"Analysis (not mandatory): {x}" for x in missing])
        if not coords_ok:
            issues.append("High Risk due to sourcing coordinate anomaly.")
        if not physical_ok:
            issues.append("Data Unrealistic due to carbon footprint below physical floor.")
        if not manufacturer_id_ok:
            issues.append("High Risk due to manufacturer identity inconsistency.")
        return DppResult(
            model=model,
            status="NOT_REQUIRED_DPP",
            risk_level="high" if (not coords_ok or not physical_ok or not manufacturer_id_ok) else "N/A",
            issues=issues,
            missing_fields=[],
            metrics=metrics,
            fraud_flags=sorted(set(fraud_flags)),
        )

    # Final compliance decision for mandatory cases
    if not basic_ok:
        issues.extend([f"Basic info non-compliance: {x}" for x in missing if "manufacturer" in x or "manufacture_place" in x or "manufacture_date" in x or "battery_category" in x or "battery_id" in x or "unique_identifier" in x])
    if not tech_ok:
        issues.extend([f"Technical parameters non-compliance: {x}" for x in missing if "rated_capacity_ah" in x or "nominal_voltage_v" in x or "charge_discharge_efficiency_percent" in x or "expected_lifetime_cycles" in x])
    if not safety_ok:
        issues.extend([f"Safety non-compliance: {x}" for x in missing if "extinguishing_agent" in x])
    if not carbon_ok:
        issues.extend([f"Carbon footprint non-compliance: {x}" for x in missing if "carbon_footprint_total" in x])
    if not recycled_ok:
        issues.extend([f"Recycled content non-compliance (severe if below targets): {x}" for x in missing if x.startswith("recycled_")])
    if not materials_ok:
        issues.extend([f"Materials declaration non-compliance: {x}" for x in missing if "hazardous_substances_declaration" in x])
    if not bms_ok:
        issues.extend([f"BMS access non-compliance: {x}" for x in missing if "bms_access_permissions" in x])
    if not manufacturer_id_ok:
        issues.extend([f"Manufacturer identity non-compliance: {x}" for x in missing if "manufacturer_id" in x])
    if not physical_ok:
        issues.append("Data Unrealistic (carbon footprint physical plausibility failure).")
    if not coords_ok:
        issues.append("High Risk (mine coordinates outside known lithium/cobalt zones).")
    if not manufacturer_id_ok:
        issues.append("High Risk (manufacturer_id failed validation).")

    if missing:
        risk_level = "high" if severe_recycled_violation or (len(missing) >= 2) or (not coords_ok) or (not physical_ok) else "medium"
        return DppResult(
            model=model,
            status="NON_COMPLIANT",
            risk_level=risk_level,
            issues=issues + [],
            missing_fields=missing,
            metrics=metrics,
            fraud_flags=sorted(set(fraud_flags)),
        )

    return DppResult(
        model=model,
        status="COMPLIANT",
        risk_level="high" if (not coords_ok or not physical_ok or not manufacturer_id_ok) else "low",
        issues=issues,
        missing_fields=[],
        metrics=metrics,
        fraud_flags=sorted(set(fraud_flags)),
    )


def iter_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        for row in reader:
            yield row


def generate_audit_pdf(
    *,
    results: List[DppResult],
    source_csv: Path,
    output_pdf: Path,
    language: str = "zh",
    report_no: str = "",
    client_name: str = "",
    project_code: str = "",
) -> None:
    """Single canonical fpdf2-based PDF generator.

    Parameters
    ----------
    results       : audit results from validate_record()
    source_csv    : path used only for the filename label on the cover
    output_pdf    : destination path for the generated PDF
    language      : "zh" (default) for Chinese-primary labels; "en" for English-primary
    report_no     : optional report identifier shown on cover (e.g. "DPP-2026-PRE-ABCD1234")
    client_name   : optional client/company name shown on cover
    project_code  : optional project code shown on cover
    """
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            str(e) + "\n\nInstall with:  source .venv/bin/activate && pip install fpdf2"
        ) from e

    # ── Label dictionaries (switch by language) ────────────────────────────
    _ZH = language == "zh"

    L_ZH: Dict[str, str] = {
        "title": "欧盟 2023/1542 电池法案合规预审计报告",
        "sub":   "EU 2023/1542 Battery Regulation – Compliance Pre-Audit Report",
        "grade": "合规等级",
        "time":  "审计时间",
        "src":   "数据来源",
        "client":"客户",
        "proj":  "项目",
        "rptno": "报告编号",
        "scope": (
            "适用范围：自 2027-02-18 起，LMT 电池、容量 > 2 kWh 的工业电池"
            " 及电动汽车电池须具备电池护照（Art. 77(1)）。"
        ),
        "summary": "型号级别审计结果汇总",
        "model":   "型号",
        "status":  "判定结果",
        "risk":    "风险等级",
        "issues":  "问题说明 / 法规引用",
        "compliant":     "COMPLIANT / 合规",
        "non_compliant": "NON_COMPLIANT / 不合规",
        "not_required":  "NOT_REQUIRED_DPP / 不强制执行",
        "manual": "建议人工复核（潜在欺诈风险）",
        "radar":  "合规六维指标雷达",
        "gap":    "差额修复清单 (Gap Fixing List)",
        "no_gap": "未检测到关键缺口；请保持定期数据更新与证据留痕。",
        "rec_title": "专业建议",
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

    L_EN: Dict[str, str] = {
        "title": "EU 2023/1542 Battery Regulation Compliance Pre-Audit Report",
        "sub":   "Powered by DPP Expert 3.0 – Sino-British Sustainable Development Research Group",
        "grade": "Compliance Grade",
        "time":  "Audit Time",
        "src":   "Data Source",
        "client":"Client",
        "proj":  "Project",
        "rptno": "Report No.",
        "scope": (
            "Scope: From 18 Feb 2027, LMT batteries, industrial batteries > 2 kWh,"
            " and EV batteries shall have a battery passport (Art. 77(1))."
        ),
        "summary": "Model-Level Audit Summary",
        "model":   "Model",
        "status":  "Status",
        "risk":    "Risk Level",
        "issues":  "Issues & Legal References",
        "compliant":     "COMPLIANT",
        "non_compliant": "NON_COMPLIANT",
        "not_required":  "NOT_REQUIRED_DPP",
        "manual": "Manual Review Recommended (Potential Fraud Risk)",
        "radar":  "6-Dimension Compliance Metrics Radar",
        "gap":    "Gap Fixing List",
        "no_gap": "No critical gaps detected; maintain periodic data-quality monitoring.",
        "rec_title": "Professional Recommendations",
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

    L = L_ZH if _ZH else L_EN

    # ── Compliance grade ───────────────────────────────────────────────────
    total_cnt = len(results) or 1
    non_cnt = sum(1 for r in results if r.status == "NON_COMPLIANT")
    flag_cnt = sum(
        1 for r in results
        if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or []))
    )
    if non_cnt / total_cnt > 0.35 or flag_cnt > max(1, total_cnt // 3):
        grade = "C"
    elif non_cnt / total_cnt > 0.10 or flag_cnt > 0:
        grade = "B"
    else:
        grade = "A"

    # ── Font setup ─────────────────────────────────────────────────────────
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(left=18, top=15, right=18)

    font_r = "Helvetica"   # regular
    font_b = "Helvetica"   # bold (same; use style="B")

    if _ZH:
        cjk_candidates = [
            ("/Library/Fonts/Arial Unicode.ttf",      "ArialUnicode"),
            ("/System/Library/Fonts/PingFang.ttc",    "PingFang"),
            ("/System/Library/Fonts/STHeiti Light.ttc","STHeitiL"),
        ]
        for fpath, fname in cjk_candidates:
            if Path(fpath).exists():
                try:
                    pdf.add_font(fname, "", fpath)
                    pdf.add_font(fname, "B", fpath)
                    font_r = fname
                    font_b = fname
                    break
                except Exception:
                    continue
        # If no CJK font found, fall back to English labels to avoid tofu
        if font_r == "Helvetica":
            L = L_EN

    # ── Helper: watermark (call after add_page) ────────────────────────────
    def _watermark() -> None:
        pdf.set_text_color(210, 210, 210)
        pdf.set_font("Helvetica", "B", 18)
        with pdf.rotation(32, x=105, y=148):
            pdf.text(15, 148, L["watermark"])
        pdf.set_text_color(0, 0, 0)

    # ── Helper: cell with newline (replaces deprecated ln=1) ──────────────
    def _cell(w: float, h: float, txt: str, **kw) -> None:
        pdf.cell(w, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT, **kw)

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    pdf.ln(18)
    pdf.set_font(font_b, "B", 20)
    pdf.set_text_color(11, 61, 145)
    pdf.multi_cell(0, 11, L["title"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(3)
    pdf.set_font(font_r, "", 11)
    pdf.multi_cell(0, 7, L["sub"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

    pdf.ln(8)
    pdf.set_draw_color(11, 61, 145)
    pdf.set_line_width(0.8)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(8)

    # Grade badge
    grade_color = {
        "A": (27, 94, 32),
        "B": (230, 126, 34),
        "C": (176, 0, 32),
    }.get(grade, (0, 0, 0))
    pdf.set_font(font_b, "B", 28)
    pdf.set_text_color(*grade_color)
    pdf.multi_cell(0, 14, f"{L['grade']}: {grade}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_font(font_r, "", 11)
    now_str = datetime.now().strftime("%Y-%m-%d  %H:%M")
    meta_rows = [
        (L["time"],   now_str),
        (L["src"],    source_csv.name),
    ]
    if client_name:
        meta_rows.insert(0, (L["client"], client_name))
    if project_code:
        meta_rows.insert(1, (L["proj"],   project_code))
    if report_no:
        meta_rows.insert(2, (L["rptno"],  report_no))

    for label, val in meta_rows:
        pdf.set_font(font_b, "B", 10)
        pdf.cell(42, 7, f"{label}:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font(font_r, "", 10)
        _cell(0, 7, val)

    pdf.ln(6)
    pdf.set_font(font_r, "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 5, L["scope"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 2+ — AUDIT RESULTS TABLE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    pdf.set_font(font_b, "B", 13)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["summary"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)

    # Build row data
    def _status_label(status: str) -> str:
        if status == "COMPLIANT":
            return L["compliant"]
        if status == "NON_COMPLIANT":
            return L["non_compliant"]
        return L["not_required"]

    headers = [L["model"], L["status"], L["risk"], L["issues"]]
    rows_data = []
    for r in results:
        issue_txt = "; ".join(r.missing_fields) if r.missing_fields else (
            r.issues[0] if r.issues else "-"
        )
        if any(f in {"HIGH_RISK", "DATA_UNREALISTIC"} for f in (r.fraud_flags or [])):
            flags_str = ", ".join(r.fraud_flags)
            issue_txt = f"{issue_txt} [{L['manual']}: {flags_str}]"
        rows_data.append([
            str(r.model)[:60],
            _status_label(r.status),
            str(r.risk_level),
            issue_txt,
        ])

    # Column widths
    page_w = 210 - 18 - 18   # usable width mm
    min_issue = 68
    w0, w1, w2 = 34, 30, 20
    # Widen model/status columns based on content
    for i, (base_w, col_idx) in enumerate([(w0, 0), (w1, 1), (w2, 2)]):
        max_len = len(headers[col_idx])
        for row in rows_data[:20]:
            max_len = max(max_len, len(str(row[col_idx])))
        widths_computed = min(base_w + 10, 4 + max_len * 1.8)
        if i == 0:
            w0 = max(base_w, widths_computed)
        elif i == 1:
            w1 = max(base_w, widths_computed)
        else:
            w2 = max(base_w, widths_computed)
    base_sum = w0 + w1 + w2
    if base_sum > page_w - min_issue:
        scale = (page_w - min_issue) / base_sum
        w0 = max(24, w0 * scale)
        w1 = max(22, w1 * scale)
        w2 = max(16, w2 * scale)
    w3 = max(min_issue, page_w - w0 - w1 - w2)
    col_widths = [w0, w1, w2, w3]

    def _draw_header() -> None:
        pdf.set_font(font_b, "B", 9)
        pdf.set_fill_color(11, 61, 145)
        pdf.set_text_color(255, 255, 255)
        for h, cw in zip(headers, col_widths):
            pdf.cell(cw, 8, h[:40], border=1, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(8)
        pdf.set_text_color(0, 0, 0)

    _draw_header()

    for ri, row in enumerate(rows_data):
        issue_text = str(row[3]).replace("_", "_ ").replace("/", "/ ")
        # Estimate height
        chars_per_line = max(1, int(w3 / 2.1))
        n_lines = max(1, len(issue_text) // chars_per_line + 1)
        row_h = max(7, min(28, n_lines * 4))

        if pdf.get_y() + row_h > 283:
            pdf.add_page()
            _watermark()
            _draw_header()

        fill = ri % 2 == 0
        fill_color = (243, 244, 246) if fill else (255, 255, 255)
        pdf.set_fill_color(*fill_color)

        # Status text color
        st_val = results[ri].status
        if st_val == "COMPLIANT":
            pdf.set_text_color(27, 94, 32)
        elif st_val == "NON_COMPLIANT":
            pdf.set_text_color(176, 0, 32)
        else:
            pdf.set_text_color(80, 80, 80)

        x0, y0 = pdf.get_x(), pdf.get_y()

        pdf.set_font(font_r, "", 8)
        pdf.cell(w0, row_h, str(row[0])[:60], border=1, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(w1, row_h, str(row[1])[:40], border=1, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(w2, row_h, str(row[2])[:20], border=1, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        # Issue column: multi_cell (may wrap)
        pdf.set_xy(x0 + w0 + w1 + w2, y0)
        pdf.set_text_color(0, 0, 0)
        try:
            pdf.multi_cell(w3, 4, issue_text, border=1, fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pdf.multi_cell(w3, 4, issue_text[:200], border=1, fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_xy(x0, max(y0 + row_h, pdf.get_y()))

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE — RADAR + GAP LIST + RECOMMENDATIONS
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _watermark()

    # Six-dimension radar (text-bar form)
    pdf.set_font(font_b, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["radar"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)

    dim_keys = {
        "Safety":      ["extinguishing_agent", "thermal_runaway_prevention", "explosion_proof_declaration"],
        "Environmental":["carbon_footprint_total_kg_co2e", "carbon_physical_plausibility"],
        "Traceability": ["unique_identifier", "manufacturer_id", "mine_coordinates"],
        "Recycled":    ["recycled_lithium_pct", "recycled_cobalt_pct", "recycled_nickel_pct", "recycled_lead_pct"],
        "Performance": ["rated_capacity_ah", "nominal_voltage_v", "rated_power_w", "expected_lifetime_cycles"],
        "BMS Access":  ["bms_access_permissions"],
    }
    mandatory = [r for r in results if r.status in {"COMPLIANT", "NON_COMPLIANT"}]
    total_m = len(mandatory) or 1
    pdf.set_font(font_r, "", 10)
    for dim, keys in dim_keys.items():
        met = sum(
            1 for r in mandatory
            if all(((r.metrics.get(k, {}) or {}).get("met") is True) for k in keys)
        )
        score = met / total_m
        bar_filled = int(round(score * 20))
        bar = "#" * bar_filled + "." * (20 - bar_filled)
        pct = f"{score:.0%}"
        pdf.set_x(pdf.l_margin)
        try:
            _cell(0, 6, f"  {dim:<16}  [{bar}]  {pct}  ({met}/{total_m})")
        except Exception:
            _cell(0, 6, f"  {dim}:  {pct}  ({met}/{total_m})")

    pdf.ln(5)

    # Gap Fixing List
    pdf.set_font(font_b, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["gap"])
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font(font_r, "", 10)

    dept_map = [
        ("recycled_",         "Procurement & Sustainability",
         "Collect recycled-material certificates and update recycled-content declarations."),
        ("carbon_footprint",  "LCA / ESG Team",
         "Recalculate lifecycle carbon footprint and provide audited methodology evidence."),
        ("bms_access",        "BMS Firmware & Diagnostics",
         "Publish read/write access policy and technical interface control note."),
        ("extinguishing_agent","EHS & Product Safety",
         "Provide extinguishing-agent specification and hazard response instructions."),
        ("manufacturer_id",   "Master Data Governance",
         "Fix manufacturer identity schema and traceability key integrity."),
        ("hazardous_substances","Compliance Documentation",
         "Complete hazardous-substance declaration linked to BOM/SDS records."),
        ("rated_capacity",    "R&D Validation",
         "Provide validated electrochemical performance measurements."),
    ]
    issue_pool = [m for r in results for m in (r.missing_fields or [])]
    used_actions: set = set()
    for issue in issue_pool:
        for token, dept, action in dept_map:
            if token in issue and action not in used_actions:
                used_actions.add(action)
                pdf.set_x(pdf.l_margin)
                try:
                    pdf.multi_cell(0, 5, f"  [{dept}] {action}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                except Exception:
                    pdf.multi_cell(0, 5, f"  {action}"[:200], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if not used_actions:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, f"  {L['no_gap']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(5)

    # Recommendations
    pdf.set_font(font_b, "B", 12)
    pdf.set_text_color(11, 61, 145)
    _cell(0, 8, L["rec_title"])
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_r, "", 10)
    pdf.ln(1)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, L["rec_body"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(6)
    pdf.set_font(font_r, "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, L["disclaimer"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(str(output_pdf))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="EU 2023/1542 Battery DPP checker (Art. 77 + Annex XIII).",
    )
    p.add_argument("--csv", type=str, help="Path to a CSV file to validate (recommended).")
    p.add_argument("--model", type=str, help="Battery model (for single-record mode).")
    p.add_argument("--data", type=str, help="JSON object with battery data (for single-record mode).")
    p.add_argument("--json", action="store_true", help="Output results as JSON lines.")
    p.add_argument(
        "--pdf",
        type=str,
        default="DPP_Audit_Report.pdf",
        help="When auditing a CSV, write a PDF report to this path (default: DPP_Audit_Report.pdf). Use '--pdf none' to disable.",
    )
    args = p.parse_args(argv)

    results: List[DppResult] = []
    csv_path: Optional[Path] = None

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"CSV not found: {csv_path}", file=sys.stderr)
            return 2
        for row in iter_csv(csv_path):
            results.append(validate_record(row))
    else:
        if not args.model or not args.data:
            print("Either provide --csv, or provide both --model and --data JSON.", file=sys.stderr)
            return 2
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"--data must be valid JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("--data must be a JSON object.", file=sys.stderr)
            return 2
        data = dict(data)
        data["model"] = args.model
        results.append(validate_record(data))

    if args.json:
        for r in results:
            print(
                json.dumps(
                    {
                        "model": r.model,
                        "status": r.status,
                        "risk_level": r.risk_level,
                        "missing_fields": r.missing_fields,
                        "issues": r.issues,
                        "metrics": r.metrics,
                        "fraud_flags": r.fraud_flags,
                    },
                    ensure_ascii=False,
                )
            )
    else:
        for i, r in enumerate(results):
            if i:
                print("\n" + "-" * 60 + "\n")
            print(r.to_text())

    # Auto-generate a PDF report after CSV audits (commercial product behavior).
    if csv_path is not None:
        pdf_arg = _norm(args.pdf).lower()
        if pdf_arg not in {"", "none", "off", "false", "0"}:
            out_pdf = Path(args.pdf)
            try:
                generate_audit_pdf(results=results, source_csv=csv_path, output_pdf=out_pdf)
                if not args.json:
                    print("\n" + "=" * 60)
                    print(f"PDF report written: {out_pdf.resolve()}")
            except ModuleNotFoundError as e:
                print(str(e), file=sys.stderr)
                return 3
            except Exception as e:
                print(f"Failed to write PDF report: {e}", file=sys.stderr)
                return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

