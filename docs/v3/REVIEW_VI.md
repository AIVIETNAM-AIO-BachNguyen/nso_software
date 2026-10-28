> Historical snapshot from 23 October 2026. Superseded by [the 26 October engineering report](COMPLETION_2026-10-26.md).

# Kết quả tích hợp nghiên cứu vào NSO AI-PC

Ngày đánh giá: 23 tháng 10 năm 2026.

Website hiện tại là nền tảng V2.2 có thể mở rộng. Mã nguồn đã được bổ sung khu vực `/research`, giữ luồng fitting đang có và thêm chức năng nghiên cứu. Đây là bản tích hợp phần mềm đã kiểm thử tại máy, chưa phải phiên bản V3 đã được xác thực lâm sàng hay đã triển khai lên website production.

## Phần đã làm

- Xác minh bài nghiên cứu trên trang nhà xuất bản, đưa liên kết và trích dẫn vào giao diện.
- Thêm màn hình nghiên cứu với ba phần: dự báo tiến triển, nghiên cứu can thiệp và trạng thái tối ưu quang học.
- Có demo dùng dữ liệu hoàn toàn tổng hợp, tách biệt dữ liệu bệnh nhân và không lưu kết quả vào kho dữ liệu thật.
- Tái sử dụng định danh bệnh nhân/ca khám và dữ liệu V2; bổ sung số đo theo ngày, riêng OD/OS, phân biệt số đo thực, số suy diễn và giá trị thiếu.
- Chạy hai baseline minh bạch: giữ nguyên số đo gần nhất và hồi quy tuyến tính theo lịch sử của từng mắt. Hiển thị 6, 12, 24 tháng; không gán độ chính xác hay khoảng tin cậy chưa được xác thực.
- Đóng băng mốc dự báo, loại dữ liệu sau mốc, kiểm tra cả lịch sử điều trị V2/V3 và yêu cầu xác nhận lịch sử chưa điều trị.
- Đánh giá tái khám bằng ngày thực tế, ghi nhận sai số và thay đổi AL/SE khi đủ số đo thực.
- Tạo cohort cố định, báo cáo mô tả các nhóm can thiệp; xử lý hai mắt trong cùng bệnh nhân, ghi rõ trường hợp thiếu dữ liệu/đổi điều trị/ngừng điều trị bị loại.
- Bổ sung xác thực, phân quyền theo bệnh nhân, audit, chống ghi trùng khi gửi lại yêu cầu, schema/API, kiểm thử và hướng dẫn rollback.
- Tạo giao diện tác vụ tối ưu bất đồng bộ. Khi thiếu simulator đã hiệu chuẩn, tác vụ trả trạng thái bị chặn và không tạo thiết kế hay chỉ số quang học giả.

## Phần chưa thể hoàn thành từ dữ liệu hiện có

Không tìm thấy bộ dữ liệu lâm sàng hoặc trọng số mô hình dùng để huấn luyện V3 trong phạm vi mã nguồn đã khảo sát. Cũng chưa có bằng chứng về simulator đã hiệu chuẩn bằng mẫu kính và QC thực. Vì vậy không thể trung thực tuyên bố đã hoàn thành Transformer, mô hình hiệu quả điều trị cá nhân, thuật toán tối ưu quang học đã xác thực hay V3.1.

Các phần này cần thầy/nhóm cung cấp dữ liệu được phép sử dụng, lịch sử can thiệp đầy đủ, định nghĩa nghiên cứu và quyền truy cập triển khai. Chuyên gia quang học cần cung cấp simulator, miền thiết kế và dung sai sản xuất. Người phụ trách lâm sàng/QA cần xác lập tiêu chí kiểm định và phê duyệt độc lập.

Chưa thay đổi website production, chưa đẩy mã nguồn lên GitHub và chưa gửi thư cho thầy. Các thiết lập chức năng bệnh nhân V3 mặc định tắt. Cấu hình cloud, phục hồi backup thực tế, xác thực PostgreSQL và bảo mật các API V2 cũ vẫn cần kiểm tra trước khi triển khai có dữ liệu thật.

## Tài liệu bàn giao

- `IMPLEMENTATION_REVIEW.md`: đối chiếu từng yêu cầu với kết quả và phần còn thiếu.
- `RESEARCH_VERIFICATION.md`: kết quả kiểm chứng nguồn và giới hạn áp dụng.
- `VALIDATION.md`: bằng chứng kiểm thử và kiểm tra trình duyệt.
- `inventory.json`: danh mục API, ánh xạ thực thể và hash mã nguồn.
- `openapi.json`: hợp đồng API OpenAPI 3.1.
- `TEACHER_REPLY_DRAFT.md`: thư nháp tiếng Anh để báo cáo thầy, chưa gửi.
