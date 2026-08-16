# Rootvalue

Rootvalue là hệ thống nghiên cứu đầu tư cá nhân cho thị trường Việt Nam, kết hợp phân tích từ trên xuống về dòng tiền với phân tích doanh nghiệp từ dưới lên.

## Luận điểm sản phẩm

> Cho tôi biết tiền đang ở đâu, điều gì đã thay đổi và doanh nghiệp nào đáng điều tra sâu hơn.

Rootvalue không đưa khuyến nghị MUA / BÁN / NẮM GIỮ và không gom dữ liệu thành một điểm số đầu tư giả chính xác. Hệ thống ưu tiên dữ liệu gốc, độ mới, nguồn gốc và phát hiện thay đổi.

## Data Foundation — ưu tiên số 1

Rootvalue chỉ coi nền dữ liệu là `READY` khi:

- mọi doanh nghiệp cấu hình có tối thiểu **8 kỳ BCTC năm**;
- lịch sử tiền tệ từ 2018 có đủ các biến cốt lõi cho SBV State: tỷ giá, liên ngân hàng, lãi suất điều hành, OMO, tín dụng, cung tiền và CPI;
- dữ liệu chính thức NHNN và dữ liệu từ provider được tách provenance;
- dữ liệu thiếu giữ nguyên trạng thái thiếu, không nội suy hoặc tạo số mẫu.

Chi tiết: `docs/DATA_FOUNDATION.md`.

## Phạm vi V1

1. **Tổng quan** — trạng thái hệ thống, độ mới dữ liệu, các thay đổi cần chú ý.
2. **Dòng tiền hệ thống** — áp lực bên ngoài → tỷ giá / phản ứng NHNN → thanh khoản VND → phân bổ tài sản.
3. **Dòng tiền thị trường** — sức mạnh tương đối, mức tham gia và vị trí trong biên 20 phiên của danh sách theo dõi.
4. **Doanh nghiệp** — báo cáo tài chính theo chuỗi thời gian: cân đối kế toán, kết quả kinh doanh, lưu chuyển tiền tệ và tỷ số tài chính.
5. **Dữ liệu** — nguồn, lần cập nhật, lỗi và trường còn thiếu.

## Tự động hóa

```text
Vnstock / Vnstock Data / NHNN chính thức
            ↓
scripts/build_foundation.py
            ↓
coverage QC + provenance + giữ snapshot tốt hơn
            ↓
data/foundation/
            ↓
scripts/publish_foundation.py
            ↓
data/rootvalue.json
            ↓
rootvalue-bot commit
            ↓
GitHub Pages
```

`.github/workflows/update-data.yml` chạy 06:15 ICT mỗi ngày, chạy thủ công và tự chạy khi data pipeline/config thay đổi.

## BCTC 8 năm

Nguồn V1 là MAS thông qua Vnstock.

- Guest mode có thể không đủ 8 kỳ.
- API key cộng đồng cho phép truy cập tối đa 8 kỳ tài chính.
- Nếu runner có `vnstock_data`, Rootvalue ưu tiên provider này để lấy lịch sử dài hơn.

Tạo GitHub Actions secret:

```text
VNSTOCK_API_KEY=<api-key-của-bạn>
```

Đường dẫn: **Repository → Settings → Secrets and variables → Actions → New repository secret**.

Mỗi file `data/foundation/companies/<TICKER>.json` ghi rõ `annual_periods`, `annual_years`, `minimum_met`, provider và lỗi nếu có.

## SBV State data

Rootvalue dùng hai lớp:

- **Primary official:** các bảng công khai trên website Ngân hàng Nhà nước Việt Nam để đối chiếu và giữ provenance chính thức.
- **Historical normalized:** `vnstock_data Macro` khi quyền truy cập/package tồn tại, yêu cầu lịch sử từ 2018 cho interbank, policy rate, OMO, credit, money supply, CPI, FX và các biến bổ trợ.

Nếu thiếu chuỗi bắt buộc, `state_engine` ở trạng thái `blocked_by_missing_history`; hệ thống chưa được phép sinh xác suất easing/defend.

## Ngôn ngữ và giao diện

- `VIE / ENG`: toàn bộ giao diện chuyển theo một ngôn ngữ.
- Sáng / Tối: lưu lựa chọn trên trình duyệt.
- Typography ưu tiên `OpenAI Sans` nếu có trên máy, sau đó rơi về system UI font; không đóng gói font riêng trong repository.

## Chạy cục bộ

```bash
python -m pip install -r requirements.txt
python scripts/build_foundation.py
python scripts/publish_foundation.py
python -m http.server 8000
```

Mở `http://localhost:8000`.

## Danh sách theo dõi hiện tại

V1 dùng danh sách nhỏ để kiểm định pipeline trước khi mở rộng toàn thị trường. Chỉnh tại `config/watchlist.json`.
