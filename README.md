# Rootvalue

Rootvalue là hệ thống research đầu tư cá nhân cho thị trường Việt Nam, kết hợp top-down money flow và bottom-up fundamental analysis.

## Product thesis

> Show me where money is, what changed, and which business deserves investigation.

Rootvalue **không** đưa BUY / SELL / HOLD và không biến dữ liệu thành một investment score giả chính xác. Hệ thống ưu tiên 4 thứ: dữ liệu gốc, độ mới, provenance và change detection.

## V1 scope

1. **Overview** — trạng thái hệ thống, data freshness, các biến cần chú ý.
2. **Money Flow** — causal map: external pressure → FX/SBV reaction → VND liquidity → market allocation.
3. **Market Flow** — relative strength, participation và 20D range position của watchlist.
4. **Company** — BCTC theo time-series: Balance Sheet, Income Statement, Cash Flow + các ratio nền tảng.
5. **Data** — nguồn, lần cập nhật, lỗi và missing fields. Không có data thì hiển thị `N/A`, không fabricate.

## Automation

GitHub Actions chạy Python theo lịch và khi bấm manual dispatch:

```text
Data providers
    ↓
scripts/update_data.py
    ↓
validate + normalize + derive
    ↓
data/rootvalue.json
    ↓
HTML/CSS/JS static frontend
    ↓
GitHub Pages
```

### Data policy

- Market + fundamental: ưu tiên `vnstock` community API ở V1.
- Macro/SBV: adapter riêng; nếu nguồn không khả dụng hoặc schema thay đổi, pipeline ghi rõ lỗi và giữ dữ liệu cũ thay vì tự suy diễn.
- Mỗi section có `source`, `as_of`, `status`.
- Derived metric luôn có công thức trong code.
- V1 không gọi price move = “money flow” nếu chỉ có OHLCV. Thuật ngữ dùng là **relative strength / participation**.

## Local run

```bash
python -m pip install -r requirements.txt
python scripts/update_data.py
python -m http.server 8000
```

Mở `http://localhost:8000`.

## GitHub Pages

Workflow `.github/workflows/update-data.yml` vừa cập nhật data vừa deploy Pages. Repo cần bật **Settings → Pages → Source: GitHub Actions**.

## Current watchlist

V1 dùng một watchlist nhỏ để kiểm định pipeline và UI trước khi mở rộng universe. Chỉnh tại `config/watchlist.json`.

---

Personal research system. Evidence first.
