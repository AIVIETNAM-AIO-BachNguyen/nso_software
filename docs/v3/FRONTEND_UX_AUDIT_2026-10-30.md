# Rà soát frontend NSO — 30/10/2026

Frontend hiện có nền tảng phân nhóm dữ liệu, nhưng chưa tổ chức thành một quy trình làm việc liền mạch. Việc làm lại kiến trúc thông tin và quản lý trạng thái là hợp lý; thay màu sắc, font và bố cục đơn thuần sẽ không giải quyết các vấn đề chính.

## Phạm vi và bằng chứng

- Đọc toàn bộ các màn hình và component trong `src/frontend/app`, CSS và bộ test frontend hiện tại.
- Mở frontend đang chạy ở `http://127.0.0.1:3000`; đăng nhập bằng tài khoản staging được tài liệu dự án xác định là chỉ dùng cho bệnh nhân giả. Quan sát form lâm sàng và ba tab nghiên cứu ở chế độ demo.
- Kiểm tra DOM form lâm sàng: cả 13 input số đang hiển thị đều không có label được liên kết, không có `min`, `max`, `required`.
- Thử tạo kết quả với hồ sơ giả: giao diện báo `Failed to fetch`; lệnh kiểm tra từ shell trong sandbox cũng không kết nối được, nhưng điều đó chưa đủ để kết luận tiến trình backend đã dừng. Lượt triển khai sau xác nhận tiến trình vẫn chạy và endpoint predict trả HTTP 500. Không quy lỗi backend này cho frontend; vấn đề UX là thông báo lỗi hướng đến lập trình viên và không có hướng dẫn khôi phục phù hợp.
- Kết quả lâm sàng, tái khám và các workbench nghiên cứu có phân quyền được đánh giá qua mã nguồn; chưa xác minh toàn bộ các luồng đó trong trình duyệt ở lượt này.
- `npm test`: 14/14 test thành công. Đây là component test về hành vi và ràng buộc dữ liệu, không phải bằng chứng toàn bộ quy trình sử dụng đã tốt.
- Không sửa mã ứng dụng, không phê duyệt thiết kế, không gửi sản xuất, không triển khai model.

## Các vấn đề cần ưu tiên

P1 ở đây nghĩa là nên xử lý trước khi tiếp tục dùng frontend cho quy trình thực; P2 là vấn đề ảnh hưởng rõ đến khả năng sử dụng và bảo trì. Đây là mức ưu tiên sửa frontend, không phải đánh giá mức độ an toàn y khoa.

