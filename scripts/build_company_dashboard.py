from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPANY_DIR = ROOT / "data" / "foundation" / "companies"
WATCHLIST = ROOT / "config" / "watchlist.json"
OUT = ROOT / "data" / "company_dashboard.json"
NOW = datetime.now(timezone.utc).isoformat()


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def finite(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def period_key(label: str) -> tuple[int, int, str]:
    text = str(label)
    years = re.findall(r"20\d{2}", text)
    year = int(years[-1]) if years else 0
    q = 0
    qmatch = re.search(r"(?:q|quý\s*)([1-4])", text, flags=re.I)
    if qmatch:
        q = int(qmatch.group(1))
    else:
        m = re.search(r"(?:^|[-_/])([1-4])(?:[-_/]|$)", text)
        if m and len(text) > 4:
            q = int(m.group(1))
    return year, q, text


def report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    cols = [str(c) for c in report.get("columns", [])]
    rows = report.get("rows", []) or []
    if not cols or not rows:
        return []
    return [{cols[i]: row[i] if i < len(row) else None for i in range(len(cols))} for row in rows]


def row_identity(row: dict[str, Any]) -> tuple[str, str]:
    item = row.get("item") or row.get("item_vi") or row.get("name") or row.get("index") or ""
    item_id = row.get("item_id") or row.get("id") or row.get("code") or ""
    return norm(item_id), norm(item)


def choose_row(rows: list[dict[str, Any]], ids: list[str] = [], contains: list[str] = [], prefer: list[str] = []) -> dict[str, Any] | None:
    idset = {norm(x) for x in ids}
    candidates: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        item_id, item = row_identity(row)
        text = f"{item_id} {item}"
        score = 0
        if item_id in idset:
            score += 100
        if any(norm(x) in text for x in contains):
            score += 35
        score += sum(12 for x in prefer if norm(x) in text)
        if score:
            candidates.append((score, row))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def period_columns(row: dict[str, Any]) -> list[str]:
    ignored = {"item", "item_vi", "item_en", "item_id", "id", "code", "unit", "ticker", "symbol", "index", "name"}
    return [k for k in row if norm(k) not in ignored and re.search(r"20\d{2}", str(k))]


def row_series(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not row:
        return []
    pts = [{"period": c, "value": finite(row.get(c))} for c in period_columns(row)]
    pts = [x for x in pts if x["value"] is not None]
    pts.sort(key=lambda x: period_key(str(x["period"])))
    return pts


def align(*series: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, float | None]]]:
    periods = sorted({str(p["period"]) for s in series for p in s}, key=period_key)
    maps = [{str(p["period"]): finite(p["value"]) for p in s} for s in series]
    return periods, maps


def binary_series(a: list[dict[str, Any]], b: list[dict[str, Any]], fn) -> list[dict[str, Any]]:
    periods, maps = align(a, b)
    out = []
    for p in periods:
        av, bv = maps[0].get(p), maps[1].get(p)
        if av is None or bv is None:
            continue
        try:
            value = fn(av, bv)
        except Exception:
            value = None
        if value is not None and math.isfinite(float(value)):
            out.append({"period": p, "value": float(value)})
    return out


