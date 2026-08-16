from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "data" / "foundation"
OUT = ROOT / "data" / "rootvalue.json"
WATCHLIST = ROOT / "config" / "watchlist.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main() -> None:
    previous = load(OUT, {})
    manifest = load(FOUNDATION / "manifest.json", {})
    macro = load(FOUNDATION / "macro.json", {})
    watch = load(WATCHLIST, {})

    company_rows: dict[str, Any] = {}
    for symbol in [str(x).upper() for x in watch.get("fundamental_symbols", [])]:
        item = load(FOUNDATION / "companies" / f"{symbol}.json", {})
        if not item:
            continue
        annual = item.get("reports", {}).get("annual", {})
        company_rows[symbol] = {
            "symbol": symbol,
            "status": item.get("status"),
            "coverage": item.get("coverage", {}),
            "provider": item.get("provider"),
            "source": item.get("source"),
            "warnings": item.get("warnings", []),
            "reports": {
                "balance_sheet": annual.get("balance_sheet", {}).get("data", {"columns": [], "rows": []}),
                "income_statement": annual.get("income_statement", {}).get("data", {"columns": [], "rows": []}),
                "cash_flow": annual.get("cash_flow", {}).get("data", {"columns": [], "rows": []}),
                "ratio": annual.get("ratio", {}).get("data", {"columns": [], "rows": []}),
            },
        }

    missing_core = macro.get("coverage", {}).get("missing", [])
    warnings: list[str] = []
    errors: list[str] = []
    if not manifest.get("access", {}).get("vnstock_api_key_present"):
        warnings.append("VNSTOCK_API_KEY is not configured; community guest mode may expose fewer than 8 annual periods.")
    if not macro.get("coverage", {}).get("state_ready"):
        warnings.append("SBV historical state layer is not ready: " + ", ".join(missing_core))
    for row in manifest.get("companies", []):
        if not row.get("minimum_met"):
            warnings.append(f"{row.get('symbol')}: annual history {row.get('annual_periods', 0)}/8")
        if row.get("status") == "error":
            errors.append(f"{row.get('symbol')}: financial history fetch failed")

    old_market = previous.get("market", {})
    if not old_market:
        old_market = {"status": "not_run", "as_of": None, "source": None, "index": {}, "rows": [], "methodology": {}}

    ready = bool(manifest.get("foundation_ready"))
    snapshot = {
        "schema_version": "1.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "ok" if ready and not errors else "partial",
        "meta": {
            "principle": "Missing data stays missing. Rootvalue never fabricates financial or macro values.",
            "foundation_ready": ready,
            "history_target": manifest.get("history_target", {}),
        },
        "foundation": manifest,
        "macro": {
            "status": "ok" if macro.get("coverage", {}).get("state_ready") else "partial",
            "as_of": macro.get("generated_at"),
            "source": ["State Bank of Vietnam official website", macro.get("historical_provider") or "historical provider unavailable"],
            "metrics": [],
            "datasets": macro.get("datasets", {}),
            "official_checks": macro.get("official_checks", {}),
            "missing_core": missing_core,
            "reaction_engine_status": "data_ready" if macro.get("coverage", {}).get("state_ready") else "framework_only",
        },
        "market": old_market,
        "companies": {
            "status": "ok" if company_rows and all(v.get("coverage", {}).get("minimum_met") for v in company_rows.values()) else "partial",
            "as_of": manifest.get("generated_at"),
            "source": manifest.get("access", {}).get("fundamental_source"),
            "limitations": "Rootvalue requires at least 8 annual periods for a company to pass foundation QC.",
            "rows": company_rows,
        },
        "health": {"errors": errors, "warnings": warnings},
    }
    save(OUT, snapshot)
    print(f"published foundation -> data/rootvalue.json; ready={ready}; companies={len(company_rows)}")


if __name__ == "__main__":
    main()
