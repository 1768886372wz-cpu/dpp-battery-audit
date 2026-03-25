#!/usr/bin/env python3
"""
run_tests.py — 自动化测试运行器
================================
覆盖 data/samples/test_cases.json 中的 15 个极端测试用例，
验证核查引擎的所有逻辑维度。

用法：
    python run_tests.py                  # 运行全部测试
    python run_tests.py --id TC02        # 只运行指定 ID
    python run_tests.py --verbose        # 显示详细结果
    python run_tests.py --pdf            # 同时生成 PDF 报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保在项目根目录运行
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.auditor import audit_battery_data
from app.engine.calculator import run_physics_checks
from app.engine.forensics import run_forensics

# ── 颜色输出 ────────────────────────────────────────────────────────────────
RED    = "\033[1;31m"
GREEN  = "\033[1;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[1;36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def load_cases() -> list[dict]:
    path = ROOT / "data" / "samples" / "test_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def run_case(case: dict, verbose: bool = False, generate_pdf: bool = False) -> dict:
    """运行单个测试用例，返回测试结果。"""
    tc_id   = case["id"]
    name    = case["name"]
    data    = case.get("input", {})

    # ── 基础审计 ──────────────────────────────────────────────────────────
    audit_result = audit_battery_data(data)
    actual_risk  = audit_result["risk_level"]
    expected     = case.get("expected_risk_level", "any")

    risk_pass = (expected == "any" or actual_risk == expected)

    # ── 物理一致性核查 ──────────────────────────────────────────────────
    physics_results = run_physics_checks(data)
    physics_flags   = [f for f in physics_results if f["level"] == "RED_FLAG"]

    # ── 法医核查（如果有月度数据）───────────────────────────────────────
    forensic_result  = None
    forensic_risk    = None
    monthly_energy   = case.get("monthly_energy_data")
    monthly_recycled = case.get("monthly_recycled_data")
    expected_forensic = case.get("expected_forensic_risk")

    if monthly_energy or monthly_recycled:
        forensic_result = run_forensics(
            monthly_energy_data  = monthly_energy,
            monthly_recycled_data= monthly_recycled,
            input_data           = data,
        )
        forensic_risk = forensic_result["overall_forensic_risk"]

    forensic_pass = True
    if expected_forensic and forensic_risk:
        forensic_pass = (forensic_risk == expected_forensic)

    # ── PDF 生成（可选）─────────────────────────────────────────────────
    pdf_path = None
    if generate_pdf:
        try:
            from app.utils.pdf_gen import build_pdf
            pdf_bytes = build_pdf(audit_result, data)
            out_dir   = ROOT / "output" / "test_reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            pdf_path  = out_dir / f"{tc_id}.pdf"
            pdf_path.write_bytes(pdf_bytes)
        except Exception as e:
            pdf_path = f"ERROR: {e}"

    passed = risk_pass and forensic_pass

    return {
        "id":             tc_id,
        "name":           name,
        "passed":         passed,
        "risk_pass":      risk_pass,
        "forensic_pass":  forensic_pass,
        "expected_risk":  expected,
        "actual_risk":    actual_risk,
        "expected_forensic": expected_forensic,
        "actual_forensic":   forensic_risk,
        "physics_flags":  len(physics_flags),
        "total_findings": len(audit_result["findings"]),
        "pdf_path":       str(pdf_path) if pdf_path else None,
        "audit_result":   audit_result if verbose else None,
        "forensic_result": forensic_result if verbose else None,
        "physics_results": physics_results if verbose else None,
    }


def print_result(r: dict, verbose: bool = False) -> None:
    status = f"{GREEN}✅ PASS{RESET}" if r["passed"] else f"{RED}❌ FAIL{RESET}"
    risk_color = RED if r["actual_risk"] == "RED_FLAG" else (
        YELLOW if r["actual_risk"] in ("COMPLIANCE_GAP", "WARNING") else GREEN
    )

    print(f"  {status}  {BOLD}{r['id']}{RESET}  {r['name']}")
    print(f"         risk: {risk_color}{r['actual_risk']}{RESET} (expected: {r['expected_risk']})")

    if r.get("actual_forensic"):
        f_color = RED if r["actual_forensic"] == "HIGH" else (YELLOW if r["actual_forensic"] == "MEDIUM" else GREEN)
        print(f"         forensic: {f_color}{r['actual_forensic']}{RESET} (expected: {r.get('expected_forensic', 'any')})")

    if r["physics_flags"]:
        print(f"         {RED}⚠ {r['physics_flags']} physics RED_FLAG(s){RESET}")

    if r["pdf_path"]:
        print(f"         📄 PDF: {r['pdf_path']}")

    if verbose and r.get("audit_result"):
        for f in r["audit_result"]["findings"]:
            lvl_color = RED if f["level"] == "RED_FLAG" else (YELLOW if f["level"] in ("COMPLIANCE_GAP","WARNING") else GREEN)
            print(f"           [{lvl_color}{f['level']}{RESET}] {f['field']}: {f['message'][:90]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DPP Expert 自动化测试运行器")
    parser.add_argument("--id",      help="只运行指定 ID（如 TC02）")
    parser.add_argument("--verbose", action="store_true", help="显示详细 Finding 列表")
    parser.add_argument("--pdf",     action="store_true", help="同时生成 PDF 报告")
    args = parser.parse_args()

    cases = load_cases()
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
        if not cases:
            print(f"{RED}未找到测试用例：{args.id}{RESET}")
            sys.exit(1)

    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  DPP Expert V4 — 自动化测试套件{RESET}")
    print(f"{BOLD}{CYAN}  测试用例数：{len(cases)}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

    results = []
    categories: dict[str, list] = {}

    for case in cases:
        cat = case.get("category", "OTHER")
        r   = run_case(case, verbose=args.verbose, generate_pdf=args.pdf)
        results.append(r)
        categories.setdefault(cat, []).append(r)
        print_result(r, verbose=args.verbose)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["passed"])
    total  = len(results)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  测试汇总{RESET}")
    print(f"{'='*60}")
    print(f"  总计：{total} 用例  |  通过：{GREEN}{passed}{RESET}  |  失败：{RED}{total-passed}{RESET}")

    print(f"\n  按类别统计：")
    for cat, cat_results in sorted(categories.items()):
        cat_pass = sum(1 for r in cat_results if r["passed"])
        color    = GREEN if cat_pass == len(cat_results) else RED
        print(f"    {cat:<30} {color}{cat_pass}/{len(cat_results)}{RESET}")

    print(f"\n{'='*60}\n")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
