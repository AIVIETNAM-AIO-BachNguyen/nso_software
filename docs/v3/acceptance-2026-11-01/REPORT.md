# Nghiệm thu phần mềm local ngày 1 tháng 11 năm 2026

Kết luận: hai regression đã được sửa; toàn bộ regression backend có PostgreSQL UTF-8 qua 598 test, frontend qua 20 test. Docker đã build và khởi động. Luồng nghiên cứu/manufacturing/shadow đã được kiểm tra qua HTTP và kiểm tra desktop có trọng điểm. Chưa thể nghiệm thu lâm sàng hoặc tuyên bố toàn bộ UI đã qua UAT: browser control bị tắt trong Work settings ở cuối lượt kiểm tra.

## Bản sửa trong lượt nghiệm thu

- Khôi phục nhãn `V2.2 · Clinical Decision Support — Knowledge-guided personalization engine` ở vị trí nhỏ gọn, giữ nguyên hai acceptance test thay vì bỏ yêu cầu.
- Sửa input ngày lâm sàng và form workflow nhận sự kiện `input` cùng với `change`. UAT ghi nhận giá trị ngày mới có thể bị mất khi sửa trường khác; sau sửa đã kiểm tra tái khám thành công. Test xác nhận assessment date đi vào baseline và ngày trong nested workflow được giữ sau khi sửa sibling field.
- Dockerfile chép thêm `clinical_admin_auth.py`, sửa lỗi đóng gói khiến container thiếu module mặc dù chạy source local được.
- Thêm `NSO_NEXT_DIST_DIR` để frontend UAT dùng `.next-uat`, không ghi đè build chính. Mặc định vẫn là `.next`.

## Bằng chứng kiểm thử

| Hạng mục | Kết quả | Artifact |
| --- | --- | --- |
| Full backend Python 3.12.16, PostgreSQL 16 UTF-8 riêng | **598 passed, 1 skipped, 0 failed**, 204.98 giây | `backend-tests-utf8.txt` |
| Frontend components và clinical workflow | **20 passed, 0 failed** | `frontend-tests.txt` |
| Next.js production build | **PASS** | `frontend-build.txt` |
| Research HTTP, training/review/deployment/serving và auth gates | **23 checks PASS** | `research-http.json` |
| Manufacturing + binary shadow, rollback/withdrawal | **32 checks PASS** | `manufacturing-http.json` |
| Three-arm support, ranking/abstention và design-value diagnostics | **21 checks PASS** | `multiarm-http.json` |
| Plan được reviewer duyệt trên desktop → lot/QC/exposure/outcome qua HTTP | **PASS**, trace đọc được | `desktop-chain-http-completion.json` |
| Docker image local | **PASS** | `docker-build.txt` |
| Container health và fail-closed | **PASS**: health 200; unprovisioned clinical/research access 503 | `container-http.json` |
| Diff whitespace | **PASS** | `git diff --check` |

Skip duy nhất: `test_nso_package.py:673`, fixture chưa vượt ngưỡng chiều cao phần tử. Đây là skip, không tính là test qua. Còn cảnh báo deprecation alias BlockingPortal của Starlette/AnyIO.

Lượt PostgreSQL đầu bị dừng sau khi phát hiện test cluster khởi tạo SQL_ASCII trả TEXT dạng bytes; đây là cấu hình test sai, không phải xung đột observation thực. Đã tạo database UTF-8 riêng và chạy lại toàn bộ thành công. `backend-tests.txt` là log chẩn đoán chưa hoàn tất, không dùng làm bằng chứng nghiệm thu.

## Phạm vi UAT desktop thực tế

Tất cả dùng bệnh nhân và thông số tổng hợp trên server 8001/8002, frontend UAT 3200. Không ghi vào database bệnh nhân thật, không gửi nhà máy hoặc thay đổi điều trị thực.

