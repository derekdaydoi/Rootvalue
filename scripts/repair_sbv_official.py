from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "foundation.json"
MACRO = ROOT / "data" / "foundation" / "macro.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def jsonable(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            pass
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def payload(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [str(c) for c in df.columns],
        "rows": [[jsonable(v) for v in row] for row in df.itertuples(index=False, name=None)],
        "row_count": int(len(df)),
    }


def fetch_tables(url: str, label: str) -> dict[str, Any]:
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Rootvalue/1.0 personal-research"})
        r.raise_for_status()
        # SBV tables use Vietnamese formatting: 20.414.616 and 4,99.
        # Explicit locale parsing avoids dangerous conversions such as 4,99 -> 499.
        tables = pd.read_html(StringIO(r.text), decimal=",", thousands=".")
        usable = [t for t in tables if isinstance(t, pd.DataFrame) and not t.empty]
        return {
            "status": "ok" if usable else "empty",
            "label": label,
            "url": url,
            "source": "State Bank of Vietnam official website",
            "provenance": "primary_official",
            "numeric_locale": "vi-VN: decimal comma, thousands dot",
            "as_of": None,
            "tables": [payload(t) for t in usable[:5]],
        }
    except Exception as exc:
        return {
            "status": "error",
            "label": label,
            "url": url,
            "source": "State Bank of Vietnam official website",
            "provenance": "primary_official",
            "numeric_locale": "vi-VN: decimal comma, thousands dot",
            "as_of": None,
            "tables": [],
            "error": str(exc),
        }


def validate_official(official: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    omo = official.get("omo_latest", {})
    for table in omo.get("tables", []):
        cols = table.get("columns", [])
        rate_idx = next((i for i, c in enumerate(cols) if "Lãi suất" in str(c)), None)
        if rate_idx is None:
            continue
        for row in table.get("rows", []):
            if rate_idx >= len(row):
                continue
            value = row[rate_idx]
            if isinstance(value, (int, float)) and value > 20:
                warnings.append(f"OMO rate fails sanity check: {value}")
    ms = official.get("money_supply_deposits", {})
    for table in ms.get("tables", []):
        cols = table.get("columns", [])
        growth_idx = next((i for i, c in enumerate(cols) if "Tốc" in str(c) and "%" in str(c)), None)
        if growth_idx is None:
            continue
        for row in table.get("rows", []):
            if growth_idx >= len(row):
                continue
            value = row[growth_idx]
            if isinstance(value, (int, float)) and abs(value) > 100:
                warnings.append(f"Money/deposit growth fails sanity check: {value}")
    return warnings


def main() -> None:
    cfg = load(CONFIG, {})
    macro = load(MACRO, {})
    urls = cfg.get("official_sbv_sources", {})
    official = {
        "money_supply_deposits": fetch_tables(urls.get("money_supply_deposits", ""), "Tổng phương tiện thanh toán và tiền gửi"),
        "omo_latest": fetch_tables(urls.get("omo", ""), "Nghiệp vụ thị trường mở"),
    }
    warnings = validate_official(official)
    macro["official_checks"] = official
    macro["official_validation"] = {
        "status": "pass" if not warnings else "warning",
        "warnings": warnings,
        "policy": "Official SBV tables are not promoted into historical state series until dates/schema are validated."
    }
    MACRO.write_text(json.dumps(macro, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(macro["official_validation"], ensure_ascii=False))


if __name__ == "__main__":
    main()
