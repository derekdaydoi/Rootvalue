# Rootvalue

Rootvalue là hệ thống nghiên cứu đầu tư cá nhân cho thị trường Việt Nam, kết hợp phân tích từ trên xuống về dòng tiền với phân tích doanh nghiệp từ dưới lên.

## Luận điểm sản phẩm

> Cho tôi biết tiền đang ở đâu, điều gì đã thay đổi và doanh nghiệp nào đáng điều tra sâu hơn.

Rootvalue không đưa khuyến nghị MUA / BÁN / NẮM GIỮ và không gom dữ liệu thành một điểm số đầu tư giả chính xác. Hệ thống ưu tiên dữ liệu gốc, độ mới, nguồn gốc và phát hiện thay đổi.

## Phạm vi V1

1. **Tổng quan** — trạng thái hệ thống, độ mới dữ liệu, các thay đổi cần chú ý.
2. **Dòng tiền hệ thống** — áp lực bên ngoài → tỷ giá / phản ứng NHNN → thanh khoản VND → phân bổ tài sản.
3. **Dòng tiền thị trường** — sức mạnh tương đối, mức tham gia và vị trí trong biên 20 phiên của danh sách theo dõi.
4. **Doanh nghiệp** — báo cáo tài chính theo chuỗi thời gian: cân đối kế toán, kết quả kinh doanh, lưu chuyển tiền tệ và tỷ số tài chính.
5. **Dữ liệu** — nguồn, lần cập nhật, lỗi và trường còn thiếu. Không có dữ liệu thì hiển thị `N/A`, không tự tạo số.

## Tự động hóa

Hai luồng GitHub Actions được tách riêng để tránh việc sửa giao diện vô tình gọi API dữ liệu nhiều lần:

```text
Nguồn dữ liệu
    ↓
scripts/update_data.py
    ↓
kiểm tra + chuẩn hóa + tính chỉ số
    ↓
data/rootvalue.json
    ↓
commit tự động
    ↓
GitHub Pages tự triển khai
```

- `.github/workflows/update-data.yml`: chạy theo lịch và khi bấm chạy thủ công.
- `.github/workflows/pages.yml`: chỉ triển khai website khi mã nguồn hoặc dữ liệu thay đổi.

## Lịch sử báo cáo tài chính 5–10 năm

V1 đặt mục tiêu **8 năm báo cáo năm** cho mỗi doanh nghiệp.

- Chế độ khách của Vnstock chỉ trả về tối đa 4 kỳ báo cáo.
- API key cộng đồng miễn phí có thể tăng lên tối đa 8 kỳ.
- Nếu cần đủ 10 năm hoặc hơn, Rootvalue phải dùng nguồn có lịch sử dài hơn / quyền truy cập dữ liệu mở rộng.

Mỗi doanh nghiệp lưu `history.annual_periods`, `history.target_years` và `history.meets_minimum`; giao diện hiển thị đúng độ phủ thực tế.

### Cấu hình API key Vnstock

Tạo GitHub Actions secret:

```text
VNSTOCK_API_KEY=<api-key-của-bạn>
```

Đường dẫn: **Repository → Settings → Secrets and variables → Actions → New repository secret**.

Workflow đã truyền biến môi trường này cho thư viện. Nếu secret chưa có, pipeline tự chạy ở chế độ khách với tốc độ chậm hơn để tránh vượt giới hạn truy cập.

## Ngôn ngữ và giao diện

Rootvalue có hai công tắc độc lập:

- `VIE / ENG`: toàn bộ giao diện chuyển theo một ngôn ngữ, không trộn nhãn Việt–Anh.
- Sáng / Tối: lưu lựa chọn trên trình duyệt.

Typography ưu tiên `OpenAI Sans` nếu có trên máy, sau đó rơi về system UI font; không đóng gói font riêng trong repository.

## Chạy cục bộ

```bash
python -m pip install -r requirements.txt
python scripts/update_data.py
python -m http.server 8000
```

Mở `http://localhost:8000`.

## GitHub Pages

Bật **Settings → Pages → Source: GitHub Actions**.

## Danh sách theo dõi hiện tại

V1 dùng danh sách nhỏ để kiểm định pipeline và giao diện trước khi mở rộng toàn thị trường. Chỉnh tại `config/watchlist.json`.
