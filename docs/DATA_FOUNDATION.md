# Rootvalue Data Foundation

## Definition of Done

Rootvalue chỉ coi Data Foundation là `READY` khi đồng thời đạt:

1. Mỗi doanh nghiệp trong `fundamental_symbols` có tối thiểu **8 kỳ BCTC năm**.
2. Các chuỗi lịch sử bắt buộc cho SBV State có dữ liệu: `exchange_rate`, `interbank_rate`, `policy_rate`, `omo`, `credit`, `money_supply`, `cpi`.
3. Dữ liệu thiếu không được nội suy hoặc tạo số mẫu.
4. Dữ liệu chính thức của NHNN được lưu riêng với provenance `primary_official`; nguồn chuẩn hoá/API được đánh dấu `secondary_normalized_provider`.

## Financial history

Nguồn V1: MAS thông qua Vnstock.

- Guest mode có thể không đủ 8 kỳ.
- Khi GitHub Secret `VNSTOCK_API_KEY` được cấu hình, community access có thể trả tối đa 8 kỳ tài chính.
- Nếu môi trường có `vnstock_data`, Rootvalue ưu tiên provider này để lấy lịch sử dài hơn.

GitHub Secret cần có:

`Settings → Secrets and variables → Actions → New repository secret`

Tên secret: `VNSTOCK_API_KEY`

Không commit API key vào repo.

## SBV / monetary history

Rootvalue tách hai lớp:

- **Primary official checks:** website Ngân hàng Nhà nước Việt Nam, hiện tự lấy các bảng công khai về tổng phương tiện thanh toán/tiền gửi và nghiệp vụ thị trường mở.
- **Historical normalized feed:** `vnstock_data Macro` khi package/quyền truy cập tồn tại trong runner. Pipeline yêu cầu lịch sử từ 2018 tới hiện tại cho interbank, policy rate, OMO, credit, money supply, CPI, FX và các biến bổ trợ.

Nếu historical provider chưa có, `macro.state_engine.status = blocked_by_missing_history`. Hệ thống không tự gán trạng thái easing/defend hay xác suất chính sách.

## Output

Generated files:

```text
data/foundation/manifest.json
data/foundation/macro.json
data/foundation/companies/<TICKER>.json
data/rootvalue.json
```

`manifest.json` là source of truth cho QC, gồm số kỳ BCTC thực tế của từng mã và các biến macro còn thiếu.

## Automation

`.github/workflows/update-data.yml` chạy lúc 06:15 ICT mỗi ngày và khi code/config của data pipeline thay đổi.

```text
Providers
  ↓
build_foundation.py
  ↓
raw provider payload + provenance + coverage QC
  ↓
data/foundation/*
  ↓
publish_foundation.py
  ↓
data/rootvalue.json
  ↓
Git commit by rootvalue-bot
  ↓
GitHub Pages deploy
```

Pipeline giữ snapshot cũ nếu lần fetch mới có ít kỳ BCTC hơn snapshot đang lưu.
