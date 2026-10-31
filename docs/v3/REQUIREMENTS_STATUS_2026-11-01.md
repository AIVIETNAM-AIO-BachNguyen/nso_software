> Cập nhật sau xử lý: xem [báo cáo nghiệm thu hiện hành](acceptance-2026-11-01/REPORT.md). Hai lỗi ghi dưới đây đã được sửa; regression mới đạt 598 backend và 20 frontend test. Nội dung bên dưới giữ lại làm snapshot trước sửa.

# Đối chiếu yêu cầu và kiểm thử ngày 1 tháng 11 năm 2026

Bản hiện tại có nền tảng phần mềm nghiên cứu và giao diện desktop chạy được, nhưng chưa đủ căn cứ nghiệm thu toàn bộ V3.0/V3.1 theo yêu cầu của thầy. Không coi test phần mềm trên fixture tổng hợp là xác thực khoa học hoặc cho phép dùng lâm sàng.

## Nguồn đối chiếu

Tài liệu gốc: `/Users/bachng/Downloads/NSO_AI-PC_V3.0_V3.1_Engineering_Workflow_EN.docx`, bản 1.0 ngày 20/10/2026. Đã đọc toàn bộ nội dung chữ, gồm bảng và checklist. Đối chiếu thêm mã nguồn và báo cáo triển khai 26, 28, 29/10; báo cáo 23/10 đã lỗi thời và không phản ánh mô hình ba nhánh hiện có.

## Kiểm thử mới chạy

- `npm test` tại `src/frontend`: **19 passed**, không lỗi/skip.
- `OMP_NUM_THREADS=1 .venv312/bin/python -m pytest -q src/backend`: **581 passed, 2 failed, 16 skipped**, 140.31 giây; một cảnh báo deprecation Starlette/AnyIO.
- Hai test lỗi: `test_v21_acceptance.py::test_supervisor_copy_and_medical_claim_disclaimer_are_present` và `test_v22_acceptance.py::test_frontend_uses_v22_clinical_language_and_no_false_probabilities`. Chúng dừng ở assertion tìm nhãn phiên bản/clinical wording trong `app/page.js`; nhãn bị bỏ khi làm lại giao diện. Không có bằng chứng từ hai lỗi này rằng thuật toán dự báo sai. Đồng thời không được bỏ qua chúng rồi tuyên bố regression hoàn toàn qua. Cần quyết định cách giữ nội dung bắt buộc và cập nhật phép kiểm tra phù hợp với cấu trúc component mới.
- Các skip bao gồm kiểm tra PostgreSQL chưa có `NSO_TEST_POSTGRES_URL` và fixture ngưỡng chiều cao phần tử cũ. Chưa xác minh lại toàn bộ PostgreSQL trong lượt này.
- Production build đã qua trên mã hiện tại trong lượt sửa sidebar gần nhất. Lượt đối chiếu này không thay đổi mã ứng dụng.
- Browser desktop đã kiểm tra có trọng điểm: đăng nhập, form trống/nhãn trường, bước review, bản nháp theo bệnh nhân/chuyển khu vực, phân khu nghiên cứu, bố cục gọn và sidebar hover 64 → 244 → 64px, nội dung không xê dịch. Chưa chạy toàn bộ tác vụ nghiên cứu qua browser với mọi vai trò và lỗi mạng/hết phiên. Mobile bỏ qua theo chỉ dẫn của người dùng.
- HTTP local trước đó xác nhận `/api/predict` và `/api/followup` trả 200 sau sửa lỗi recipe lịch sử. Đây không phải kiểm thử toàn chuỗi sản xuất/ML của bản frontend cuối.

## Đối chiếu với workflow gốc

