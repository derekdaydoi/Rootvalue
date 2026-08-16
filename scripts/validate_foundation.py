from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "data" / "foundation"
MANIFEST = FOUNDATION / "manifest.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if not MANIFEST.exists():
        print("QC FAIL: data/foundation/manifest.json missing")
        return 2
    manifest = load(MANIFEST)
    failures: list[str] = []
    warnings: list[str] = []

    target = int(manifest.get("history_target", {}).get("annual_min_periods", 8) or 8)
    for row in manifest.get("companies", []):
        symbol = row.get("symbol", "?")
        periods = int(row.get("annual_periods", 0) or 0)
        if periods < target:
            failures.append(f"{symbol}: {periods}/{target} annual periods")

        path = FOUNDATION / "companies" / f"{symbol}.json"
        if not path.exists():
            failures.append(f"{symbol}: company file missing")
            continue
        item = load(path)
        if item.get("policy") != "No synthetic values. Missing periods remain missing.":
            warnings.append(f"{symbol}: unexpected missing-data policy")
        annual = item.get("reports", {}).get("annual", {})
        for report in ("balance_sheet", "income_statement", "cash_flow"):
            payload = annual.get(report, {})
            if payload.get("status") != "ok" or not payload.get("data", {}).get("rows"):
                failures.append(f"{symbol}: {report} annual unavailable")

    macro = load(FOUNDATION / "macro.json") if (FOUNDATION / "macro.json").exists() else {}
    required = macro.get("coverage", {}).get("required_for_state", [])
    missing = macro.get("coverage", {}).get("missing", required)
    if missing:
        failures.append("SBV state history missing: " + ", ".join(missing))
    if not macro.get("official_checks"):
        warnings.append("SBV official checks absent")

    print(json.dumps({
        "foundation_ready": not failures,
        "failures": failures,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