- Clinical: đăng nhập; chặn 17 input số thiếu; nhập hồ sơ → review → tạo recommendation; baseline OD/OS lấy đúng giá trị xác nhận, follow-up để trống; nhập ngày/số đo → đánh giá tái khám; refit tạo recommendation mới và nút gửi bị khóa chờ phê duyệt mới.
- Public demos: forecast có bảng baseline results; study có adjusted comparison; optical search có bảng candidate.
- Researcher: đăng nhập assigned cases, mở study records, tạo protocol và khóa validation policy qua form; manufacturing có plan/lot/QC/exposure/outcome theo roles của fixture.
- Reviewer: chỉ có manufacturing review; gửi ID không tồn tại bị từ chối; review độc lập plan tổng hợp được lưu qua form.
- Operator: có plan/review/lot/QC theo roles fixture; model governance chỉ có deploy/rollback, không có training. Ghi lot `SIMULATED` và QC `passed=true` qua UI.
- Ghi exposure trùng thời gian trên UI bị từ chối đúng. Ca thứ hai chưa có exposure được reviewer duyệt qua UI; bước lot/QC/exposure/outcome của ca này hoàn tất qua HTTP sau khi browser control bị tắt.
- Screenshots: `desktop-operator.jpg` và `desktop-optics.jpg`. Chúng thể hiện các màn hình đã kiểm tra, không chứng minh mọi mutation đều được chạy qua browser.

Không kiểm tra mobile theo yêu cầu người dùng. Chưa nghiệm thu bằng browser tất cả import/bulk files, chạy training/release/rollback toàn bộ qua UI, idle/session expiry, mất mạng và toàn bộ các trường hợp retry. Security/expiry/retry có automated API/component coverage nhưng không thay thế UAT desktop còn thiếu. Một số thao tác browser gặp timeout và cần đọc lại trạng thái; chỉ kết quả đã quan sát được mới ghi PASS.

## Docker và CI

Đã bật Docker Desktop đã cài, build image local `nso-acceptance:20261101` trên kiến trúc máy và chạy container loopback. Không push image. Container chưa provision credentials nên API protected trả `AUTH_NOT_CONFIGURED`/503; đây là fail-closed đúng hợp đồng, không phải xác nhận authenticated workflow trong container. Authenticated workflow được kiểm tra riêng trên staging source.

Remote GitHub Actions chưa được chạy trong lượt này. Không push branch, không deploy cloud, không có security sign-off hoặc cloud backup/restore/rollback rehearsal. Docker build/run local không đồng nghĩa CI và production acceptance đã xong.

## Điều còn cần từ yêu cầu của thầy

1. NPM: dữ liệu được phép sử dụng và external/temporal validation thật, calibration/subgroup/OOD đạt ngưỡng khóa trước; chưa chứng minh Transformer prototype cải thiện trên bệnh nhân NSO.
2. IPM/V3.1: assignment/causal assumptions được kiểm định, đủ sample size/overlap, prospective shadow evaluation và giá trị tăng thêm của design parameters trên dữ liệu thật; clinical-adaptive ranking vẫn bị tắt đúng gate.
3. Optics: simulator được hiệu chuẩn bằng kính/vật liệu/process và QC thật, dung sai được kỹ sư xác nhận; reference recipe không phải machine toolpath đã qualification.
4. Release: hoàn tất UAT desktop còn thiếu, remote CI và cloud/security/identity/TLS/backup/restore acceptance; ký xác nhận người chịu trách nhiệm và inventory.

Không có số test nào thay thế được các gate dữ liệu/khoa học, quang học và phê duyệt độc lập.

## Bản local bàn giao

Đã nạp production build mới tại `http://127.0.0.1:3100`. Kiểm tra `/`, `/research`, `/backend/api/health` đều trả 200 và clinical version label có trong HTML. Đã dừng frontend UAT 3200, backend UAT 8001/8002, container test và PostgreSQL test riêng; giữ backend 8000/frontend 3100 phục vụ người dùng. Docker Desktop đã được khởi động trong quá trình kiểm thử và được giữ chạy; không tác động các container/dịch vụ của dự án khác. Image và dữ liệu test được giữ để tái lập, không xóa dữ liệu.

Artifact được quét đối chiếu với các credential test: không có credential bị ghi vào log/report.

## Chốt bàn giao theo yêu cầu người dùng

Sau lượt nghiệm thu, đã dừng backend chính 8000 và frontend chính 3100 theo yêu cầu người dùng. Kiểm tra lại các cổng 3100, 8000, 3200, 8001 và 8002 không còn tiến trình lắng nghe. Frontend được chạy lại 20 test thành công trước khi commit. Mail báo cáo dự thảo nằm tại `EMAIL_TO_SUPERVISOR.md`; chưa gửi mail.
