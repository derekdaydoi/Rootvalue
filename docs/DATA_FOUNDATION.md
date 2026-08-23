# Rootvalue Data Foundation

## Definition of Done

Rootvalue chỉ coi Data Foundation là `READY` khi đồng thời đạt:

1. Mỗi doanh nghiệp trong `fundamental_symbols` có tối thiểu **8 kỳ cho từng BCTC năm cốt lõi**: `balance_sheet`, `income_statement`, `cash_flow`.
2. Các chuỗi lịch sử bắt buộc cho SBV State có dữ liệu: `exchange_rate`, `interbank_rate`, `policy_rate`, `omo`, `credit`, `money_supply`, `cpi`.
3. Dữ liệu thiếu không được nội suy hoặc tạo số mẫu.
4. Dữ liệu chính thức của NHNN được lưu riêng với provenance `primary_official`; nguồn chuẩn hoá/API được đánh dấu `secondary_normalized_provider`.

## Financial history

Nguồn V1: MAS thông qua Vnstock.

- Guest mode có thể không đủ 8 kỳ.
- Khi GitHub Secret `VNSTOCK_API_KEY` được cấu hình, community access có thể trả tối đa 8 kỳ tài chính.
- Nếu môi trường đã được cài `vnstock_data`, Rootvalue ưu tiên provider này để lấy lịch sử dài hơn. `vnstock_data` là gói tài trợ cài qua Vnstock Installer, không phải dependency công khai có thể thêm thẳng vào `requirements.txt`.

GitHub Secret cần có:

`Settings → Secrets and variables → Actions → New repository secret`

Tên secret: `VNSTOCK_API_KEY`

Không commit API key vào repo.

`VNSTOCK_API_KEY` chỉ xác thực quyền dữ liệu; nó không tự cài `vnstock_data` trên GitHub-hosted runner. Khi runner chưa có gói tài trợ, manifest phải ghi rõ provider khả dụng và giữ trạng thái coverage chưa đạt thay vì báo `READY`.

## SBV / monetary history

Rootvalue tách hai lớp:

- **Primary official checks:** website Ngân hàng Nhà nước Việt Nam, hiện tự lấy các bảng công khai về tổng phương tiện thanh toán/tiền gửi và nghiệp vụ thị trường mở.
- **Historical normalized feed:** `vnstock_data Macro` khi package/quyền truy cập tồn tại trong runner. Pipeline yêu cầu lịch sử từ 2018 tới hiện tại cho interbank, policy rate, OMO, credit, money supply, CPI, FX và các biến bổ trợ.

Nếu historical provider chưa có, `macro.state_engine.status = blocked_by_missing_history`. Hệ thống không tự gán trạng thái easing/defend hay xác suất chính sách.

Mỗi quan sát chính thức phải có `source_observation_date` lấy từ nội dung nguồn. `fetched_at` chỉ mô tả thời điểm thu thập và tuyệt đối không được thay thế ngày quan sát. Một bảng tháng/sự kiện không được sao chép thành nhiều điểm theo ngày.

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

Automation tách theo chi phí và nguồn dữ liệu:

- `.github/workflows/update-data.yml`: company foundation/BCTC chạy mỗi Chủ nhật lúc 06:15 ICT; có thể chạy thủ công từ `main` khi cần.
- `.github/workflows/update-sbv.yml`: bảng NHNN chính thức chạy hằng ngày lúc 06:15 ICT, không phụ thuộc `VNSTOCK_API_KEY`.

Readiness thiếu độ phủ vẫn là báo cáo cảnh báo (`continue-on-error`). Lỗi code hoặc vi phạm `validate_data_contracts.py` vẫn làm workflow đỏ.

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

Pipeline so sánh chất lượng theo từng báo cáo và giữ snapshot tốt hơn nếu lần fetch mới rỗng, lỗi hoặc có độ phủ thấp hơn. Timestamp chỉ thay đổi không được tạo commit dữ liệu mới.

## Quality gates

- `scripts/validate_data_contracts.py`: kiểm định cấu trúc bắt buộc và làm fail build nếu dữ liệu công bố không an toàn hoặc tự mâu thuẫn.
- `scripts/validate_foundation.py`: báo cáo readiness/coverage. Thiếu quyền provider có thể làm báo cáo này fail mà không biến dữ liệu hiện có thành lỗi cấu trúc.
- `tests/`: khóa hồi quy cho selector BCTC, CFO, Capex/FCF, missing-value semantics và đồng bộ snapshot.
