"""config.py — Global constants, field mappings, and UI CSS for DPP Expert 3.0.

All business constants are derived from Regulation (EU) 2023/1542.
No business logic lives here — pure data/configuration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── Font ──────────────────────────────────────────────────────────────────────
# Single authoritative font constant used by pdf_generator.py.
FONT_FILE = "NotoSansSC-Regular.otf"
FONT_URLS: List[str] = [
    "https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf",
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf",
    "https://github.com/googlefonts/noto-cjk/raw/be6c059ac1587e556e2412b27f5155c8eb3ddbe6/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf",
]

# ── Regulatory constants ───────────────────────────────────────────────────────
ALLOWED_CATEGORIES = {"LMT", "INDUSTRIAL", "EV"}

# Minimum recycled-content shares — Article 8(2)(a)-(d), target year 2027.
RECYCLED_MIN_PCT: Dict[str, float] = {
    "Lithium": 6.0,
    "Cobalt": 16.0,
    "Nickel": 6.0,
    "Lead": 85.0,
}
RECYCLED_LEGAL_REF = "Article 8(2)(a)-(d)"

# Approximate lower bounds for anti-fraud plausibility checks (kg CO₂e/kWh).
# Not legal thresholds — heuristic only.
CARBON_FOOTPRINT_MIN_BY_CHEMISTRY: Dict[str, float] = {
    "LFP": 30.0,
    "NMC": 40.0,
}

# Simplified bounding boxes for sourcing-risk coordinate checks.
# (lat_min, lat_max, lon_min, lon_max)
KNOWN_LITHIUM_COBALT_MINING_ZONES: List[Tuple[float, float, float, float]] = [
    (-30.0, -15.0, -72.0, -65.0),   # Chile/Argentina lithium triangle
    (-25.0, -18.0, 16.0, 30.0),     # Southern Africa lithium belt
    (-15.0,   5.0, 12.0, 33.0),     # DRC cobalt region
    (-33.0, -20.0, 114.0, 122.0),   # Western Australia lithium region
]

# ── Annex XIII field map ───────────────────────────────────────────────────────
# Single source of truth for expected CSV fields, aliases, and legal references.
DPP_FIELD_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    "public_information": {
        "unique_identifier":  {"aliases": ["unique_identifier", "battery_passport_id", "uid", "唯一标识"],         "legal_ref": "Article 77(3)"},
        "battery_id":         {"aliases": ["battery_id", "battery_identifier", "serial", "battery_model_id", "电池识别码"], "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
        "manufacturer_id":    {"aliases": ["manufacturer_id", "mfg_id", "制造商ID"],                               "legal_ref": "Heuristic anti-fraud identity check"},
        "manufacturer":       {"aliases": ["manufacturer", "manufacturer_name", "制造商"],                         "legal_ref": "Annex VI Part A(1) via Annex XIII(1)(a)"},
        "manufacture_place":  {"aliases": ["manufacture_place", "place_of_manufacture", "生产地"],                 "legal_ref": "Annex VI Part A(3) via Annex XIII(1)(a)"},
        "manufacture_date":   {"aliases": ["manufacture_date", "date_of_manufacture", "生产日期"],                 "legal_ref": "Annex VI Part A(4) via Annex XIII(1)(a)"},
        "category":           {"aliases": ["category", "battery_category", "类别"],                               "legal_ref": "Annex VI Part A(2) via Annex XIII(1)(a)"},
    },
    "materials_and_compliance": {
        "recycled_lithium_pct":            {"aliases": ["recycled_lithium_pct", "lithium_pct"],         "legal_ref": "Article 8(2)(c)", "min": 6.0},
        "recycled_cobalt_pct":             {"aliases": ["recycled_cobalt_pct", "cobalt_pct"],           "legal_ref": "Article 8(2)(a)", "min": 16.0},
        "recycled_nickel_pct":             {"aliases": ["recycled_nickel_pct", "nickel_pct"],           "legal_ref": "Article 8(2)(d)", "min": 6.0},
        "recycled_lead_pct":               {"aliases": ["recycled_lead_pct", "lead_pct"],               "legal_ref": "Article 8(2)(b)", "min": 85.0},
        "hazardous_substances_declaration":{"aliases": ["hazardous_substances_declaration", "hazardous_substances", "hazardous", "危险物质声明"], "legal_ref": "Annex XIII(1)(b)"},
    },
    "performance_and_durability": {
        "rated_capacity_ah":                   {"aliases": ["rated_capacity_ah", "rated_capacity", "额定容量"],                                                      "legal_ref": "Annex XIII(1)(a)(g)"},
        "nominal_voltage_v":                   {"aliases": ["nominal_voltage_v", "nominal_voltage", "标称电压"],                                                      "legal_ref": "Annex XIII(1)(a)(h)"},
        "rated_power_w":                       {"aliases": ["rated_power_w", "power_w", "额定功率"],                                                                  "legal_ref": "Annex XIII(1)(a)(i)"},
        "self_discharge_rate_pct_per_month":   {"aliases": ["self_discharge_rate_pct_per_month", "self_discharge_rate", "自放电率"],                                  "legal_ref": "Annex VII Part B(4)"},
        "expected_lifetime_cycles":            {"aliases": ["expected_lifetime_cycles", "cycles", "预期寿命_cycles"],                                                 "legal_ref": "Annex XIII(1)(a)(j)"},
        "charge_discharge_efficiency_percent": {"aliases": ["charge_discharge_efficiency_percent", "efficiency_percent", "充放电效率_percent", "充放电效率"],           "legal_ref": "Annex XIII(1)(a)(n)"},
    },
    "safety": {
        "thermal_runaway_prevention": {"aliases": ["thermal_runaway_prevention", "thermal_runaway_control", "热失控预防"],    "legal_ref": "Heuristic safety check"},
        "extinguishing_agent":        {"aliases": ["extinguishing_agent", "Extinguishing Agent", "灭火剂类型"],               "legal_ref": "Annex VI Part A(9) via Annex XIII(1)(a)"},
        "explosion_proof_declaration":{"aliases": ["explosion_proof_declaration", "explosion_proof", "防爆声明"],             "legal_ref": "Heuristic safety check"},
        "bms_access_permissions":     {"aliases": ["bms_access_permissions", "bms_access", "bms_rw_permissions", "BMS访问权限"], "legal_ref": "Article 14"},
    },
    "traceability_and_sourcing": {
        "mine_latitude":                  {"aliases": ["mine_latitude", "source_mine_lat", "矿山纬度"],                                                                          "legal_ref": "Heuristic sourcing-risk check"},
        "mine_longitude":                 {"aliases": ["mine_longitude", "source_mine_lon", "矿山经度"],                                                                         "legal_ref": "Heuristic sourcing-risk check"},
        "chemistry":                      {"aliases": ["chemistry", "电化学体系"],                                                                                               "legal_ref": "Annex XIII(1)(b)"},
        "carbon_footprint_total_kg_co2e": {"aliases": ["carbon_footprint_total_kg_co2e", "carbon_footprint_total", "carbon_footprint_kg_co2e_total", "生命周期碳排放总量", "碳足迹_总量_kgco2e"], "legal_ref": "Annex XIII(1)(c) / Article 7"},
    },
}

# Legal citation snippets shown in the Streamlit results expanders.
LEGAL_CITATIONS: Dict[str, str] = {
    "recycled_lithium":    "Article 8(2)(c): batteries shall contain ≥ 6% lithium recovered from battery waste.",
    "recycled_cobalt":     "Article 8(2)(a): batteries shall contain ≥ 16% cobalt recovered from battery waste.",
    "recycled_nickel":     "Article 8(2)(d): batteries shall contain ≥ 6% nickel recovered from battery waste.",
    "recycled_lead":       "Article 8(2)(b): batteries shall contain ≥ 85% lead recovered from battery waste.",
    "carbon_footprint":    "Annex XIII(1)(c) + Article 7: carbon footprint information must be declared and physically plausible.",
    "bms_access":          "Article 14: BMS read/write access disclosure required for state-of-health assessment.",
    "unique_identifier":   "Article 77(3): battery passport accessible via QR-linked unique identifier.",
    "manufacturer_id":     "Article 77(4): information in passport shall be accurate, complete and up to date.",
    "extinguishing_agent": "Annex VI Part A(9) via Annex XIII(1)(a): label must include usable extinguishing agent.",
    "hazardous_substances":"Annex XIII(1)(b): battery passport includes hazardous substances declaration.",
    "mine_coordinates":    "OECD Due Diligence Guidance: mine coordinates outside known mining zones flagged as high-risk.",
}

# ── Streamlit CSS theme ────────────────────────────────────────────────────────
APP_CSS = """
<style>
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0A192F 0%, #112240 60%, #0D2137 100%);
    color: #CCD6F6;
}
[data-testid="stSidebar"] {
    background: #0D1B2A !important;
    border-right: 1px solid #1E3A5F;
}
[data-testid="stSidebar"] * { color: #8892B0 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label,
[data-testid="stSidebar"] .stFileUploader label {
    color: #64FFDA !important;
    font-weight: 600;
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
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
.kpi-delta { color: #8892B0; font-size: 0.77rem; margin-top: 0.3rem; }
.section-header {
    color: #CCD6F6;
    font-size: 1.18rem;
    font-weight: 700;
    border-left: 3px solid #64FFDA;
    padding-left: 0.65rem;
    margin: 1.2rem 0 0.7rem 0;
}
.welcome-banner {
    background: linear-gradient(90deg, #112240, #0D2137);
    border-radius: 14px;
    border: 1px solid #1E3A5F;
    padding: 1.6rem 2rem;
    margin-bottom: 1.4rem;
    text-align: center;
}
.welcome-banner h1 { color: #64FFDA; font-size: 1.75rem; font-weight: 800; margin: 0 0 0.4rem 0; }
.welcome-banner p  { color: #8892B0; font-size: 0.88rem; margin: 0; letter-spacing: 0.04em; }
[data-testid="stExpander"] {
    background: #112240;
    border-radius: 10px;
    border: 1px solid #1E3A5F;
    margin-bottom: 0.5rem;
}
[data-testid="stExpander"] summary { color: #CCD6F6 !important; font-weight: 600; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
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
.stDownloadButton > button {
    background: linear-gradient(90deg, #064420, #1B5E20);
    color: #A5D6A7;
    border-radius: 10px;
    border: 1px solid #4CAF5044;
    font-weight: 700;
}
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
.disclaimer-box {
    background: #1A0A0A;
    border: 1px solid #7F1D1D;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    color: #FCA5A5;
    font-size: 0.87rem;
    line-height: 1.65;
}
.stMarkdown p { color: #CCD6F6; }
</style>
"""
