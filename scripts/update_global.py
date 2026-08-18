from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "global.json"
NOW = datetime.now(timezone.utc)
HEADERS = {"User-Agent": "Rootvalue/1.0 personal-research (github.com/derekdaydoi/Rootvalue)"}

SERIES = {
    "fed_funds_effective": {"id": "DFF", "label": "Fed funds effective", "unit": "%", "frequency": "daily", "source": "Federal Reserve / FRED"},
    "fed_total_assets": {"id": "WALCL", "label": "Fed total assets", "unit": "USD mn", "frequency": "weekly", "source": "Federal Reserve H.4.1 / FRED"},
    "fed_overnight_rrp": {"id": "RRPONTSYD", "label": "Fed overnight reverse repo", "unit": "USD bn", "frequency": "daily", "source": "New York Fed / FRED"},
    "broad_dollar": {"id": "DTWEXBGS", "label": "Broad U.S. dollar index", "unit": "index", "frequency": "daily", "source": "Federal Reserve H.10 / FRED"},
    "us_2y": {"id": "DGS2", "label": "U.S. Treasury 2Y", "unit": "%", "frequency": "daily", "source": "U.S. Treasury / FRED"},
    "us_10y": {"id": "DGS10", "label": "U.S. Treasury 10Y", "unit": "%", "frequency": "daily", "source": "U.S. Treasury / FRED"},
    "vix": {"id": "VIXCLS", "label": "VIX", "unit": "index", "frequency": "daily", "source": "CBOE / FRED"},
    "wti": {"id": "DCOILWTICO", "label": "WTI crude oil", "unit": "USD/bbl", "frequency": "daily", "source": "EIA / FRED"},
}

RSS_FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html"),
]


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == ".":
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def fetch_fred_series(series_id: str) -> dict[str, Any]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    points: list[dict[str, Any]] = []
    for row in reader:
        date = row.get("DATE") or row.get("observation_date") or next(iter(row.values()), None)
        value = row.get(series_id)
        if value is None and len(row) >= 2:
            value = list(row.values())[1]
        number = to_float(value)
        if date and number is not None:
            points.append({"date": str(date), "value": number})
    if not points:
        raise RuntimeError(f"No usable observations for {series_id}")
    points = points[-420:]
    latest = points[-1]
    prev = points[-2] if len(points) > 1 else None
    return {
        "status": "ok",
        "series_id": series_id,
        "as_of": latest["date"],
        "latest": latest["value"],
        "previous": prev["value"] if prev else None,
        "change": latest["value"] - prev["value"] if prev else None,
        "history": points,
        "url": f"https://fred.stlouisfed.org/series/{series_id}",
    }


def text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    found = node.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def fetch_rss(source: str, url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        output: list[dict[str, Any]] = []
        for item in items[:12]:
            title = text(item, "title")
            link = text(item, "link")
            date = text(item, "pubDate") or text(item, "date")
            desc = clean_html(text(item, "description"))[:320]
            if title:
                output.append({"source": source, "title": title, "url": link, "published": date, "summary": desc})
        return output, {"source": source, "url": url, "status": "ok", "items": len(output)}
    except Exception as exc:
        return [], {"source": source, "url": url, "status": "error", "error": str(exc), "items": 0}


def main() -> None:
    series: dict[str, Any] = {}
    errors: list[str] = []
    for key, meta in SERIES.items():
        try:
            node = fetch_fred_series(meta["id"])
            node.update({k: v for k, v in meta.items() if k != "id"})
            series[key] = node
        except Exception as exc:
            errors.append(f"{key}: {exc}")
            series[key] = {"status": "error", **meta, "error": str(exc)}

    news: list[dict[str, Any]] = []
    feeds: list[dict[str, Any]] = []
    for source, url in RSS_FEEDS:
        items, health = fetch_rss(source, url)
        news.extend(items)
        feeds.append(health)

    # Preserve source ordering and cap payload. We deliberately do not machine-summarize headlines.
    news = news[:24]
    ok_series = sum(1 for x in series.values() if x.get("status") == "ok")
    payload = {
        "schema_version": "1.0.0",
        "generated_at": NOW.isoformat(),
        "status": "ok" if ok_series >= 5 else ("partial" if ok_series else "error"),
        "freshness_class": "near-real-time / source-release cadence",
        "accuracy_policy": "Official/primary releases are preferred. Rootvalue stores source dates separately from fetch time and never labels delayed official statistics as real-time.",
        "series": series,
        "news": news,
        "feeds": feeds,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "series_ok": f"{ok_series}/{len(SERIES)}", "news": len(news), "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
