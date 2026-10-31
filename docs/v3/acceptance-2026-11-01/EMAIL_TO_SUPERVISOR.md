**Tiêu đề:** Báo cáo cập nhật NSO Clinical và kết quả kiểm thử phần mềm – 01/11/2026

Kính gửi Thầy,

Em xin báo cáo tiến độ cập nhật hệ thống NSO theo workflow AI-PC V3.0/V3.1 như sau:

**1. Giao diện và quy trình sử dụng**

Em đã tổ chức lại giao diện thành hai khu vực Patient care và Research & engineering, sử dụng thiết kế clinical với tông xanh dương, bố cục cô đọng và sidebar tự thu gọn. Luồng lâm sàng được sắp xếp theo trình tự nhập hồ sơ → xác nhận dữ liệu → tạo khuyến nghị → phê duyệt → theo dõi/tái khám. Các biểu mẫu nghiên cứu và manufacturing được trình bày theo tác vụ và phân quyền người dùng.

Em cũng đã bỏ số đo mẫu khỏi form lâm sàng ban đầu, liên kết baseline với dữ liệu đã xác nhận và bổ sung cơ chế hủy kết quả/phê duyệt cũ khi dữ liệu thay đổi. Khi refit tạo khuyến nghị mới, hệ thống yêu cầu phê duyệt lại trước bước gửi tiếp.

**2. Kết quả kiểm thử bản hiện tại**

- Backend: 598 test đạt, 0 lỗi, 1 test được skip; chạy với PostgreSQL UTF-8 riêng.
- Frontend: 20 test đạt; production build thành công.
- Kiểm tra HTTP: 76 kiểm tra đạt cho research, manufacturing/shadow và đánh giá three-arm.
- Docker: build và khởi động thành công; đã kiểm tra health và chặn truy cập khi chưa cấu hình xác thực.
- Đã kiểm tra có trọng điểm trên desktop các luồng clinical, phân quyền, nghiên cứu và review/manufacturing. Các lỗi phát hiện về input ngày và thiếu module xác thực trong Docker đã được sửa và kiểm tra lại.

Toàn bộ dữ liệu dùng trong lượt kiểm thử này là dữ liệu tổng hợp. Kết quả trên xác nhận hoạt động phần mềm trong phạm vi đã kiểm tra, chưa chứng minh hiệu quả lâm sàng hoặc độ chính xác trên bệnh nhân thật. UAT desktop chưa bao phủ toàn bộ import/bulk, training/release/rollback, hết phiên và mất mạng; remote CI cũng chưa được xác nhận trong lượt nghiệm thu này.

**3. Phần cần tiếp tục để đáp ứng đầy đủ yêu cầu**

Em cần hoàn tất external/temporal validation, calibration, subgroup/OOD và đánh giá giá trị tăng thêm của mô hình trên dữ liệu thật được phép sử dụng; kiểm định các giả định causal và prospective shadow evaluation cho IPM/V3.1; hiệu chuẩn optics bằng dữ liệu kính, vật liệu, quy trình và QC thực tế. Các bước UAT còn lại, kiểm thử triển khai/security/backup–restore và phê duyệt độc lập cũng cần được hoàn tất trước khi đưa vào sử dụng lâm sàng. Chức năng clinical-adaptive ranking vẫn được khóa theo các điều kiện kiểm định hiện tại.

Mã nguồn được lưu tại: https://github.com/bachng23/nso_software

Báo cáo và bằng chứng kiểm thử nằm trong thư mục `docs/v3/acceptance-2026-11-01/` của repository, với bản tổng hợp tại `REPORT.md`.

Em kính mong Thầy góp ý về thứ tự ưu tiên cho giai đoạn tiếp theo, đặc biệt là nguồn dữ liệu validation và tiêu chí nghiệm thu khoa học/quang học.

Em cảm ơn Thầy.

Trân trọng,
Bách