| Ưu tiên | Phát hiện | Tác động | Bằng chứng |
| --- | --- | --- | --- |
| P1 | Chọn bệnh nhân chỉ đổi ID và reset form về dữ liệu mẫu | Người dùng có thể tưởng số đang hiển thị thuộc bệnh nhân vừa chọn; không có bước đọc hồ sơ và xác nhận nguồn dữ liệu | `app/page.js` — `DEFAULTS`, `clearClinicalData`, bộ chọn Assigned patient |
| P1 | Tái khám dùng baseline, số đo và ngày cố định, độc lập với lần khám đầu | Không hình thành chuỗi hồ sơ → lần khám đầu → thiết kế → lần tái khám; người dùng phải tự nhập lại và tự đối chiếu | `app/page.js` — state `fu`, `goFollowup`, `setFuVal` |
| P1 | Form lâm sàng thiếu kiểm tra dữ liệu trước khi gửi; ô trống chuyển thành 0 | Không phân biệt rõ chưa nhập và giá trị bằng 0; lỗi có thể chỉ xuất hiện sau khi gọi API. Backend có thể chặn dữ liệu sai, nhưng UI chưa hỗ trợ người nhập sửa ngay tại trường | `app/page.js` — `num`, `predictBody`, `NumField` |
| P1 | Đánh giá tái khám gọi API khi vào màn hình và sau mỗi thay đổi; lỗi bị bỏ qua, kết quả cũ được giữ lại | Khi request mới thất bại, kết quả cũ vẫn có thể được trình bày cạnh dữ liệu mới mà không có cảnh báo lỗi rõ ràng | `app/page.js` — `runFollowup`, `goFollowup`, `setFuVal` |
| P1 | Trạng thái phê duyệt chưa gắn chặt với phiên bản thiết kế trong frontend | `runRefit()` thay `pred` và xóa `job`, nhưng không xóa `approval`; UI có thể còn hiển thị “Approved” của thiết kế trước. Cần xác minh và sửa bất kể backend vẫn kiểm tra quyền phê duyệt | `app/page.js` — `runRefit`, `Screen2` |
| P2 | Điều hướng theo V2.2/V3 và nhóm thuật toán | Người dùng phải tự hiểu mối quan hệ giữa fitting, nghiên cứu, thiết kế quang học, model và sản xuất | `app/page.js` — `research-entry`; `app/research/page.js` — header và tab |
| P2 | Ba tab nghiên cứu không bao quát các khối phía dưới | StudyRecords, ModelWorkbench và ExtensionWorkbench được render ngoài điều kiện tab; với quyền tương ứng, các việc khác mục tiêu vẫn xuất hiện trong cùng trang | `app/research/page.js` — các workbench cuối component `ResearchPage` |
| P2 | Nhiều thao tác quan trọng là nhập ID, tải JSON và đọc JSON kết quả | Đây là cách làm phù hợp hơn với công cụ kỹ thuật; người dùng phải tìm record liên quan, ghép dữ liệu và nhớ thứ tự thủ công | `app/research/ExtensionWorkbench.js` — `template`, form upload và kết quả; `ModelWorkbench.js`, `StudyRecords.js` |
| P2 | Form dài, chưa có trạng thái hoàn thành từng nhóm và bản tóm tắt trước khi tạo kết quả | Người dùng khó biết đang thiếu gì, dữ liệu nào đã được kiểm tra và bước tiếp theo là gì. Tier 2/3 có thu gọn, nhưng vẫn chỉ là phân nhóm trường | `app/page.js` — `Screen1`, hai `Disclosure` mở rộng |
| P2 | Màn hình kết quả ưu tiên Design ID và nhiều cụm chỉ số trước hành động cần làm | Quyết định, lý do chính, dữ liệu còn thiếu và bước tiếp theo chưa tạo thành một thứ bậc thông tin rõ ràng | `app/page.js` — `Screen2`, từ `design-hero` đến hàng nút cuối — đánh giá qua mã nguồn |
| P2 | Trạng thái tác vụ chưa rõ ràng | Lỗi lâm sàng hiện dạng “API error”/“Is the backend running”; tiến độ dài được đổi bằng timer, không phản ánh trạng thái thực từ server; job nghiên cứu yêu cầu refresh thủ công | `app/page.js` — `runPredict`; `app/research/ModelWorkbench.js` — hiển thị job |
| P2 | Accessibility và responsive chưa đồng đều | Nhãn không liên kết input; disclosure tự viết thiếu `aria-expanded`; một số grid kết quả và hàng nút dùng inline style cố định. Accessibility đã xác nhận bằng DOM; responsive là rủi ro từ mã nguồn, chưa kiểm chứng trên thiết bị nhỏ | `app/page.js` — `Disclosure`, `NumField`, `SelectField`, `Slider`, grid/hàng nút `Screen2` và `Screen3` |

Một điểm bổ sung: dữ liệu form, session và kết quả chủ yếu giữ trong React state. Chuyển giữa `/` và `/research` dùng thẻ `a`, không có cơ chế khôi phục bản nháp và ngữ cảnh hồ sơ ở tầng ứng dụng. Cần thiết kế lại khả năng tiếp tục công việc, đồng thời giữ yêu cầu bảo vệ dữ liệu và hết hạn phiên.

## Vì sao giao diện có cảm giác “loạn”

Các nhóm việc đang dùng những cấp điều hướng không tương xứng: phiên bản sản phẩm ở đầu trang, ba bước fitting, ba tab nghiên cứu, nhiều accordion và một dropdown chứa nhiều workflow. Người dùng không có một nơi thống nhất để trả lời: đang làm việc với ai, ở lần khám/nghiên cứu nào, dữ liệu đã đủ chưa và việc gì cần làm tiếp.