def sum_series(*parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    periods, maps = align(*parts)
    out = []
    for p in periods:
        vals = [m.get(p) for m in maps]
        if not vals or any(v is None for v in vals):
            continue
        out.append({"period": p, "value": float(sum(vals))})
    return out


def build_frequency(reports: dict[str, Any]) -> dict[str, Any]:
    income = report_rows(reports.get("income_statement", {}).get("data", {}))
    cashflow = report_rows(reports.get("cash_flow", {}).get("data", {}))
    balance = report_rows(reports.get("balance_sheet", {}).get("data", {}))
    ratios = report_rows(reports.get("ratio", {}).get("data", {}))

    revenue = row_series(choose_row(income, ids=["net_revenue", "revenue"], contains=["doanh thu thuần"], prefer=["thuần"]))
    if not revenue:
        revenue = row_series(choose_row(income, ids=["revenue"], contains=["doanh thu bán hàng"]))
    cogs = row_series(choose_row(income, ids=["cost_of_goods_sold"], contains=["giá vốn hàng bán", "cost of goods sold"]))
    gross_profit = row_series(choose_row(income, ids=["gross_profit"], contains=["lợi nhuận gộp", "gross profit"]))
    selling_expenses = row_series(choose_row(income, ids=["selling_expenses"], contains=["chi phí bán hàng", "selling expenses"]))
    admin_expenses = row_series(choose_row(income, ids=["admin_expenses", "general_and_administration_expenses"], contains=["chi phí quản lý doanh nghiệp", "administrative expenses"]))
    financial_income = row_series(choose_row(income, ids=["financial_income"], contains=["doanh thu hoạt động tài chính", "financial income"]))
    finance_expenses = row_series(choose_row(income, ids=["finance_expenses"], contains=["chi phí tài chính", "finance expenses"]))
    operating_profit = row_series(choose_row(income, ids=["operating_profit"], contains=["lợi nhuận thuần từ hoạt động kinh doanh", "operating profit"]))
    net_profit = row_series(choose_row(income, ids=["profit_after_tax_for_shareholders_of_parent_company", "net_profit"], contains=["lợi nhuận sau thuế", "net profit"], prefer=["công ty mẹ", "parent"]))
    interest_expense = row_series(choose_row(income, ids=["of_which_interest_expense", "interest_expense"], contains=["chi phí đi vay", "interest expense"]))

    cfo = row_series(choose_row(cashflow, ids=["net_cash_flows_from_operating_activities", "net_cash_flow_from_operating_activities"], contains=["lưu chuyển tiền thuần từ hoạt động kinh doanh", "net cash flow from operating"]))
    capex = row_series(choose_row(cashflow, ids=["purchase_of_fixed_assets", "purchase_of_fixed_assets_and_other_long_term_assets"], contains=["mua sắm, xây dựng tài sản cố định", "purchase of fixed assets"]))

    total_assets = row_series(choose_row(balance, ids=["total_assets", "total_asset"], contains=["tổng cộng tài sản", "tổng tài sản", "total assets"]))
    current_assets = row_series(choose_row(balance, ids=["current_assets", "total_current_assets"], contains=["tài sản ngắn hạn", "current assets"]))
    current_liabilities = row_series(choose_row(balance, ids=["current_liabilities", "total_current_liabilities"], contains=["nợ ngắn hạn", "current liabilities"]))
    cash = row_series(choose_row(balance, ids=["cash_and_cash_equivalents", "cash"], contains=["tiền và các khoản tương đương tiền", "cash and cash equivalents"]))
    receivables = row_series(choose_row(balance, ids=["short_term_receivables", "receivables"], contains=["các khoản phải thu ngắn hạn", "short-term receivables"]))
    inventory = row_series(choose_row(balance, ids=["inventories", "inventory"], contains=["hàng tồn kho", "inventories"]))
    ppe = row_series(choose_row(balance, ids=["fixed_assets", "tangible_fixed_assets", "property_plant_equipment"], contains=["tài sản cố định", "fixed assets"]))
    cip = row_series(choose_row(balance, ids=["construction_in_progress", "construction_in_progress_cost"], contains=["xây dựng cơ bản dở dang", "construction in progress"]))
    payables = row_series(choose_row(balance, ids=["trade_payables", "short_term_trade_payables"], contains=["phải trả người bán", "trade payables"]))
    short_debt = row_series(choose_row(balance, ids=["short_term_borrowings", "short_term_debt", "short_term_borrowings_and_finance_lease_liabilities"], contains=["vay và nợ thuê tài chính ngắn hạn", "short-term borrowings"]))
    long_debt = row_series(choose_row(balance, ids=["long_term_borrowings", "long_term_debt", "long_term_borrowings_and_finance_lease_liabilities"], contains=["vay và nợ thuê tài chính dài hạn", "long-term borrowings"]))
    equity = row_series(choose_row(balance, ids=["owners_equity", "total_equity", "equity"], contains=["vốn chủ sở hữu", "owners' equity", "total equity"]))

    nwc = binary_series(current_assets, current_liabilities, lambda a, b: a - b)
    operating_nwc = []
    if receivables and inventory and payables:
        operating_nwc = sum_series(receivables, inventory, [{"period": x["period"], "value": -x["value"]} for x in payables])
    total_debt = sum_series(short_debt, long_debt) if short_debt and long_debt else (short_debt or long_debt)
    gross_margin = binary_series(gross_profit, revenue, lambda a, b: a / b if b else None)
    net_margin = binary_series(net_profit, revenue, lambda a, b: a / b if b else None)
    cfo_to_profit = binary_series(cfo, net_profit, lambda a, b: a / b if b else None)
    fcf = sum_series(cfo, capex) if cfo and capex else []

    asset_other: list[dict[str, Any]] = []
    if total_assets:
        periods, maps = align(total_assets, cash, receivables, inventory, ppe, cip)
        for p in periods:
            total = maps[0].get(p)
            if total is None:
                continue
            known = sum((m.get(p) or 0) for m in maps[1:])
            asset_other.append({"period": p, "value": max(float(total - known), 0.0)})

    return {
        "series": {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "selling_expenses": selling_expenses,
            "admin_expenses": admin_expenses,
            "financial_income": financial_income,
            "finance_expenses": finance_expenses,
            "operating_profit": operating_profit,
            "net_profit": net_profit,
            "interest_expense": interest_expense,
            "cfo": cfo,
            "capex": capex,
            "fcf": fcf,
            "total_assets": total_assets,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "cash": cash,
            "receivables": receivables,
            "inventory": inventory,
            "ppe": ppe,
            "cip": cip,
            "payables": payables,
            "short_debt": short_debt,
            "long_debt": long_debt,
            "total_debt": total_debt,
            "equity": equity,
            "nwc": nwc,
            "operating_nwc": operating_nwc,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "cfo_to_profit": cfo_to_profit,
        },
        "asset_mix": {
            "cash": cash,
            "receivables": receivables,
            "inventory": inventory,
            "ppe": ppe,
            "cip": cip,
            "other": asset_other,
        },
        "report_availability": {
            "balance_sheet": bool(balance),
            "income_statement": bool(income),
            "cash_flow": bool(cashflow),
            "ratio": bool(ratios),
        },
    }


def main() -> None:
    watch = load(WATCHLIST, {})
    sector_map = {str(x.get("symbol", "")).upper(): str(x.get("sector", "")) for x in watch.get("symbols", [])}
    symbols = [str(x).upper() for x in watch.get("fundamental_symbols", [])]
    companies: dict[str, Any] = {}

    for symbol in symbols:
        raw = load(COMPANY_DIR / f"{symbol}.json", {})
        if not raw:
            continue
        reports = raw.get("reports", {})
        sector = sector_map.get(symbol, "")
        companies[symbol] = {
            "symbol": symbol,
            "sector": sector,
            "analysis_model": "banking" if sector == "Banking" else "generic",
            "source": raw.get("source"),
            "provider": raw.get("provider"),
            "coverage": raw.get("coverage", {}),
            "warnings": raw.get("warnings", []),
            "annual": build_frequency(reports.get("annual", {})),
            "quarterly": build_frequency(reports.get("quarterly", {})),
        }

    payload = {
        "schema_version": "1.0.0",
        "generated_at": NOW,
        "policy": "All chart values are generated from normalized financial statements. Missing facts remain missing; no synthetic values are inserted.",
        "companies": companies,
    }
    save(OUT, payload)
    print(json.dumps({"companies": len(companies), "output": str(OUT.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