| Nhóm yêu cầu của thầy | Phần đã có | Phần chưa đủ để nghiệm thu |
| --- | --- | --- |
| Sprint 0 và bảo toàn V2.2 | Inventory, ánh xạ entity/API, migration cộng thêm, baseline và test | Chưa có inventory có người chịu trách nhiệm ký xác nhận; cấu hình hosting, quyền dữ liệu, consent/residency và rollback trên môi trường đích chưa được nghiệm thu. Hai regression về nội dung frontend hiện còn lỗi |
| Dữ liệu dọc và truy vết | Quan sát OD/OS có provenance; measured/imputed/missing; correction revision; protocol/enrollment; exposure; chuỗi prediction/design/recipe/lot/QC/outcome | Cần dữ liệu thật có quyền sử dụng, kiểm định nguồn đo và lịch sử điều trị đầy đủ. Bản nháp UI trong bộ nhớ không phải hệ thống hồ sơ/lịch khám bền vững |
| NPM | Carry-forward, linear history, mixed effects, boosting, Transformer nhỏ; patient-disjoint splits, calibration và artifact governance | Chưa có báo cáo hiệu năng NSO trên bệnh nhân thật với external/temporal validation, subgroup/OOD và calibration đạt ngưỡng đã khóa. Transformer độc lập là prototype, không phải tái tạo MPPM và chưa được chứng minh vượt baseline trên dữ liệu thật |
| IPM | Cohort khóa, ANCOVA/AIPW, overlap/ESS, sensitivity và mô hình DR nhiều nhánh ở phần mở rộng | Chưa có xác nhận assignment/exchangeability, đủ mẫu/overlap và bằng chứng causal trên nghiên cứu thật. Chưa thể công bố ITE/CATE cá nhân đã xác thực |
| Optical Optimizer | Scalar reference simulator, PSF/MTF, search đa mục tiêu, Pareto, kiểm tra perturbation; thông số bảo vệ phía server | Chưa hiệu chuẩn/xác thực bằng kính, vật liệu, cấu trúc và QC thật; chưa có miền quy trình/dung sai được kỹ sư xác nhận. Ranking tham chiếu không chứng minh hiệu quả kiểm soát cận |
| V3.1 | Một mô hình ba nhánh cùng comparator, support/abstention, shadow ranking và kiểm tra predictive design-value trên fixture | Chưa có prospective shadow study, clinical outcomes độc lập, giá trị tăng thêm của design parameters trên dữ liệu thật, và sign-off khoa học/ethics/safety. Clinical adaptive ranking vẫn bị tắt; đây là hành vi phù hợp gate của tài liệu |
| API, governance và triển khai | Auth/patient scope, audit/idempotency, approval/review/deploy/rollback; cấu hình service tách logic, CI/Docker và staging local | Chưa có security/release review độc lập; remote CI và container/cloud acceptance chưa được chứng minh bằng lượt chạy mới; TLS/identity/secrets, rollback/restore trên hosting thật chưa nghiệm thu |
| UI và bàn giao | Clinical desktop mới, form nghiên cứu, phân khu công việc, sidebar tự thu gọn, trạng thái/error | Còn một số thao tác chuyên gia dùng ID/file JSON; chưa có UAT đầy đủ từ lúc nhập hồ sơ đến review/model/lot/QC/outcome theo từng vai trò. Tài liệu bàn giao cũ có các snapshot mâu thuẫn và cần tập hợp lại thành một trạng thái hiện hành |

Lưu ý: workflow gốc cho phép V3.0 IPM chỉ trả báo cáo nhóm nếu chưa đủ điều kiện cho ITE. Giữ ITE/clinical ranking ở trạng thái unavailable/shadow không phải thiếu cần mở bằng cách bỏ gate. Muốn đạt mức cao hơn phải có bằng chứng dữ liệu và phê duyệt tương ứng.

## Thứ tự xử lý

1. Sửa hai acceptance regressions và chạy lại các kiểm tra liên quan.
2. Chạy lại bộ test có PostgreSQL riêng; ghi rõ mọi skip và lý do, kiểm tra CI/container trong môi trường được chọn.
3. Làm desktop UAT theo kịch bản và vai trò: nhập/correction → forecast → protocol/cohort → analysis → optical candidate → independent review → lot/QC → exposure → follow-up → validation. Thử sai patient scope, dữ liệu thiếu, hết phiên, rút duyệt và retry.
4. Hoàn thiện các điểm UI còn phải ghép record thủ công; thống nhất bộ tài liệu bàn giao theo mã hiện tại.
5. Cùng thầy/nhóm xác lập dataset có quyền sử dụng, protocol/acceptance thresholds, bộ đo kính/QC và trách nhiệm review. Sau đó mới làm xác thực thật và prospective shadow study.

Không có tỷ lệ phần trăm hoàn thành đủ cơ sở để báo cáo: các gate khoa học, quang học và vận hành không thể quy đổi từ số test đã qua.