Về hình thức, card, màu sắc và font đã có một mức nhất quán. Cảm giác rối chủ yếu đến từ quá nhiều loại công việc đặt chung tầng, thông tin kỹ thuật lấn thông tin hành động và các bản ghi chưa được nối thành quy trình trên màn hình.

## Cấu trúc đề xuất cho lần làm lại

Tách khu vực theo công việc và vai trò. Người có nhiều quyền có thể chuyển khu vực, nhưng mỗi màn hình cần một mục tiêu chính.

| Khu vực | Nội dung chính |
| --- | --- |
| Công việc hôm nay | Hồ sơ cần hoàn thiện, lịch tái khám, yêu cầu đang chờ xử lý |
| Bệnh nhân | Danh sách có tìm kiếm → hồ sơ → timeline lần khám, thiết kế và theo dõi |
| Nghiên cứu | Nghiên cứu → protocol → tuyển mẫu → chất lượng dữ liệu → phân tích → báo cáo |
| Thiết kế & sản xuất | Yêu cầu thiết kế → ứng viên → đánh giá → kế hoạch → lô → QC → truy vết, theo quyền và các gate hiện có |
| Mô hình & quản trị | Dataset → training job → validation → independent review → deployment/rollback, theo quyền |

Luồng lâm sàng đề xuất:

**Chọn bệnh nhân → chọn/tạo lần khám → nhập và xác minh dữ liệu → xem tóm tắt → tạo khuyến nghị → đánh giá/phê duyệt theo điều kiện → theo dõi bàn giao → tái khám từ hồ sơ đã lưu.**

Mỗi bước nên có ngữ cảnh bệnh nhân/lần khám luôn hiện, trạng thái dữ liệu rõ ràng, thông báo lỗi tại trường và một hành động chính. Mọi kết quả/phê duyệt phải gắn với đúng phiên bản dữ liệu và thiết kế. Dữ liệu mẫu chỉ xuất hiện trong chế độ demo được nhận diện rõ.

Luồng nghiên cứu cần thể hiện quan hệ phụ thuộc và trạng thái từng bản ghi. Thay việc tự chép ID bằng danh sách chọn bản ghi có tên, ngày, trạng thái và liên kết chi tiết. JSON có thể giữ cho nhập hàng loạt hoặc công cụ chuyên gia; thao tác thường ngày cần form và bước kiểm tra trước khi gửi.

## Thứ tự thực hiện

1. Chốt vai trò, sơ đồ màn hình và vòng đời bản ghi; phân biệt trạng thái bệnh nhân, lần khám, thiết kế, phê duyệt và job.
2. Sửa các lỗi P1: dữ liệu mẫu, baseline tái khám, validation, kết quả cũ và phê duyệt theo phiên bản.
3. Làm trọn một luồng bệnh nhân từ đầu đến tái khám, bao gồm đọc lại hồ sơ và tiếp tục bản nháp theo chính sách dữ liệu.
4. Đưa nghiên cứu, mô hình và sản xuất vào khu vực riêng; thay các chuỗi JSON/ID thủ công bằng thao tác trên bản ghi.
5. Chuẩn hóa component, typography, khoảng cách, bàn phím, responsive và các trạng thái loading/empty/error/success.
6. Kiểm tra bằng các kịch bản xuyên suốt: đổi bệnh nhân, sửa dữ liệu sau khi tạo kết quả, refit sau phê duyệt, mất kết nối khi tái khám và quay lại hồ sơ sau khi hết phiên.

Giữ lại các phần đang có giá trị: phân quyền, phân biệt measured/imputed/missing trong nghiên cứu, audit trail, phê duyệt độc lập và các ràng buộc bảo vệ thiết kế. Frontend mới cần làm các ràng buộc đó dễ hiểu và dễ thao tác hơn.

Ảnh form thực tế trong lượt rà soát: [frontend-audit-clinical-2026-10-30.jpg](frontend-audit-clinical-2026-10-30.jpg).
