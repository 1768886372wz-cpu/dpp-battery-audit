# DPP Battery Audit Platform

## Project Background

This project is a battery Digital Product Passport (DPP) pre-audit platform for manufacturers targeting EU market entry.  
It provides:

- rule-based compliance pre-audit for battery model data
- fraud-risk detection (high-risk sourcing / unrealistic data checks)
- Streamlit web dashboard with bilingual UI
- auto-generated PDF pre-audit report

## EU Regulation Scope

This implementation is aligned to **Regulation (EU) 2023/1542** and uses requirement references mainly from:

- **Article 7** (carbon footprint information)
- **Article 8** (recycled content thresholds)
- **Article 14** (state-of-health / information access context)
- **Article 77** (battery passport scope and obligations)
- **Annex XIII** (battery passport information categories)

> Note: some anti-fraud checks (e.g., coordinate plausibility, physical floor heuristics) are intentionally marked as heuristic controls, not direct statutory minimum clauses.

## Quick Start

### 1) Create/activate venv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Run CLI audit

```bash
python3 dpp_engine.py --csv test_data.csv
```

This generates:

- console diagnosis (COMPLIANT / NON_COMPLIANT / NOT_REQUIRED_DPP)
- `DPP_Audit_Report.pdf`

### 4) Run web app

```bash
streamlit run app.py --server.port 8505 --server.address localhost
```

Open:

- `http://localhost:8505`

## Main Files

- `dpp_engine.py` - compliance engine + PDF report generation
- `app.py` - Streamlit UI
- `test_data.csv` - sample data set
- `requirements.txt` - python dependencies

## Deploy/Update Flow

1. Commit changes to your branch/repo
2. Push to GitHub
3. Your CI/CD or app platform picks up the latest commit and redeploys

If deployment is GitHub-connected, push to the configured branch (typically `main`) to trigger update.
